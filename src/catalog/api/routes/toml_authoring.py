"""POST /toml/{kind} — backend-authoritative TOML generation (ADR-0001).

Validates posted JSON against the matching Pydantic model and is
status-discriminated: valid -> 200 with the clean value-only ``.toml`` body and
a ``Content-Disposition`` attachment header; invalid -> 422 with field-level
errors from ``ValidationError.errors()``. Output omits comments, the
``#:schema`` pragma, empty fields/tables, and directory-derived identity keys.
"""

from __future__ import annotations

import tomllib
from enum import Enum
from pathlib import Path

import tomli_w
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from loguru import logger
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.path_validation import validate_under_data_root
from catalog.api.schemas import MdRunOut
from schema.form_fields import FORM_FIELDS, FORM_META, FORM_SECTIONS
from schema.loader import drop_authored_group_ids
from schema.schema import AcquisitionFile, MdRun, ReconstructionFile, SampleRecord

router = APIRouter()

_META = {m.form: m for m in FORM_META}

# kind -> Pydantic model.
_MODELS: dict[str, type[BaseModel]] = {
    "md_run": MdRun,
    "acquisition": AcquisitionFile,
    "sample": SampleRecord,
    "reconstruction": ReconstructionFile,
}

# Composite forms: (section, field) pairs to strip from output — the
# directory-derived identity (is_id) and ingest-derived (derived) fields are
# never part of the file, no matter what the client posts. Built from the
# registry so a new derived field is dropped automatically. The dumped dict is
# by_alias, so a field whose model aliases it (e.g.
# ReconstructionAlignment.reconstruction_alignment_id -> "id") must be dropped
# by its alias, not its Python field name, or the pop is a silent no-op.
_SECTION_MODEL = {(fs.form, fs.section): fs.model for fs in FORM_SECTIONS}
_COMPOSITE_DROP: dict[str, list[tuple[str, str]]] = {}
for _ff in FORM_FIELDS:
    if _ff.is_id or _ff.derived:
        _model = _SECTION_MODEL.get((_ff.form, _ff.section))
        # FormSection.model defaults to `object`, which is truthy but has no
        # model_fields — getattr keeps a model-less section from breaking import.
        _finfo = getattr(_model, "model_fields", {}).get(_ff.field)
        _dumped_key = _finfo.alias if _finfo and _finfo.alias else _ff.field
        _COMPOSITE_DROP.setdefault(_ff.form, []).append((_ff.section, _dumped_key))

# kind -> top-level serialized (by_alias) id key to drop: the identity field is
# the directory name, not file content. Only flat forms post their id at the
# top level; composite forms (sample / acquisition) never post the
# directory-derived id at the top level, so there's nothing to strip there.
_ID_KEYS: dict[str, str] = {
    "md_run": "id",
}

# Sample sections backed by a 1:1 sub-entity table, for pull-from-API load.
_SAMPLE_SECTION_ORM: dict[str, type] = {
    "chromatin": orm.ChromatinORM,
    "fiducial": orm.FiducialORM,
    "freezing": orm.FreezingORM,
    "milling": orm.MillingORM,
}


def _enum_val(v):
    return v.value if isinstance(v, Enum) else v


def _toml_safe(v):
    """Make a ``model_dump`` value tomli_w-serializable and clean: enums become
    their value; empty tables/arrays are dropped (ADR-0001 "empties omitted").
    Dates stay native ``datetime.date`` so they serialize as TOML date literals
    (``mode='json'`` would stringify them into quoted strings)."""
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            sx = _toml_safe(x)
            if sx == [] or sx == {}:  # omit empty table / empty array
                continue
            out[k] = sx
        return out
    if isinstance(v, list):
        return [_toml_safe(x) for x in v]
    return v


def _field_errors(exc: ValidationError, model: type[BaseModel]) -> list[dict]:
    # Pydantic reports a missing field's loc by its alias ("id") but a bad
    # value's loc by the field name ("md_run_id"). Normalize the top-level loc
    # segment to the field name so the frontend maps every error to the same
    # form field. Also trim to JSON-safe keys (errors() can carry
    # non-serializable ctx objects).
    alias_to_field = {
        f.alias: name for name, f in model.model_fields.items() if f.alias
    }
    out = []
    for e in exc.errors():
        loc = list(e["loc"])
        if loc and loc[0] in alias_to_field:
            loc[0] = alias_to_field[loc[0]]
        out.append({"loc": loc, "msg": e["msg"], "type": e["type"]})
    return out


