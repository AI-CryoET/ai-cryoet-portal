"""GET /samples and /samples/{sample_id}."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, exists, func, literal, null, or_, select, union_all
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.filter_fields import FIELDS, Field
from catalog.api.schemas import (
    AcquisitionOut,
    AcquisitionScanStatus,
    AnnotationOut,
    ChromatinOut,
    EntityScanStatus,
    FiducialOut,
    FreezingOut,
    LabelOut,
    MdRunOut,
    MdSourceOut,
    MillingOut,
    PostProcessedTomogramOut,
    RawTomogramOut,
    ReconstructionAlignmentOut,
    SampleDetail,
    SampleMatch,
    SampleSummary,
    SimulationOut,
    TiltSeriesOut,
)

router = APIRouter()


def _enum_val(v):
    """Coerce a possibly-enum value to its string value."""
    return v.value if hasattr(v, "value") else v


def _match_locator(q: str):
    """UNION ALL of (sample_id, acquisition_id, kind, matched_id) rows where an
    ID at any level of the hierarchy matches `q` (case-insensitive substring).
    IDs-only — description and other free-text fields are intentionally not
    searched."""
    # Escape LIKE metacharacters in the literal search term: real ids commonly
    # contain '_' (a LIKE single-char wildcard), and an unescaped '%' would
    # match everything. Backslash must be escaped first so it doesn't clobber
    # the escapes added for % and _.
    escaped = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    arms = [
        select(
            m.sample_id.label("sample_id"),
            (a if a is not None else null()).label("acquisition_id"),
            literal(k).label("kind"),
            i.label("matched_id"),
        ).where(func.lower(i).like(like, escape="\\"))
        for (m, i, k, a) in (
            (orm.SampleORM, orm.SampleORM.sample_id, "sample", None),
            (
                orm.AcquisitionORM,
                orm.AcquisitionORM.acquisition_id,
                "acquisition",
                orm.AcquisitionORM.acquisition_id,
            ),
            (
                orm.RawTomogramORM,
                orm.RawTomogramORM.tomogram_id,
                "tomogram",
                orm.RawTomogramORM.acquisition_id,
            ),
            (
                orm.PostProcessedTomogramORM,
                orm.PostProcessedTomogramORM.tomogram_id,
                "tomogram",
                orm.PostProcessedTomogramORM.acquisition_id,
            ),
            (
                orm.AnnotationORM,
                orm.AnnotationORM.annotation_id,
                "annotation",
                orm.AnnotationORM.acquisition_id,
            ),
        )
    ]
    return union_all(*arms)


# Pydantic sub-entity schemas paired with their ORM sources. Each sub-entity
# table has ``sample_id`` as its PK so we can fetch via ``session.get``.
_SUB_ENTITY_MAP: tuple[tuple[str, type, type], ...] = (
    ("chromatin", orm.ChromatinORM, ChromatinOut),
    ("fiducial", orm.FiducialORM, FiducialOut),
    ("simulation", orm.SimulationORM, SimulationOut),
    ("freezing", orm.FreezingORM, FreezingOut),
    ("milling", orm.MillingORM, MillingOut),
)


def _build_sub_entity(row, out_cls: type):
    """Construct an XxxOut Pydantic model from an ORM row, picking only the
    columns the Pydantic model declares (so DB-only columns like ``sample_id``
    don't leak in).
    """
    if row is None:
        return None
    field_names = out_cls.model_fields.keys()
    values = {name: getattr(row, name, None) for name in field_names}
    return out_cls(**values)


# ── Registry-driven filter machinery ──────────────────────────────────────
# The filter set is generated from catalog.api.filter_fields.FIELDS instead of
# hand-coded Query(...) params. Conditions are grouped by their ORM table and
# turned into one EXISTS per sub-entity table (or direct WHERE on samples), so
# all conditions on the same sub-entity must hold on the *same* row (per-row
# semantics — resolved decision 9 / the acquisition rule). Repeatable
# categorical values OR within a facet (col.in_), facets AND across (separate
# conditions).
# ponytail: one loop over the registry beats ~60 hand-coded branches; the
# registry is the contract, pinned by test_filter_fields_drift.py.

# Registry `table` string → ORM class.
_TABLE_ORM = {
    "samples": orm.SampleORM,
    "chromatin": orm.ChromatinORM,
    "fiducial": orm.FiducialORM,
    "simulation": orm.SimulationORM,
    "freezing": orm.FreezingORM,
    "milling": orm.MillingORM,
    "labels": orm.LabelORM,
    "acquisitions": orm.AcquisitionORM,
    "annotations": orm.AnnotationORM,
}


def _existence_cond(predicate_id: str):
    """Build a correlated EXISTS for an acquisition-entity existence field.

    Correlated to BOTH sample_id and acquisition_id of the AcquisitionORM in
    scope, so "has X" means the acquisition currently being matched owns a
    matching child row.
    """
    A = orm.AcquisitionORM

    def _exists(child, *extra):
        return exists(
            select(1)
            .where(child.sample_id == A.sample_id)
            .where(child.acquisition_id == A.acquisition_id)
            .where(*extra)
            .correlate(A)
        )

    TS, RAW, POST = (
        orm.TiltSeriesORM,
        orm.RawTomogramORM,
        orm.PostProcessedTomogramORM,
    )
    if predicate_id == "has_unaligned_tilt_series":
        # IS NOT TRUE → False or NULL.
        return _exists(TS, or_(TS.is_aligned.is_(False), TS.is_aligned.is_(None)))
    if predicate_id == "has_aligned_tilt_series":
        return _exists(TS, TS.is_aligned.is_(True))
    if predicate_id == "has_tilt_series_zarr":
        return _exists(TS, TS.zarr_path.isnot(None))
    if predicate_id == "has_raw_tomogram":
        return _exists(RAW)
    if predicate_id == "has_post_processed_tomogram":
        return _exists(POST)
    if predicate_id == "has_tomogram_zarr":
        return or_(
            _exists(RAW, RAW.zarr_path.isnot(None)),
            _exists(POST, POST.zarr_path.isnot(None)),
        )
    raise ValueError(f"unknown existence predicate: {predicate_id}")


def _field_values(field: Field, params):
    """Pull a field's value(s) out of the raw query params, typed by kind.

    Returns None when the field is absent (so it contributes no condition).
      text      -> list[str] (repeatable, OR within facet)
      range     -> (lo, hi) floats from {key}_min / {key}_max (either may be None)
      boolean   -> True | False (true/false; absent / other -> None)
      existence -> True when the checkbox param is truthy, else None
    """
    if field.kind == "text":
        vals = params.getlist(field.key)
        return vals or None
    if field.kind == "range":
        def _num(name):
            raw = params.get(name)
            return None if raw in (None, "") else float(raw)

        lo, hi = _num(f"{field.key}_min"), _num(f"{field.key}_max")
        return (lo, hi) if (lo is not None or hi is not None) else None
    if field.kind == "boolean":
        raw = params.get(field.key)
        if raw is None or raw == "":
            return None
        return raw.lower() in ("true", "1", "yes")
    if field.kind == "existence":
        raw = params.get(field.key)
        return bool(raw and raw.lower() in ("true", "1", "yes")) or None
    return None


def _field_condition(field: Field, value):
    """Map one field+value to a SQLAlchemy condition on its own table's column.

    Existence fields correlate to the acquisition rather than a plain column,
    so they are routed through ``_existence_cond``.
    """
    if field.kind == "existence":
        return _existence_cond(field.column)
    col = getattr(_TABLE_ORM[field.table], field.column)
    if field.kind == "text":
        return col.in_(value)
    if field.kind == "range":
        lo, hi = value
        conds = []
        if lo is not None:
            conds.append(or_(col.is_(None), col >= lo))
        if hi is not None:
            conds.append(or_(col.is_(None), col <= hi))
        return and_(*conds)
    if field.kind == "boolean":
        return col.is_(True) if value else col.is_(False)
    raise ValueError(f"unhandled kind: {field.kind}")


def _filter_conditions(params) -> dict[str, list]:
    """Group active filter conditions by ORM table (sample-direct → 'samples')."""
    by_table: dict[str, list] = {}
    for field in FIELDS:
        value = _field_values(field, params)
        if value is None:
            continue
        # Existence fields live on tilt_series/tomogram tables but are
        # correlated to the acquisition inside _existence_cond, so they belong
        # in the acquisition EXISTS bucket (all acquisition filters on the same
        # acquisition), not a standalone EXISTS on the child table.
        bucket = "acquisitions" if field.kind == "existence" else field.table
        by_table.setdefault(bucket, []).append(_field_condition(field, value))
    return by_table


@router.get("", response_model=list[SampleSummary])
def list_samples(
    request: Request,
    q: str | None = Query(None),
    sort: Literal["sample_id", "project", "type"] = Query("sample_id"),
    order: Literal["asc", "desc"] = Query("asc"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """Paginated list of live samples (deleted_at IS NULL) with filters and
    intrinsic child-row counts (n_acquisitions/n_tomograms/n_tilt_series).

    Filters are registry-driven (``catalog.api.filter_fields.FIELDS``); the
    full param set is read off ``request.query_params`` rather than declared
    one-by-one. Param naming: text/existence/boolean use the field ``key``;
    range fields use ``{key}_min`` / ``{key}_max``. See the OpenAPI-friendly
    note: the registry is the documented contract.

    Filter semantics:
      * Repeatable categorical params act as OR within a facet, AND across.
      * Sub-entity (1:1, label, acquisition, annotation) filters use EXISTS
        subqueries; all conditions on one sub-entity must hold on the same row.
      * Range filters are NULL-tolerant: a row with NULL on the bound column is
        treated as a match (so partial metadata doesn't drop the whole sample).
      * Counts on the SELECT list are filter-INDEPENDENT total child rows.
    """
    # ── Subqueries ────────────────────────────────────────────────────────
    # Outstanding-issue count per sample (current state; resolved_at IS NULL).
    warn_count_sq = (
        select(
            orm.IssueORM.sample_id,
            func.count(orm.IssueORM.id).label("wc"),
        )
        .where(orm.IssueORM.resolved_at.is_(None))
        .where(orm.IssueORM.sample_id.is_not(None))
        .group_by(orm.IssueORM.sample_id)
        .subquery()
    )

    # Filter-independent total child counts (correlated subqueries).
    n_acq_sq = (
        select(func.count())
        .select_from(orm.AcquisitionORM)
        .where(orm.AcquisitionORM.sample_id == orm.SampleORM.sample_id)
        .correlate(orm.SampleORM)
        .scalar_subquery()
    )
    n_raw_tomo_sq = (
        select(func.count())
        .select_from(orm.RawTomogramORM)
        .where(orm.RawTomogramORM.sample_id == orm.SampleORM.sample_id)
        .correlate(orm.SampleORM)
        .scalar_subquery()
    )
    n_post_tomo_sq = (
        select(func.count())
        .select_from(orm.PostProcessedTomogramORM)
        .where(orm.PostProcessedTomogramORM.sample_id == orm.SampleORM.sample_id)
        .correlate(orm.SampleORM)
        .scalar_subquery()
    )
    n_ts_sq = (
        select(func.count())
        .select_from(orm.TiltSeriesORM)
        .where(orm.TiltSeriesORM.sample_id == orm.SampleORM.sample_id)
        .correlate(orm.SampleORM)
        .scalar_subquery()
    )
    # Representative MD-run preview relpath for the list hero. min() ignores
    # NULLs, so this is the lexicographically-first *rendered* preview (or NULL
    # when no run has one) — a stable per-sample choice.
    md_preview_sq = (
        select(func.min(orm.MdRunORM.preview_path))
        .where(orm.MdRunORM.sample_id == orm.SampleORM.sample_id)
        .correlate(orm.SampleORM)
        .scalar_subquery()
    )

    stmt = (
        select(
            orm.SampleORM,
            func.coalesce(warn_count_sq.c.wc, 0).label("warning_count"),
            n_acq_sq.label("n_acquisitions"),
            (n_raw_tomo_sq + n_post_tomo_sq).label("n_tomograms"),
            n_ts_sq.label("n_tilt_series"),
            md_preview_sq.label("md_preview_path"),
        )
        .outerjoin(warn_count_sq, warn_count_sq.c.sample_id == orm.SampleORM.sample_id)
        .where(orm.SampleORM.deleted_at.is_(None))
    )

    # ── Registry-driven filters (grouped by ORM table) ───────────────────
    by_table = _filter_conditions(request.query_params)

    # sample-direct columns: WHERE col IN (...) straight on the row.
    for cond in by_table.pop("samples", []):
        stmt = stmt.where(cond)

    # acquisition: one EXISTS on AcquisitionORM correlated to the sample,
    # AND-ing every scalar/range/boolean condition AND each nested-existence
    # (tilt_series / tomogram / annotation) condition, so all acquisition
    # filters hold on the *same* acquisition. The annotation_type text filter
    # lives on AnnotationORM (table='annotations') and is folded in here as a
    # correlated EXISTS on the same acquisition.
    acq_conds = by_table.pop("acquisitions", [])
    ann_conds = by_table.pop("annotations", [])
    if ann_conds:
        acq_conds.append(
            exists(
                select(1)
                .where(orm.AnnotationORM.sample_id == orm.AcquisitionORM.sample_id)
                .where(
                    orm.AnnotationORM.acquisition_id
                    == orm.AcquisitionORM.acquisition_id
                )
                .where(and_(*ann_conds))
                .correlate(orm.AcquisitionORM)
            )
        )
    if acq_conds:
        stmt = stmt.where(
            exists(
                select(1)
                .where(orm.AcquisitionORM.sample_id == orm.SampleORM.sample_id)
                .where(and_(*acq_conds))
                .correlate(orm.SampleORM)
            )
        )

    # 1:1 sub-entities + label (1:N): one EXISTS per table, all that table's
    # conditions AND-ed inside the SAME EXISTS (per-row — resolved decision 9).
    for table, conds in by_table.items():
        sub = _TABLE_ORM[table]
        stmt = stmt.where(
            exists(
                select(1)
                .where(sub.sample_id == orm.SampleORM.sample_id)
                .where(and_(*conds))
                .correlate(orm.SampleORM)
            )
        )

    # IDs-only free-text search across the hierarchy: keep only samples that
    # have a matching id at some level. See _match_locator.
    # (call site 1 of 2 — this pass filters the WHOLE result set; the second
    # call below re-derives match locations only for the page actually
    # returned, so it's not one query because the two run over different
    # scopes: all-matching-samples vs. matches-within-this-page.)
    if q:
        locator = _match_locator(q).subquery()
        stmt = stmt.where(
            orm.SampleORM.sample_id.in_(select(locator.c.sample_id).distinct())
        )

    # ── Sort + pagination ─────────────────────────────────────────────────
    sort_col = {
        "sample_id": orm.SampleORM.sample_id,
        "project": orm.SampleORM.project,
        "type": orm.SampleORM.type,
    }[sort]
    stmt = stmt.order_by(sort_col.desc() if order == "desc" else sort_col.asc())
    # Stable tiebreaker so paged queries are deterministic when sorting on a
    # non-unique column.
    if sort != "sample_id":
        stmt = stmt.order_by(orm.SampleORM.sample_id.asc())
    stmt = stmt.limit(limit).offset(offset)

    rows = session.execute(stmt).all()

    # Per-page match locations for auto-expand (only when searching).
    # (call site 2 of 2 — re-invokes _match_locator rather than reusing the
    # filter pass above because that pass only proves membership; it doesn't
    # return per-row kind/acquisition_id, and we only need those details for
    # the samples on this page, so it's cheaper to re-scope than to carry the
    # full unfiltered locator result through pagination.)
    matches_by_sample: dict[str, list[SampleMatch]] = {}
    if q and rows:
        page_ids = [r[0].sample_id for r in rows]
        loc = _match_locator(q).subquery()
        for sid, aid, kind, mid in session.execute(
            select(
                loc.c.sample_id, loc.c.acquisition_id, loc.c.kind, loc.c.matched_id
            ).where(loc.c.sample_id.in_(page_ids))
        ).all():
            matches_by_sample.setdefault(sid, []).append(
                SampleMatch(acquisition_id=aid, kind=kind, matched_id=mid)
            )

    return [
        SampleSummary(
            sample_id=r[0].sample_id,
            project=_enum_val(r[0].project),
            lab_name=_enum_val(r[0].lab_name),
            data_source=_enum_val(r[0].data_source),
            type=r[0].type,
            cell_type=r[0].cell_type,
            description=r[0].description,
            path=r[0].path,
            warning_count=r[1],
            n_acquisitions=r[2],
            n_tomograms=r[3],
            n_tilt_series=r[4],
            thumbnail_path=r[0].thumbnail_path,
            md_preview_path=r[5],
            matches=matches_by_sample.get(r[0].sample_id, []),
        )
        for r in rows
    ]


def _row_to_out(row, out_cls: type):
    """Map a row to an XxxOut by copying only declared fields present on row."""
    field_names = out_cls.model_fields.keys()
    return out_cls(
        **{name: getattr(row, name) for name in field_names if hasattr(row, name)}
    )


def _file_formats(*paths: str | None) -> list[str]:
    """Extension of each path, uppercased and de-duplicated in order."""
    seen: list[str] = []
    for p in paths:
        if not p:
            continue
        ext = Path(p).suffix.lstrip(".").upper()
        if ext and ext not in seen:
            seen.append(ext)
    return seen


# AcquisitionOut fields that are nested child entities rather than scalar
# columns on AcquisitionORM — populated separately below, so excluded when
# bulk-copying the acquisition's own columns.
_ACQ_CHILD_FIELDS = frozenset(
    {
        "md_source",
        "raw_tomograms",
        "post_processed_tomograms",
        "annotations",
        "tilt_series",
        "reconstruction_alignment",
        # Populated separately from acquisition_scan_status (LEFT JOIN), so it
        # must not be bulk-copied off the AcquisitionORM row.
        "scan_status",
    }
)


@router.get("/{sample_id}", response_model=SampleDetail)
def get_sample(sample_id: str, session: Session = Depends(get_session)):
    """Full sample record with typed sub-entities, acquisitions, tomograms,
    annotations, and tilt_series. 404 for missing or soft-deleted.
    """
    sample = session.get(orm.SampleORM, sample_id)
    if sample is None or sample.deleted_at is not None:
        raise HTTPException(status_code=404, detail="sample not found")

    # 1:1 sub-entities.
    sub: dict[str, object | None] = {}
    for attr_name, sub_orm, out_cls in _SUB_ENTITY_MAP:
        row = session.get(sub_orm, sample_id)
        sub[attr_name] = _build_sub_entity(row, out_cls)

    # Labels (ordinal-keyed list).
    label_rows = (
        session.execute(
            select(orm.LabelORM)
            .where(orm.LabelORM.sample_id == sample_id)
            .order_by(orm.LabelORM.ordinal)
        )
        .scalars()
        .all()
    )
    labels = [_row_to_out(r, LabelOut) for r in label_rows]

    # MD runs (id-keyed list).
    md_run_rows = (
        session.execute(
            select(orm.MdRunORM)
            .where(orm.MdRunORM.sample_id == sample_id)
            .order_by(orm.MdRunORM.md_run_id)
        )
        .scalars()
        .all()
    )
    md_runs = [_row_to_out(r, MdRunOut) for r in md_run_rows]

    # Acquisitions + per-acq children.
    acqs = (
        session.execute(
            select(orm.AcquisitionORM)
            .where(orm.AcquisitionORM.sample_id == sample_id)
            .order_by(orm.AcquisitionORM.acquisition_id)
        )
        .scalars()
        .all()
    )
    acq_out: list[AcquisitionOut] = []
    for a in acqs:
        raw_rows = (
            session.execute(
                select(orm.RawTomogramORM)
                .where(orm.RawTomogramORM.sample_id == sample_id)
                .where(orm.RawTomogramORM.acquisition_id == a.acquisition_id)
                .order_by(
                    orm.RawTomogramORM.reconstruction_alignment_id,
                    orm.RawTomogramORM.tomogram_id,
                )
            )
            .scalars()
            .all()
        )

        post_rows = (
            session.execute(
                select(orm.PostProcessedTomogramORM)
                .where(orm.PostProcessedTomogramORM.sample_id == sample_id)
                .where(
                    orm.PostProcessedTomogramORM.acquisition_id == a.acquisition_id
                )
                .order_by(
                    orm.PostProcessedTomogramORM.reconstruction_alignment_id,
                    orm.PostProcessedTomogramORM.tomogram_id,
                )
            )
            .scalars()
            .all()
        )

        anns = (
            session.execute(
                select(orm.AnnotationORM)
                .where(orm.AnnotationORM.sample_id == sample_id)
                .where(orm.AnnotationORM.acquisition_id == a.acquisition_id)
                .order_by(
                    orm.AnnotationORM.reconstruction_alignment_id,
                    orm.AnnotationORM.annotation_id,
                )
            )
            .scalars()
            .all()
        )
        ts_rows = (
            session.execute(
                select(orm.TiltSeriesORM)
                .where(orm.TiltSeriesORM.sample_id == sample_id)
                .where(orm.TiltSeriesORM.acquisition_id == a.acquisition_id)
                .order_by(orm.TiltSeriesORM.tilt_series_id)
            )
            .scalars()
            .all()
        )
        ra_rows = (
            session.execute(
                select(orm.ReconstructionAlignmentORM)
                .where(orm.ReconstructionAlignmentORM.sample_id == sample_id)
                .where(
                    orm.ReconstructionAlignmentORM.acquisition_id == a.acquisition_id
                )
                .order_by(orm.ReconstructionAlignmentORM.reconstruction_alignment_id)
            )
            .scalars()
            .all()
        )
        md_source_row = session.get(
            orm.MdSourceORM, (sample_id, a.acquisition_id)
        )

        # Per-acquisition freshness + thumbnail provenance (side table; None
        # when the acquisition has not yet been (re)scanned under the new model).
        acq_status_row = session.get(
            orm.AcquisitionScanStatusORM, (sample_id, a.acquisition_id)
        )
        acq_status = (
            AcquisitionScanStatus(
                last_scanned_at=acq_status_row.last_scanned_at,
                last_changed_at=acq_status_row.last_changed_at,
                last_outcome=_enum_val(acq_status_row.last_outcome),
                last_scan_run_id=acq_status_row.last_scan_run_id,
                thumbnail_path=acq_status_row.thumbnail_path,
                thumbnail_source_kind=_enum_val(acq_status_row.thumbnail_source_kind),
                thumbnail_source_path=acq_status_row.thumbnail_source_path,
                thumbnail_generated_at=acq_status_row.thumbnail_generated_at,
                thumbnail_status=_enum_val(acq_status_row.thumbnail_status),
            )
            if acq_status_row is not None
            else None
        )

        # Copy every scalar column AcquisitionOut declares straight off the ORM
        # row (researcher-authored + MDOC/frame-derived), then attach the nested
        # child entities below. New scalar fields flow through automatically.
        acq_scalars = {
            name: getattr(a, name, None)
            for name in AcquisitionOut.model_fields
            if name not in _ACQ_CHILD_FIELDS
        }
        acq_out.append(
            AcquisitionOut(
                **acq_scalars,
                md_source=_build_sub_entity(md_source_row, MdSourceOut),
                raw_tomograms=[
                    _row_to_out(r, RawTomogramOut).model_copy(
                        update={"file_formats": _file_formats(r.mrc_path, r.zarr_path)}
                    )
                    for r in raw_rows
                ],
                post_processed_tomograms=[
                    _row_to_out(t, PostProcessedTomogramOut).model_copy(
                        update={"file_formats": _file_formats(t.mrc_path, t.zarr_path)}
                    )
                    for t in post_rows
                ],
                annotations=[
                    AnnotationOut(
                        annotation_id=ann.annotation_id,
                        reconstruction_alignment_id=ann.reconstruction_alignment_id,
                        type=ann.type,
                        derived_from=ann.derived_from,
                        bounding_box=ann.bounding_box,
                        files=ann.files or [],
                        file_formats=_file_formats(*(ann.files or [])),
                    )
                    for ann in anns
                ],
                tilt_series=[_row_to_out(ts, TiltSeriesOut) for ts in ts_rows],
                reconstruction_alignment=[
                    _row_to_out(ra, ReconstructionAlignmentOut) for ra in ra_rows
                ],
                scan_status=acq_status,
            )
        )

    # Per-sample freshness rollup (side table; None when not yet rescanned).
    sample_status_row = session.get(orm.SampleScanStatusORM, sample_id)
    sample_status = (
        EntityScanStatus(
            last_scanned_at=sample_status_row.last_scanned_at,
            last_changed_at=sample_status_row.last_changed_at,
            last_outcome=_enum_val(sample_status_row.last_outcome),
            last_scan_run_id=sample_status_row.last_scan_run_id,
        )
        if sample_status_row is not None
        else None
    )

    return SampleDetail(
        sample_id=sample.sample_id,
        project=_enum_val(sample.project),
        lab_name=_enum_val(sample.lab_name),
        data_source=_enum_val(sample.data_source),
        type=sample.type,
        cell_type=sample.cell_type,
        description=sample.description,
        path=sample.path,
        chromatin=sub["chromatin"],
        fiducial=sub["fiducial"],
        simulation=sub["simulation"],
        freezing=sub["freezing"],
        milling=sub["milling"],
        label=labels,
        md_run=md_runs,
        acquisitions=acq_out,
        thumbnail_path=sample.thumbnail_path,
        scan_status=sample_status,
    )
