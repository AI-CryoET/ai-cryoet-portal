# ADR-0001: Backend-authoritative TOML generation for the authoring forms

## Status
Accepted

## Context
The portal needs three forms that let researchers fill inputs and download
`sample.toml`, `acquisition.toml`, and `md_run.toml` matching the current
format. The format's source of truth is `src/schema/schema.py` (Pydantic) plus
`/templates`, both server-side. Generating TOML in the browser would re-encode
every enum, required field, and cross-reference rule in TypeScript, which
drifts from `schema.py` the moment a model changes.

## Decision
Generation **and** validation live on the backend.

- One parametrized endpoint: `POST /api/toml/{kind}` where
  `kind ∈ {sample, acquisition, md_run}`.
- The handler picks the matching Pydantic model, validates the posted JSON, and
  is **status-discriminated**:
  - **valid → 200** with the `.toml` body and
    `Content-Disposition: attachment; filename={kind}.toml`.
  - **invalid → 422** with a JSON array of field-level errors derived from
    Pydantic's `ValidationError.errors()` (mapped to inline form errors).
- Output is **clean value-only TOML**: no comments, no `#:schema` pragma,
  optional/empty fields omitted. Serialized with `tomli-w` (stdlib `tomllib`
  is read-only).
- The frontend does only thin structural checks (required-not-empty; the
  `IdStr` pattern shared as one regex). All schema rules (enums, cross-refs,
  consistency invariants) are enforced by the round-trip.

## Consequences
- Form output tracks `schema.py` automatically; no TS copy of the rules.
- Cross-reference errors surface on submit, not as-you-type. Acceptable for
  low-frequency authoring.
- Reuses the existing `FileResponse` pattern (`catalog/api/routes/thumbnails.py`).
- Adds `tomli-w` as a dependency.