@router.post("/{kind}")
def author_toml(kind: str, payload: dict = Body(...)):
    model = _MODELS.get(kind)
    if model is None:
        raise HTTPException(404, f"unknown toml kind {kind!r}")
    if kind == "acquisition":
        # Same scrub the scanner's loader applies before validating an
        # acquisition.toml: a hand-authored reconstruction_alignment_id on a
        # tomogram/annotation block would split the per-group id-uniqueness
        # bucket and pass here while the scanner rejects the emitted file.
        # /toml/acquisition/parse returns unknown keys verbatim, so an uploaded
        # legacy file can carry one in. Reuse the loader helper so the two agree
        # by construction.
        drop_authored_group_ids(payload)
    try:
        obj = model.model_validate(payload)
    except ValidationError as exc:
        return JSONResponse(
            status_code=422, content={"errors": _field_errors(exc, model)}
        )

    # exclude_none drops unfilled optionals (TOML has no null); by_alias matches
    # the on-disk key names.
    dumped = obj.model_dump(by_alias=True, exclude_none=True)
    # Composite forms strip directory-derived identity + ingest-derived fields
    # per section before serialization; _toml_safe then prunes any section left
    # empty by that strip.
    meta = _META.get(kind)
    if meta and meta.composite:
        for section, fieldname in _COMPOSITE_DROP.get(kind, []):
            sub = dumped.get(section)
            if isinstance(sub, dict):
                sub.pop(fieldname, None)
    # _toml_safe coerces enums to their value, keeps dates native (TOML date
    # literals), and drops empty tables/arrays.
    data = _toml_safe(dumped)
    id_key = _ID_KEYS.get(kind)
    if id_key and isinstance(data, dict):
        data.pop(id_key, None)

    # extra="allow" lets arbitrary client keys through; a nested null (or other
    # non-TOML scalar) only surfaces here, where exclude_none can't reach it.
    # Keep the endpoint status-discriminated (ADR-0001): a serialization
    # failure is bad input -> 422, never an unhandled 500.
    try:
        body = tomli_w.dumps(data)
    except (TypeError, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={"errors": [{"loc": [], "msg": str(exc), "type": "toml_serialization"}]},
        )
    return Response(
        content=body,
        media_type="application/toml",
        headers={"Content-Disposition": f'attachment; filename="{kind}.toml"'},
    )


@router.post("/{kind}/parse")
def parse_toml(kind: str, payload: dict = Body(...)):
    """Seed mode: upload (ADR-0004). Parse a posted ``.toml`` body into form
    state with the backend ``tomllib`` loader — keeps TOML parsing off the
    frontend. Unknown/extra keys come through verbatim; the renderer splits
    registry fields from extras. Bad TOML -> 422 (no validation here; schema
    rules run on generate)."""
    if kind not in _MODELS:
        raise HTTPException(404, f"unknown toml kind {kind!r}")
    try:
        fields = tomllib.loads(payload.get("toml", ""))
    except tomllib.TOMLDecodeError as exc:
        return JSONResponse(
            status_code=422,
            content={"errors": [{"loc": [], "msg": str(exc), "type": "toml_parse"}]},
        )
    return {"fields": fields}


@router.get("/md-run-ids/{sample_id}")
def md_run_ids(sample_id: str, session: Session = Depends(get_session)):
    """md_source.md_run_id suggestions: the ids of the sample's known md_runs.
    Free-text remains accepted on submit; this only feeds the dropdown."""
    rows = (
        session.execute(
            select(orm.MdRunORM.md_run_id)
            .where(orm.MdRunORM.sample_id == sample_id)
            .order_by(orm.MdRunORM.md_run_id)
        )
        .scalars()
        .all()
    )
    return {"ids": list(rows)}


