# ADR-0002: Authored-field registry, single-sourced in Python, codegen'd to TS

## Status
Accepted

## Context
The forms cover ~75 authored fields across three files, with enums,
repeatable sections, and cross-references. `schema.py` fields are all
`Optional` and mix authored with derived fields, so the authored subset isn't
directly readable from the models — the authored/derived distinction lives
only in code comments today. `filterFields.ts` is filter-oriented (existence
booleans, MDOC fields) and is **not** a reusable source for the authored set.

Two options considered: (B1) inline `json_schema_extra` annotations on the
Pydantic fields; (B2) a separate registry file. B1 leaks UI metadata into the
ORM models and the published `*.schema.json` (which researchers reference via
`#:schema`), and makes TS codegen awkward. The codebase already uses the
registry-plus-drift-test pattern for filters
(`catalog/api/filter_fields.py` + `tests/catalog/test_filter_fields_drift.py`).

## Decision
A sidecar registry, single-sourced in Python, codegen'd to TypeScript.

- `src/schema/form_fields.py` — `FORM_FIELDS`: per entry `{form, section,
  field, label, help, repeatable}`, plus authored/derived classification.
- **Codegen** `frontend/src/utils/formFields.ts` from the Python registry (a
  script emits the TS file), mirroring how `generate_json_schema.py` produces
  `*.schema.json`.
- Two drift tests:
  1. **Completeness** — every `schema.py` authored field is classified in the
     registry (fails on an unclassified new field).
  2. **Committed-TS-matches-regen** — the checked-in `formFields.ts` equals a
     fresh codegen.
- One generic MUI renderer consumes `formFields.ts` and builds all three forms.
  Section structure and repeatability come from Pydantic model composition;
  types/enums/optionality from introspection.

## Consequences
- "Forms follow the current format" is enforced by tests, not hope.
- `schema.py` stays a pure domain/validation model; UI metadata lives in the
  presentation layer.
- No runtime spec endpoint — the frontend renders from the committed TS mirror.
- Adding a field = annotate one registry entry; codegen + tests catch the rest.
