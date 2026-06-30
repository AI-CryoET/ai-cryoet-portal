"""POST /toml/{kind} — backend-authoritative TOML generation (ADR-0001).

Validates posted JSON against the matching Pydantic model and is
status-discriminated: valid -> 200 with the clean value-only ``.toml`` body and
a ``Content-Disposition`` attachment header; invalid -> 422 with field-level
errors from ``ValidationError.errors()``. Output omits comments, the
``#:schema`` pragma, empty fields, and the directory-derived identity key.
"""

from __future__ import annotations

import tomllib

import tomli_w
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.schemas import MdRunOut
from schema.form_fields import FORM_FIELDS
from schema.schema import AcquisitionFile, MdRun

router = APIRouter()

# kind -> Pydantic model.
_MODELS: dict[str, type[BaseModel]] = {
    "md_run": MdRun,
    "acquisition": AcquisitionFile,
}

# kind -> dotted path of the identity field to drop from output: the id is the
# directory name, not file content (the loader injects it from the folder), so
# it's collected for validation + the placement hint but never written. Keyed
# by serialized (by_alias) names along the path.
_ID_PATHS: dict[str, tuple[str, ...]] = {
    "md_run": ("id",),
    "acquisition": ("acquisition", "acquisition_id"),
}


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


def _pop_path(data: dict, path: tuple[str, ...]) -> None:
    """Drop the identity key at a (possibly nested) path; no-op if absent."""
    node = data
    for key in path[:-1]:
        node = node.get(key) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return
    node.pop(path[-1], None)


def _drop_empty(value):
    """Recursively drop empty collections so an unfilled repeatable / table
    (TOML ``foo = []``) doesn't litter the output. ``None`` is left in place:
    exclude_none already removed model nulls, and a nested null from an extra
    field must still reach tomli_w so it 422s rather than vanishing."""
    if isinstance(value, dict):
        cleaned = {k: _drop_empty(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v != [] and v != {}}
    if isinstance(value, list):
        return [_drop_empty(v) for v in value]
    return value


@router.post("/{kind}")
def author_toml(kind: str, payload: dict = Body(...)):
    model = _MODELS.get(kind)
    if model is None:
        raise HTTPException(404, f"unknown toml kind {kind!r}")
    try:
        obj = model.model_validate(payload)
    except ValidationError as exc:
        return JSONResponse(
            status_code=422, content={"errors": _field_errors(exc, model)}
        )

    # exclude_none drops unfilled optionals (TOML has no null); by_alias matches
    # the on-disk key names. mode="json" so dates etc. serialize to TOML-safe
    # scalars.
    data = obj.model_dump(by_alias=True, exclude_none=True, mode="json")
    _pop_path(data, _ID_PATHS[kind])
    data = _drop_empty(data)

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


def _authored(form: str, section: str) -> list[str]:
    return [
        ff.field
        for ff in FORM_FIELDS
        if ff.form == form and ff.section == section and ff.authored
    ]


@router.get("/{kind}/load/{record_id}")
def load_toml(
    kind: str,
    record_id: str,
    sample_id: str | None = None,
    session: Session = Depends(get_session),
):
    """Seed mode: pull-from-API (ADR-0004). Load an existing record's authored
    fields by id from the catalog DB. The data may lag the on-disk file — the
    renderer surfaces a staleness warning for this mode."""
    if kind == "md_run":
        row = (
            session.execute(
                select(orm.MdRunORM).where(orm.MdRunORM.md_run_id == record_id)
            )
            .scalars()
            .first()
        )
        if row is None:
            raise HTTPException(404, f"no {kind} with id {record_id!r}")
        fields = {
            name: getattr(row, name)
            for name in MdRunOut.model_fields
            if getattr(row, name, None) is not None
        }
        return {"fields": fields}

    if kind == "acquisition":
        # Composite identity: (sample_id, acquisition_id). The edit link / route
        # carries both (mirrors the acquisition detail route).
        if not sample_id:
            raise HTTPException(422, "sample_id query param required for acquisition")
        acq = session.get(orm.AcquisitionORM, (sample_id, record_id))
        if acq is None:
            raise HTTPException(404, f"no acquisition {record_id!r} in sample {sample_id!r}")
        fields = {"acquisition": _row_fields(acq, _authored("acquisition", "acquisition"))}
        md = session.get(orm.MdSourceORM, (sample_id, record_id))
        if md is not None:
            md_fields = _row_fields(md, _authored("acquisition", "md_source"))
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
        ts_authored = _authored("acquisition", "tilt_series")
        tilt_series = [_row_fields(ts, ts_authored) for ts in ts_rows]
        if tilt_series:
            fields["tilt_series"] = tilt_series
        return {"fields": fields}

    raise HTTPException(404, f"load not supported for toml kind {kind!r}")


def _row_fields(row, names: list[str]) -> dict:
    """Authored, non-None columns of an ORM row, keyed by field name."""
    return {
        name: getattr(row, name)
        for name in names
        if getattr(row, name, None) is not None
    }