@router.get("/tilt-series-ids/{sample_id}/{acquisition_id}")
def tilt_series_ids(
    sample_id: str,
    acquisition_id: str,
    session: Session = Depends(get_session),
):
    """Tilt-series ids in one acquisition, for the reconstruction form.

    raw_tomogram.derived_from names a [[tilt_series]] in the acquisition's
    acquisition.toml — a different file, so the renderer's in-form cross-ref
    pooling cannot supply it.
    """
    rows = session.execute(
        select(orm.TiltSeriesORM.tilt_series_id)
        .where(orm.TiltSeriesORM.sample_id == sample_id)
        .where(orm.TiltSeriesORM.acquisition_id == acquisition_id)
        .order_by(orm.TiltSeriesORM.tilt_series_id)
    ).scalars()
    return {"ids": list(rows)}


@router.get("/reconstruction-group-ids/{sample_id}/{acquisition_id}")
def reconstruction_group_ids(
    sample_id: str,
    acquisition_id: str,
    session: Session = Depends(get_session),
):
    """Alignment-group folder names in one acquisition, for the reconstruction
    form's group selector.

    One reconstruction.toml per Reconstructions/<group>/ folder, so the form
    needs the acquisition's group list to offer switching between them. The
    author route carries no sample context of its own, so it can't read the
    acquisition detail payload — hence this ids endpoint, mirroring
    /tilt-series-ids.
    """
    rows = session.execute(
        select(orm.ReconstructionAlignmentORM.reconstruction_alignment_id)
        .where(orm.ReconstructionAlignmentORM.sample_id == sample_id)
        .where(orm.ReconstructionAlignmentORM.acquisition_id == acquisition_id)
        .order_by(orm.ReconstructionAlignmentORM.reconstruction_alignment_id)
    ).scalars()
    return {"ids": list(rows)}


def _authored_fields(
    form: str,
    section: str,
    *,
    exclude_id: bool = False,
    exclude_derived: bool = False,
) -> list[str]:
    """Authored columns of a form section, from the registry — keeps the load
    endpoint in step with what the form renders.

    Acquisition/md_run sections load their is_id field too (it seeds the
    placement hint and, per ADR-0004, locks read-only once loaded); the sample
    loader excludes it (and derived fields) since it sets those explicitly.
    """
    return [
        ff.field
        for ff in FORM_FIELDS
        if ff.form == form
        and ff.section == section
        and ff.authored
        and not (exclude_id and ff.is_id)
        and not (exclude_derived and ff.derived)
    ]


def _row_fields(row, names: list[str]) -> dict:
    """Authored, non-None columns of an ORM row, keyed by field name (enums
    coerced to their value)."""
    out = {}
    for name in names:
        v = getattr(row, name, None)
        if v is not None:
            out[name] = _enum_val(v)
    return out


def _dedupe_by_leaf_id(
    blocks: list[dict], id_field: str, section: str, seen: set | None = None
) -> list[dict]:
    """Collapse loaded blocks to one per leaf id (case-insensitively — see
    ``_case_insensitive_duplicates``), first (lowest group) wins.

    Tomogram/annotation rows are keyed by (…, reconstruction_alignment_id,
    <leaf>_id), so two alignment groups in one acquisition can each hold a
    ``denoised.mrc``. The flat acquisition.toml this form authors has one id
    namespace and cannot express the distinction —
    ``reconstruction_alignment_id`` is registry-classified as not authored, so
    the form can't even render the field that would tell the blocks apart.
    Returning both would render two byte-identical rows that ``POST
    /toml/acquisition`` then rejects as a duplicate id, with no way for the user
    to fix the form. Callers order by group then id, so "first" is
    deterministic. The dropped duplicates are logged, not returned: the response
    shape is a parsed-TOML-shaped ``fields`` dict, and anything added to it
    would be re-emitted into the generated file as an extra key.

    Pass a shared ``seen`` set to dedupe across sections: the validator checks
    raw and post-processed tomograms as one namespace, so the same stem living
    as raw in one group and post-processed in another collides too. Raw is
    visited first, so it wins that tie.
    """
    seen = set() if seen is None else seen
    out: list[dict] = []
    for block in blocks:
        leaf = block.get(id_field)
        # Membership is casefolded because the validator this dedupe exists to
        # satisfy is case-insensitive; the block itself is emitted unchanged.
        key = leaf.casefold() if isinstance(leaf, str) else leaf
        if key in seen:
            logger.warning(
                "toml load: dropping duplicate {} id {!r} — it exists in more "
                "than one Reconstructions/ group and the flat acquisition.toml "
                "form has a single id namespace; per-group metadata belongs in "
                "that group's reconstruction.toml",
                section,
                leaf,
            )
            continue
        seen.add(key)
        out.append(block)
    return out


