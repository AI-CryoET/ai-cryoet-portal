"""POST /toml/{kind} — backend-authoritative TOML generation (ADR-0001).

Validates posted JSON against the matching Pydantic model and is
status-discriminated: valid -> 200 with the clean value-only ``.toml`` body and
a ``Content-Disposition`` attachment header; invalid -> 422 with field-level
errors from ``ValidationError.errors()``. Output omits comments, the
``#:schema`` pragma, empty fields, and the directory-derived identity key.
"""

from __future__ import annotations

import tomli_w
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from schema.schema import MdRun

router = APIRouter()

# kind -> Pydantic model (extended by later issues with sample / acquisition).
_MODELS: dict[str, type[BaseModel]] = {
    "md_run": MdRun,
}

# kind -> output key to drop: the identity field is the directory name, not
# file content (the loader injects it from the folder), so it's collected for
# validation + the placement hint but never written. Keyed by serialized
# (by_alias) name.
_ID_KEYS: dict[str, str] = {
    "md_run": "id",
}


def _field_errors(exc: ValidationError, model: type[BaseModel]) -> list[dict]:
    # Pydantic reports a missing field's loc by its alias ("id") but a bad
    # value's loc by the field name ("md_run_id"). Normalize to the field name
    # so the frontend maps every error to the same form field. Also trim to
    # JSON-safe keys (errors() can carry non-serializable ctx objects).
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
    data.pop(_ID_KEYS[kind], None)

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
