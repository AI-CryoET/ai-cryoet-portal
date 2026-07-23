---
name: add-sample-field
description: Add a new field to an existing entity in sample.toml (or acquisition.toml / md_run.toml) and wire it end-to-end through schema, DB, API, filters, forms, docs, and the frontend. Use when asked to "add a field", "add <x> to the schema", or extend an existing TOML entity (chromatin, label, fiducial, freezing, milling, sample, simulation, acquisition, md_run, tomogram, annotation, tilt_series).
---

# Add a field to an existing entity

`src/schema/schema.py` is the source of truth. A dozen artifacts mirror it,
guarded by drift tests — so the job is mechanical: edit the hand-authored
sources, regenerate the rest, run the tests. The drift tests tell you exactly
what you forgot, so **run them** rather than trusting this list is complete.

Pick the target Pydantic model (e.g. `Chromatin`) and its ORM twin
(`ChromatinORM`). Add the field in the **same position** in every file, and
match the field order used in the canonical `templates/*.toml`.

## 1. Hand-edit the sources

| File | Change | Guarded by |
|---|---|---|
| `src/schema/schema.py` | field on the Pydantic model, e.g. `salt_mM: str \| None = None` | — (source of truth) |
| `src/catalog/orm.py` | matching column on the `*ORM` class, e.g. `mapped_column(String, nullable=True)` | `tests/catalog/test_orm_drift.py` |
| `src/catalog/api/schemas.py` | field on the `*Out` response model | (surfaces in API JSON) |
| `src/schema/form_fields.py` | a `FormField(...)` entry (authored fields render; classify derived ones with `_derived(...)` / `authored=False`) | `tests/test_form_fields_drift.py` (completeness) |
| `src/schema/schema_catalog.py` | a `CatalogField(...)` in the entity's `fields=[...]` | `tests/test_schema_catalog_drift.py` |
| `src/catalog/api/filter_fields.py` | *(optional)* a `Field(...)` in the matching `Group` — only if the field should be **filterable** on the landing page | `tests/catalog/test_filter_fields_drift.py` |

Persistence (`src/catalog/persistence.py`) is generic (`_filter_to_columns`) —
**no edit needed**.

## 2. Add an Alembic migration

The ORM column change needs a revision or `test_autogenerate_empty_at_head`
fails. Autogenerate (preferred — it fills in the `add_column` and a real hash)
diffs the ORM against a live DB **at the previous head**, so point it at a
throwaway DB you first upgrade to head:

```bash
PY=.pixi/envs/catalog/bin/python   # `python -m alembic` works everywhere; the
                                   # `alembic` console script has an absolute-path
                                   # shebang that breaks if the env is at a
                                   # different prefix (e.g. in a devcontainer)
INI=src/catalog/migrations/alembic.ini
SCRATCH="$PWD/scratch_autogen.db"; rm -f "$SCRATCH"
# env.py reads CATALOG_DB_URL; upgrade the scratch DB to the current head first
CATALOG_DB_URL="sqlite:///$SCRATCH" "$PY" -m alembic -c "$INI" upgrade head
CATALOG_DB_URL="sqlite:///$SCRATCH" "$PY" -m alembic -c "$INI" \
  revision --autogenerate -m "add <field> to <table>"
rm -f "$SCRATCH"   # never commit the scratch DB
```

(The `pixi run migrate-revision "..."` task does the same `alembic revision
--autogenerate`, but it's defined in two envs — needs `--environment catalog` —
and the quoted message survives `-m` only when passed as one arg, so the direct
form above is more reliable.)

Then **read the generated file** and sanity-check it: `down_revision` should be
the current head, and the op should be an `op.batch_alter_table(...)` +
`add_column` (SQLite requires batch mode). Hand-writing one by copying an
existing `add_*` revision works too if autogenerate is unavailable.

## 3. Mirror in the frontend (hand-written, no codegen)

| File | Change | When |
|---|---|---|
| `frontend/src/types.ts` | field on the `*Out` type | always |
| `frontend/src/utils/filterFields.ts` | mirror the `filter_fields.py` entry (key/kind/table/column parity) | only if you added a filter in step 1 |
| `frontend/src/components/common/metadataSections.ts` | a `{ label, value }` row in the entity's section | if it should show on the detail page |

`frontend/src/utils/formFields.ts` and `.../schema/schemaData.ts` are
**generated** — do not hand-edit.

## 4. Template (optional)

If the field should appear as a fill-in for authors, add a commented line to the
canonical `templates/<file>.toml` in the right block (all optional block fields
are commented). `sync-templates` fans it out to the starter copies.

## 5. Regenerate and verify

```bash
pixi run sync   # schema.json, formFields.ts, starter templates, zips, schema.md, schemaData.ts
```

Then run the safety net (catalog env has sqlalchemy + alembic):

```bash
.pixi/envs/catalog/bin/python -m pytest \
  tests/catalog/test_orm_drift.py tests/test_schema_catalog_drift.py \
  tests/test_form_fields_drift.py tests/catalog/test_filter_fields_drift.py \
  tests/catalog/test_alembic.py tests/test_generate_json_schema.py \
  tests/test_repo_consistency.py tests/test_template_zips.py -q

cd frontend && node_modules/.bin/tsc --noEmit && node_modules/.bin/vitest run
```

Green = wired through. A failure names the file you missed.