def _load_md_run(record_id: str, session: Session) -> tuple[dict, str | None]:
    row = (
        session.execute(
            select(orm.MdRunORM).where(orm.MdRunORM.md_run_id == record_id)
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(404, f"no md_run with id {record_id!r}")
    fields = {
        name: getattr(row, name)
        for name in MdRunOut.model_fields
        if getattr(row, name, None) is not None
    }
    # md_run has no path column of its own: the on-disk directory is the
    # owning sample's directory + the MdRuns/{id} convention (mirrors the
    # scanner's layout). No relationship() exists on the ORM, so look the
    # sample up explicitly; a missing sample or unset sample.path -> null.
    sample = session.get(orm.SampleORM, row.sample_id)
    path = f"{sample.path}/MdRuns/{record_id}" if sample and sample.path else None
    return fields, path


def _load_acquisition(
    record_id: str, sample_id: str | None, session: Session
) -> tuple[dict, str | None]:
    """Reconstruct an acquisition's authored fields, shaped per-section like a
    parsed acquisition.toml, for the deep-link editor (ADR-0004). Composite
    identity is (sample_id, acquisition_id), so the edit link / route carries
    both (mirrors the acquisition detail route)."""
    if not sample_id:
        raise HTTPException(422, "sample_id query param required for acquisition")
    acq = session.get(orm.AcquisitionORM, (sample_id, record_id))
    if acq is None:
        raise HTTPException(404, f"no acquisition {record_id!r} in sample {sample_id!r}")
    acq_authored = _authored_fields("acquisition", "acquisition")
    fields: dict = {"acquisition": _row_fields(acq, acq_authored)}
    md = session.get(orm.MdSourceORM, (sample_id, record_id))
    if md is not None:
        md_fields = _row_fields(md, _authored_fields("acquisition", "md_source"))
        if md_fields:
            fields["md_source"] = md_fields
    ts_rows = (
        session.execute(
            select(orm.TiltSeriesORM)
            .where(
                orm.TiltSeriesORM.sample_id == sample_id,
                orm.TiltSeriesORM.acquisition_id == record_id,
            )
            .order_by(orm.TiltSeriesORM.tilt_series_id)
        )
        .scalars()
        .all()
    )
    ts_authored = _authored_fields("acquisition", "tilt_series")
    tilt_series = [_row_fields(ts, ts_authored) for ts in ts_rows]
    if tilt_series:
        fields["tilt_series"] = tilt_series

    ra_rows = (
        session.execute(
            select(orm.ReconstructionAlignmentORM)
            .where(
                orm.ReconstructionAlignmentORM.sample_id == sample_id,
                orm.ReconstructionAlignmentORM.acquisition_id == record_id,
            )
            .order_by(orm.ReconstructionAlignmentORM.reconstruction_alignment_id)
        )
        .scalars()
        .all()
    )
    ra_authored = _authored_fields("acquisition", "reconstruction_alignment")
    reconstruction_alignment = [_row_fields(ra, ra_authored) for ra in ra_rows]
    if reconstruction_alignment:
        fields["reconstruction_alignment"] = reconstruction_alignment

    # Processing log (ADR-0004): loaded entries seed read-only form blocks.
    raw_rows = (
        session.execute(
            select(orm.RawTomogramORM)
            .where(
                orm.RawTomogramORM.sample_id == sample_id,
                orm.RawTomogramORM.acquisition_id == record_id,
            )
            .order_by(
                orm.RawTomogramORM.reconstruction_alignment_id,
                orm.RawTomogramORM.tomogram_id,
            )
        )
        .scalars()
        .all()
    )
    raw_authored = _authored_fields("acquisition", "raw_tomogram")
    # Raw and post-processed tomograms are one id namespace to the validator.
    tomo_seen: set = set()
    raw_tomogram = _dedupe_by_leaf_id(
        [_row_fields(r, raw_authored) for r in raw_rows],
        "tomogram_id",
        "raw_tomogram",
        tomo_seen,
    )
    if raw_tomogram:
        fields["raw_tomogram"] = raw_tomogram
    pp_rows = (
        session.execute(
            select(orm.PostProcessedTomogramORM)
            .where(
                orm.PostProcessedTomogramORM.sample_id == sample_id,
                orm.PostProcessedTomogramORM.acquisition_id == record_id,
            )
            .order_by(
                orm.PostProcessedTomogramORM.reconstruction_alignment_id,
                orm.PostProcessedTomogramORM.tomogram_id,
            )
        )
        .scalars()
        .all()
    )
    pp_authored = _authored_fields("acquisition", "post_processed_tomogram")
    post_processed = _dedupe_by_leaf_id(
        [_row_fields(pp, pp_authored) for pp in pp_rows],
        "tomogram_id",
        "post_processed_tomogram",
        tomo_seen,
    )
    if post_processed:
        fields["post_processed_tomogram"] = post_processed
    an_rows = (
        session.execute(
            select(orm.AnnotationORM)
            .where(
                orm.AnnotationORM.sample_id == sample_id,
                orm.AnnotationORM.acquisition_id == record_id,
            )
            .order_by(
                orm.AnnotationORM.reconstruction_alignment_id,
                orm.AnnotationORM.annotation_id,
            )
        )
        .scalars()
        .all()
    )
    an_authored = _authored_fields("acquisition", "annotation")
    annotations = _dedupe_by_leaf_id(
        [_row_fields(an, an_authored) for an in an_rows],
        "annotation_id",
        "annotation",
    )
    if annotations:
        fields["annotation"] = annotations
    return fields, acq.path


def _load_sample(record_id: str, session: Session) -> tuple[dict, str | None]:
    """Reconstruct a sample's authored fields, shaped per-section like a parsed
    sample.toml, for the deep-link editor (ADR-0004). data_source is returned so
    the form locks the arm from the record; the directory-derived sample_id
    pre-fills the placement hint."""
    sample = session.get(orm.SampleORM, record_id)
    if sample is None:
        raise HTTPException(404, f"no sample with id {record_id!r}")

    sample_authored = _authored_fields(
        "sample", "sample", exclude_id=True, exclude_derived=True
    )
    sample_fields = _row_fields(sample, sample_authored)
    sample_fields["sample_id"] = record_id
    sample_fields["data_source"] = _enum_val(sample.data_source)
    fields: dict = {"sample": sample_fields}

    for section, sub_orm in _SAMPLE_SECTION_ORM.items():
        row = session.get(sub_orm, record_id)
        if row is not None:
            section_authored = _authored_fields(
                "sample", section, exclude_id=True, exclude_derived=True
            )
            sub = _row_fields(row, section_authored)
            if sub:
                fields[section] = sub

    label_cols = _authored_fields("sample", "label", exclude_id=True, exclude_derived=True)
    labels = [
        _row_fields(r, label_cols)
        for r in session.execute(
            select(orm.LabelORM)
            .where(orm.LabelORM.sample_id == record_id)
            .order_by(orm.LabelORM.ordinal)
        )
        .scalars()
        .all()
    ]
    labels = [lbl for lbl in labels if lbl]
    if labels:
        fields["label"] = labels

    return fields, sample.path


def _read_disk_toml(
    request: Request, kind: str, path: str | None
) -> tuple[dict, str] | None:
    """Return ``(parsed_fields, raw_text)`` from the live ``{path}/{kind}.toml``,
    or ``None`` to fall back to the catalog reconstruction.

    Falls back (returns ``None``) when there is no path, the file is missing,
    resolves outside the data root, is unreadable, or holds invalid TOML — every
    such failure surfaces here as a caught ``HTTPException``/``OSError``/
    ``TOMLDecodeError``. The read is bounded by ``validate_under_data_root`` so a
    DB-recorded path can't be used to escape the configured data root.
    """
    if not path:
        return None
    try:
        resolved = validate_under_data_root(request, Path(path) / f"{kind}.toml")
        # Decode raw bytes as UTF-8 (no universal-newline translation) so the
        # baseline matches Fileglancer's Response.text() byte-for-byte on save;
        # read_text() would rewrite CRLF->LF and use the locale encoding, which
        # would false-positive the save-time byte-compare as "changed".
        text = resolved.read_bytes().decode("utf-8")
        return tomllib.loads(text), text
    except (HTTPException, OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None


def _load_reconstruction(
    group_id: str,
    sample_id: str | None,
    acquisition_id: str | None,
    session: Session,
) -> tuple[dict, str | None]:
    """Reconstruct one alignment group's authored fields, shaped like a parsed
    reconstruction.toml.

    Identity is (sample_id, acquisition_id, reconstruction_alignment_id): the
    group folder name is unique only within its acquisition, so all three are
    required. Tomograms and annotations are filtered by group — their ids are
    file stems and may repeat across groups.

    The alignment group has no path column of its own, so the on-disk directory
    is derived from the parent acquisition (mirrors ``_load_md_run``):
    ``{acq.path}/Reconstructions/{group}``. Null if the acquisition path is
    unset — the loader then falls back to the catalog source.
    """
    if not sample_id or not acquisition_id:
        raise HTTPException(
            422,
            "sample_id and acquisition_id query params required for reconstruction",
        )
    ra = session.get(
        orm.ReconstructionAlignmentORM, (sample_id, acquisition_id, group_id)
    )
    if ra is None:
        raise HTTPException(
            404,
            f"no reconstruction group {group_id!r} in "
            f"{sample_id!r}/{acquisition_id!r}",
        )
    acq = session.get(orm.AcquisitionORM, (sample_id, acquisition_id))
    path = f"{acq.path}/Reconstructions/{group_id}" if acq and acq.path else None
    fields: dict = {
        "reconstruction_alignment": _row_fields(
            ra, _authored_fields("reconstruction", "reconstruction_alignment")
        )
    }
    for section, orm_cls, leaf in (
        ("raw_tomogram", orm.RawTomogramORM, orm.RawTomogramORM.tomogram_id),
        (
            "post_processed_tomogram",
            orm.PostProcessedTomogramORM,
            orm.PostProcessedTomogramORM.tomogram_id,
        ),
        ("annotation", orm.AnnotationORM, orm.AnnotationORM.annotation_id),
    ):
        authored = _authored_fields("reconstruction", section)
        rows = session.execute(
            select(orm_cls)
            .where(orm_cls.sample_id == sample_id)
            .where(orm_cls.acquisition_id == acquisition_id)
            .where(orm_cls.reconstruction_alignment_id == group_id)
            .order_by(leaf)
        ).scalars()
        entries = [_row_fields(r, authored) for r in rows]
        if entries:
            fields[section] = entries
    return fields, path


@router.get("/{kind}/load/{record_id}")
def load_toml(
    kind: str,
    record_id: str,
    request: Request,
    sample_id: str | None = None,
    acquisition_id: str | None = None,
    session: Session = Depends(get_session),
):
    """Seed mode: pull-from-API (ADR-0004). Load an existing record's authored
    fields for editing.

    The DB reconstruction locates the record's on-disk directory (``path``, null
    if unknown). When the live ``{path}/{kind}.toml`` is readable under the data
    root, the form seeds from the *file* (fresh content) and its raw text is
    returned as ``baseline`` with ``source='disk'`` — the baseline lets a later
    "save to file share" refuse to clobber a file that changed since load
    (optimistic concurrency). When the file can't be read, load falls back to the
    catalog reconstruction (``source='catalog'``, ``baseline=None``) — this data
    may lag the on-disk file, so the renderer surfaces a staleness warning.
    ``path`` is always the directory to write back to.
    """
    if kind == "md_run":
        db_fields, path = _load_md_run(record_id, session)
    elif kind == "acquisition":
        db_fields, path = _load_acquisition(record_id, sample_id, session)
    elif kind == "sample":
        db_fields, path = _load_sample(record_id, session)
    elif kind == "reconstruction":
        db_fields, path = _load_reconstruction(
            record_id, sample_id, acquisition_id, session
        )
    else:
        raise HTTPException(404, f"load not supported for toml kind {kind!r}")

    disk = _read_disk_toml(request, kind, path)
    if disk is not None:
        fields, baseline = disk
        return {"fields": fields, "path": path, "source": "disk", "baseline": baseline}
    return {"fields": db_fields, "path": path, "source": "catalog", "baseline": None}
