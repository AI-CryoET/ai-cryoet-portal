# Data Schema Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive "Data schema" tab to `/data-organization` that lets researchers explore every documented field by entity — filtered by data arm (experimental/simulation), project (chromatin/non-chromatin), and provenance (authored/derived) — sourced without drift from a single Python registry.

**Architecture:** Introduce `src/schema/schema_catalog.py` as the single curated source of truth for the *documented* data model (entities, nesting, per-field type/provenance/notes). Two generators render from it: `docs/schema.md` (regenerated, PK/FK annotations dropped) and `frontend/.../schema/schemaData.ts` (consumed by the page). A drift test asserts the catalog stays complete against the SQLAlchemy ORM (`src/catalog/orm.py`) and that both generated artifacts match a fresh render. The winning prototype layout (Variant C: tree + two-pane) is promoted to the real page; the prototype scaffolding is deleted.

**Tech Stack:** Python 3.14 + Pydantic + SQLAlchemy (backend registry/generators/tests); React 19 + MUI 6 + TanStack Router (frontend); pixi task runner; pytest; vitest.

## Global Constraints

- Run pytest with the pixi env Python, never bare `pytest` (pixi shebangs are broken here): `.pixi/envs/api/bin/python -m pytest <path>` — `pyproject.toml` sets `pythonpath = ["src"]`, so `from schema... import` / `from catalog... import` resolve from repo root.
- Codegen pattern mirrors ADR-0002 (`form_fields.py` → `generate_form_fields.py` → `formFields.ts`, guarded by `tests/test_form_fields_drift.py`). Follow it exactly: hand-authored Python source → generator emits an AUTO-GENERATED file → drift test compares committed file to a fresh `render()`.
- Regenerate all schema artifacts with `pixi run <task>`; the new tasks must be wired into the existing `sync` aggregate task in `pyproject.toml`.
- Frontend scripts are JavaScript-flavored TS under Vite: no runtime type-only tricks; `import.meta.env` for env gating. Typecheck with `npx tsc --noEmit` from `frontend/`.
- Drop `(PK)` / `(FK)` annotations from the regenerated `schema.md` (product decision). Keep the 5-column table shape: `Field | Type | Source | Source Type | Notes`.
- The 14 domain ORM classes are the only ones the catalog covers: `SampleORM, ChromatinORM, LabelORM, FiducialORM, SimulationORM, FreezingORM, MillingORM, MdRunORM, AcquisitionORM, MdSourceORM, RawTomogramORM, PostProcessedTomogramORM, AnnotationORM, TiltSeriesORM`. The other 10 ORM tables (scan runs, issues, scan state, extras, meta, scan-status) are operational and out of scope.
- Undocumented internal ORM columns (excluded from the catalog by design): `samples.{deleted_at, disk_size_bytes, thumbnail_path}`, `labels.ordinal`. Only documented-but-not-a-DB-column field: `renamed_from` (scan-time-only directive; catalog marks it `in_db=False`).

---

### Task 1: Schema catalog registry + ORM completeness drift test

**Files:**
- Create: `src/schema/schema_catalog.py`
- Create: `tests/test_schema_catalog_drift.py`

**Interfaces:**
- Produces: `CatalogField(name: str, type: str, source: str, notes: str = "", in_db: bool = True)` with property `kind -> 'authored' | 'derived'` (`'authored' if '.toml' in self.source else 'derived'`); `CatalogEntity(key: str, name: str, cardinality: str, parent: str | None, arm: str | None, chromatin_only: bool, orm: type, fields: list[CatalogField])`; module constants `CATALOG: list[CatalogEntity]`, `DOMAIN_ORM: list[type]`, `UNDOCUMENTED_ORM_COLUMNS: dict[str, set[str]]`.
- The catalog data is transcribed from `docs/schema.md` (current committed version). The drift test below is the safety net: it FAILS listing any ORM column the transcription missed, so completeness is enforced, not assumed.

- [ ] **Step 1: Write the dataclasses + registry skeleton**

Create `src/schema/schema_catalog.py`. Author the dataclasses and the entity list. Nesting via `parent`; gating via `arm` / `chromatin_only`; each entity references its ORM class for the drift test.

```python
"""Curated single source of truth for the DOCUMENTED data model.

Every field a researcher or reader should see, organized by entity and nesting.
Two generators render from this module: ``generate_schema_docs`` emits both
``docs/schema.md`` and the frontend ``schemaData.ts``. Completeness against the
SQLAlchemy ORM (the DB superset) is enforced by tests/test_schema_catalog_drift.py.

This mirrors the ADR-0002 pattern (form_fields.py): hand-authored Python source,
codegen'd artifacts, drift-tested. Types and notes are display strings carried
here (sourced from the prior docs/schema.md); the drift test guards that every
documented field is a real ORM column and every non-internal ORM column is
documented.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from catalog import orm


@dataclass(frozen=True)
class CatalogField:
    name: str
    type: str  # display string, e.g. 'text', 'float', 'list[float]', 'enum'
    source: str  # provenance label, e.g. 'sample.toml [sample]', 'MDOC', 'directory'
    notes: str = ""
    in_db: bool = True  # False = documented but not an ORM column (renamed_from)

    @property
    def kind(self) -> str:
        return "authored" if ".toml" in self.source else "derived"


@dataclass(frozen=True)
class CatalogEntity:
    key: str
    name: str
    cardinality: str
    parent: str | None
    orm: type
    arm: str | None = None  # 'experimental' | 'simulation' | None (both)
    chromatin_only: bool = False
    fields: list[CatalogField] = field(default_factory=list)


# Domain ORM classes the catalog documents (see Global Constraints).
DOMAIN_ORM: list[type] = [
    orm.SampleORM, orm.ChromatinORM, orm.LabelORM, orm.FiducialORM,
    orm.SimulationORM, orm.FreezingORM, orm.MillingORM, orm.MdRunORM,
    orm.AcquisitionORM, orm.MdSourceORM, orm.RawTomogramORM,
    orm.PostProcessedTomogramORM, orm.AnnotationORM, orm.TiltSeriesORM,
]

# Internal/operational columns intentionally left out of the documented model.
UNDOCUMENTED_ORM_COLUMNS: dict[str, set[str]] = {
    "samples": {"deleted_at", "disk_size_bytes", "thumbnail_path"},
    "labels": {"ordinal"},
}

CATALOG: list[CatalogEntity] = [
    CatalogEntity(
        key="sample", name="Sample", cardinality="one per sample",
        parent=None, orm=orm.SampleORM,
        fields=[
            CatalogField("sample_id", "text", "directory", "Sample folder name."),
            CatalogField("lab_name", "enum", "sample.toml [sample]",
                         "collepardo, gouaux, rosen, or villa."),
            CatalogField("data_source", "enum", "directory",
                         "experimental (Experimental/) or simulation (MdSimulation/); not authored."),
            CatalogField("project", "enum", "sample.toml [sample]",
                         "chromatin, synapse, or nanogold."),
            CatalogField("type", "text", "sample.toml [sample]", "e.g. cellular / reconstituted."),
            CatalogField("cell_type", "text", "sample.toml [sample]", "Required when type = cellular."),
            CatalogField("description", "text", "sample.toml [sample]", "Free text."),
            CatalogField("path", "text", "directory", "Absolute sample-directory path."),
            CatalogField("renamed_from", "text", "sample.toml [sample]",
                         "Scan-time-only rename directive; not stored in the DB.", in_db=False),
        ],
    ),
    CatalogEntity(
        key="chromatin", name="Chromatin", cardinality="one per sample",
        parent="sample", orm=orm.ChromatinORM, chromatin_only=True,
        fields=[
            # ... transcribe every row of docs/schema.md §1a here ...
        ],
    ),
    # ... remaining 12 entities (label, fiducial, simulation, freezing, milling,
    #     md_run, acquisition, md_source, raw_tomogram,
    #     post_processed_tomogram, annotation, tilt_series) ...
]
```

Transcribe ALL fields for ALL 14 entities from the current `docs/schema.md` tables. Mapping rules while transcribing:
- `type`: copy the schema.md Type column, stripping ` (PK)` / ` (FK)` suffixes (e.g. `text (PK)` → `text`).
- `source`: normalize the schema.md Source column to a compact label — authored → `<file>.toml [<section>]` (e.g. `sample.toml [chromatin]`, `acquisition.toml [[post_processed_tomogram]]`); derived → the bare source word(s) (`MDOC`, `MRC header`, `directory`, `OME-Zarr .zattrs`, `filesystem`, `.eer / .tiff`, `derived`).
- `notes`: copy the schema.md Notes column (trim to a sentence or two).
- `in_db=False` only for `renamed_from` rows.
- Entity `parent`: `sample` for chromatin/label/fiducial/simulation/freezing/milling/md_run; `acquisition` for md_source/raw_tomogram/post_processed_tomogram/annotation/tilt_series; `None` for sample and acquisition.
- Entity `arm`: `experimental` for label/fiducial/freezing/milling; `simulation` for simulation/md_run/md_source; `None` otherwise. `chromatin_only=True` only for chromatin.
- Entity `cardinality`: `0..N per sample` (label, md_run), `0..N per acquisition` (tilt_series, post_processed_tomogram, annotation), `one per acquisition (optional)` (raw_tomogram), `one per imaging position` (acquisition), else `one per sample` / `one per acquisition`.

- [ ] **Step 2: Write the failing completeness drift test**

Create `tests/test_schema_catalog_drift.py`:

```python
from __future__ import annotations

from schema.schema_catalog import CATALOG, DOMAIN_ORM, UNDOCUMENTED_ORM_COLUMNS


def _catalog_by_orm():
    by_orm: dict[type, set[str]] = {}
    for e in CATALOG:
        by_orm.setdefault(e.orm, set()).update(f.name for f in e.fields if f.in_db)
    return by_orm


def test_every_documented_field_is_an_orm_column():
    by_orm = _catalog_by_orm()
    for e in CATALOG:
        cols = {c.name for c in e.orm.__table__.columns}
        documented = {f.name for f in e.fields if f.in_db}
        stray = documented - cols
        assert not stray, f"{e.key}: documented fields absent from {e.orm.__name__}: {sorted(stray)}"


def test_every_domain_orm_column_is_documented_or_internal():
    by_orm = _catalog_by_orm()
    for model in DOMAIN_ORM:
        cols = {c.name for c in model.__table__.columns}
        documented = by_orm.get(model, set())
        internal = UNDOCUMENTED_ORM_COLUMNS.get(model.__tablename__, set())
        missing = cols - documented - internal
        assert not missing, (
            f"{model.__name__}: ORM columns neither documented in schema_catalog "
            f"nor listed internal: {sorted(missing)}"
        )
```

- [ ] **Step 3: Run the test to verify it fails (drives transcription completeness)**

Run: `.pixi/envs/api/bin/python -m pytest tests/test_schema_catalog_drift.py -q`
Expected: FAIL — `test_every_domain_orm_column_is_documented_or_internal` lists columns still missing from `CATALOG` (until every entity is transcribed).

- [ ] **Step 4: Complete the transcription until the test passes**

Fill in every entity's `fields` from `docs/schema.md`. Re-run until green. The failure messages name the exact missing columns per entity.

Run: `.pixi/envs/api/bin/python -m pytest tests/test_schema_catalog_drift.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/schema/schema_catalog.py tests/test_schema_catalog_drift.py
git commit -m "feat(schema): add curated schema catalog registry + ORM drift test"
```

---

### Task 2: Generate docs/schema.md from the catalog

**Files:**
- Create: `src/schema/generate_schema_docs.py`
- Modify: `docs/schema.md` (becomes generated output)
- Modify: `tests/test_schema_catalog_drift.py` (add md parity test)

**Interfaces:**
- Consumes: `CATALOG` from Task 1.
- Produces: `render_md() -> str`, `_MD_OUT: Path`, `main(argv=None) -> int` (writes the file). Later tasks add `render_ts()` to this module.

- [ ] **Step 1: Write the failing md-parity test**

Append to `tests/test_schema_catalog_drift.py`:

```python
from pathlib import Path

from schema.generate_schema_docs import _MD_OUT, render_md


def test_committed_schema_md_matches_codegen():
    assert Path(_MD_OUT).read_text() == render_md(), (
        "docs/schema.md is out of sync with schema_catalog.py. "
        "Regenerate with `pixi run schema-docs`."
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.pixi/envs/api/bin/python -m pytest tests/test_schema_catalog_drift.py::test_committed_schema_md_matches_codegen -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'schema.generate_schema_docs'`.

- [ ] **Step 3: Write the generator**

Create `src/schema/generate_schema_docs.py`. Keep the intro legend as a verbatim preamble constant (lifted from the current `docs/schema.md`, MINUS the `**Key annotations**: (PK)/(FK)` paragraph). Render each top-level entity as `## N. <Name> entity`, then that entity plus its children as sub-tables. Group top-level entities as: `1. Sample` (+ its `parent=="sample"` children as `### 1x.` sub-sections), `2. Acquisition` (+ its children), matching the existing doc's ordering.

```python
"""Codegen docs/schema.md AND the frontend schemaData.ts from schema_catalog.py.

Single source of truth is schema_catalog.CATALOG. Parity guarded by
tests/test_schema_catalog_drift.py. Regenerate: `pixi run schema-docs`.
"""
from __future__ import annotations

import sys
from pathlib import Path

from schema.schema_catalog import CATALOG, CatalogEntity

_ROOT = Path(__file__).resolve().parents[2]
_MD_OUT = _ROOT / "docs" / "schema.md"

_PREAMBLE = """\
# Database Model: CryoET + AI Portal

This document enumerates every field stored in the portal database, organized by
entity (Sample → Acquisition → Tomogram → Annotation). For each field it lists
the data type and the **authoritative source**.

<!-- AUTO-GENERATED by src/schema/generate_schema_docs.py — do not edit by hand.
     Edit src/schema/schema_catalog.py and run `pixi run schema-docs`. -->
"""


def _kind_label(kind: str) -> str:
    return "researcher authored" if kind == "authored" else "derived"


def _rows(entity: CatalogEntity) -> str:
    lines = ["| Field | Type | Source | Source Type | Notes |", "|---|---|---|---|---|"]
    for f in entity.fields:
        lines.append(
            f"| `{f.name}` | {f.type} | `{f.source}` | {_kind_label(f.kind)} | {f.notes} |"
        )
    return "\n".join(lines)


def _children(parent_key: str) -> list[CatalogEntity]:
    return [e for e in CATALOG if e.parent == parent_key]


def render_md() -> str:
    tops = [e for e in CATALOG if e.parent is None]
    out = [_PREAMBLE]
    for i, top in enumerate(tops, start=1):
        out.append(f"\n---\n\n## {i}. {top.name} entity\n\n_{top.cardinality}_\n")
        out.append(_rows(top))
        for j, child in enumerate(_children(top.key), start=1):
            gate = child.arm or ("chromatin only" if child.chromatin_only else "")
            suffix = f" ({gate})" if gate else ""
            out.append(f"\n### {i}{chr(ord('a') + j - 1)}. {child.name}{suffix} — _{child.cardinality}_\n")
            out.append(_rows(child))
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    _MD_OUT.write_text(render_md())
    print(f"wrote {_MD_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Regenerate and verify the test passes**

Run: `.pixi/envs/api/bin/python -m schema.generate_schema_docs`
Then: `.pixi/envs/api/bin/python -m pytest tests/test_schema_catalog_drift.py -q`
Expected: PASS. Review the `git diff docs/schema.md` — confirm content parity (PK/FK annotations gone; fields/notes intact). Adjust `_PREAMBLE` / formatting until the diff is only the intended PK/FK removal + structural regeneration.

- [ ] **Step 5: Commit**

```bash
git add src/schema/generate_schema_docs.py docs/schema.md tests/test_schema_catalog_drift.py
git commit -m "feat(schema): generate docs/schema.md from schema catalog (drop PK/FK)"
```

---

### Task 3: Extend the generator to emit the frontend schemaData.ts

**Files:**
- Modify: `src/schema/generate_schema_docs.py` (add `render_ts()` + `_TS_OUT` + emit in `main`)
- Create: `frontend/src/components/dataOrganization/schema/schemaData.ts` (generated)
- Modify: `tests/test_schema_catalog_drift.py` (add ts parity test)

**Interfaces:**
- Consumes: `CATALOG`.
- Produces: `render_ts() -> str`, `_TS_OUT: Path`. The emitted TS exports `type SourceKind = 'authored' | 'derived'`, `type Arm = 'experimental' | 'simulation'`, `interface SchemaField { field; type; source; kind; notes }`, `interface SchemaEntity { id; name; cardinality; arm?; chromatinOnly?; fields; children? }`, and `const SCHEMA: SchemaEntity[]`. This shape matches the prototype's `schemaData.ts` so the promoted Variant C consumes it unchanged.

- [ ] **Step 1: Write the failing ts-parity test**

Append to `tests/test_schema_catalog_drift.py`:

```python
from schema.generate_schema_docs import _TS_OUT, render_ts


def test_committed_schema_ts_matches_codegen():
    assert Path(_TS_OUT).read_text() == render_ts(), (
        "frontend schemaData.ts is out of sync with schema_catalog.py. "
        "Regenerate with `pixi run schema-docs`."
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.pixi/envs/api/bin/python -m pytest tests/test_schema_catalog_drift.py::test_committed_schema_ts_matches_codegen -q`
Expected: FAIL with `ImportError: cannot import name '_TS_OUT'`.

- [ ] **Step 3: Add `render_ts()` and TS emission**

Add to `src/schema/generate_schema_docs.py`. Build a nested `SchemaEntity` tree (top-level entities carrying `children`). Emit an AUTO-GENERATED header identical in spirit to `formFields.ts`.

```python
_TS_OUT = _ROOT / "frontend" / "src" / "components" / "dataOrganization" / "schema" / "schemaData.ts"


def _ts_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _ts_field(f) -> str:
    return (
        "        { "
        f"field: {_ts_str(f.name)}, type: {_ts_str(f.type)}, "
        f"source: {_ts_str(f.source)}, kind: {_ts_str(f.kind)}, "
        f"notes: {_ts_str(f.notes)} "
        "},"
    )


def _ts_entity(e, indent: str) -> str:
    lines = [f"{indent}{{"]
    lines.append(f"{indent}  id: {_ts_str(e.key)}, name: {_ts_str(e.name)},")
    lines.append(f"{indent}  cardinality: {_ts_str(e.cardinality)},")
    if e.arm:
        lines.append(f"{indent}  arm: {_ts_str(e.arm)},")
    if e.chromatin_only:
        lines.append(f"{indent}  chromatinOnly: true,")
    lines.append(f"{indent}  fields: [")
    lines.extend(_ts_field(f) for f in e.fields)
    lines.append(f"{indent}  ],")
    kids = _children(e.key)
    if kids:
        lines.append(f"{indent}  children: [")
        for k in kids:
            lines.append(_ts_entity(k, indent + "    "))
        lines.append(f"{indent}  ],")
    lines.append(f"{indent}}},")
    return "\n".join(lines)


def render_ts() -> str:
    tops = [e for e in CATALOG if e.parent is None]
    body = "\n".join(_ts_entity(e, "  ") for e in tops)
    return f"""\
// AUTO-GENERATED by src/schema/generate_schema_docs.py — do not edit by hand.
// Regenerate: `pixi run schema-docs`. Parity guarded by
// tests/test_schema_catalog_drift.py.

export type SourceKind = 'authored' | 'derived';
export type Arm = 'experimental' | 'simulation';

export interface SchemaField {{
  field: string;
  type: string;
  source: string;
  kind: SourceKind;
  notes: string;
}}

export interface SchemaEntity {{
  id: string;
  name: string;
  cardinality: string;
  arm?: Arm;
  chromatinOnly?: boolean;
  fields: SchemaField[];
  children?: SchemaEntity[];
}}

export const SCHEMA: SchemaEntity[] = [
{body}
];
"""
```

Then add `_TS_OUT.parent.mkdir(parents=True, exist_ok=True); _TS_OUT.write_text(render_ts())` to `main()` (before the return), and update the print line to mention both outputs.

- [ ] **Step 4: Regenerate and verify**

Run: `.pixi/envs/api/bin/python -m schema.generate_schema_docs`
Then: `.pixi/envs/api/bin/python -m pytest tests/test_schema_catalog_drift.py -q`
Expected: PASS (4 passed). Confirm `frontend/src/components/dataOrganization/schema/schemaData.ts` exists and typechecks: `cd frontend && npx tsc --noEmit`.

- [ ] **Step 5: Commit**

```bash
git add src/schema/generate_schema_docs.py frontend/src/components/dataOrganization/schema/schemaData.ts tests/test_schema_catalog_drift.py
git commit -m "feat(schema): generate frontend schemaData.ts from schema catalog"
```

---

### Task 4: Wire the generator into pixi tasks

**Files:**
- Modify: `pyproject.toml:56-63` (`[tool.pixi.tasks]`)

**Interfaces:**
- Consumes: `schema.generate_schema_docs.main`.
- Produces: `pixi run schema-docs`; `schema-docs` folded into the `sync` aggregate.

- [ ] **Step 1: Add the task and extend `sync`**

In `pyproject.toml` under `[tool.pixi.tasks]`, add:

```toml
schema-docs = "python -m schema.generate_schema_docs"
```

and add `"schema-docs"` to the `sync` task's `depends-on` list:

```toml
sync = { depends-on = ["json-schema", "form-fields", "sync-templates", "template-zips", "schema-docs"] }
```

- [ ] **Step 2: Verify the task runs and is idempotent**

Run: `pixi run schema-docs`
Then: `git diff --exit-code docs/schema.md frontend/src/components/dataOrganization/schema/schemaData.ts`
Expected: task prints the two written paths; `git diff --exit-code` returns 0 (no changes — already regenerated in Task 3).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(schema): add schema-docs pixi task and fold into sync"
```

---

### Task 5: Promote shared schema components out of the prototype

**Files:**
- Create: `frontend/src/components/dataOrganization/schema/shared.tsx`
- Test: `frontend/src/components/dataOrganization/schema/__tests__/filter.test.ts`

**Interfaces:**
- Consumes: `SchemaEntity`, `SchemaField`, `Arm`, `SourceKind` from generated `./schemaData`.
- Produces: `type SourceFilter = 'all' | 'authored' | 'derived'`; `interface Controls { arm: Arm; chromatin: boolean; source: SourceFilter }`; `filterTree(entities: SchemaEntity[], c: Controls): SchemaEntity[]`; components `SourceBadge`, `FieldsTable`, `EntityMeta`, `SchemaControls`.

- [ ] **Step 1: Copy the prototype `shared.tsx` into the real `schema/` dir**

Copy `frontend/src/components/dataOrganization/schemaPrototype/shared.tsx` to `frontend/src/components/dataOrganization/schema/shared.tsx`, changing the import of field types from `./schemaData` (the generated file created in Task 3) and removing the `// PROTOTYPE` banner. The logic (filterTree, SchemaControls, FieldsTable, SourceBadge, EntityMeta) is unchanged — it already matches the generated `SchemaEntity` shape.

- [ ] **Step 2: Write a focused unit test for the filter (the one piece of real logic)**

Create `frontend/src/components/dataOrganization/schema/__tests__/filter.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { filterTree } from '../shared'
import { SCHEMA } from '../schemaData'

describe('filterTree', () => {
  it('hides chromatin sub-entity when non-chromatin selected', () => {
    const tree = filterTree(SCHEMA, { arm: 'experimental', chromatin: false, source: 'all' })
    const sample = tree.find((e) => e.id === 'sample')!
    expect(sample.children?.some((c) => c.id === 'chromatin')).toBe(false)
  })

  it('hides simulation-only entities under the experimental arm', () => {
    const tree = filterTree(SCHEMA, { arm: 'experimental', chromatin: true, source: 'all' })
    const sample = tree.find((e) => e.id === 'sample')!
    expect(sample.children?.some((c) => c.id === 'md_run')).toBe(false)
  })

  it('source=authored drops derived fields', () => {
    const tree = filterTree(SCHEMA, { arm: 'experimental', chromatin: true, source: 'authored' })
    const acq = tree.find((e) => e.id === 'acquisition')!
    expect(acq.fields.every((f) => f.kind === 'authored')).toBe(true)
  })
})
```

- [ ] **Step 3: Run the test**

Run: `cd frontend && npx vitest run src/components/dataOrganization/schema/__tests__/filter.test.ts`
Expected: PASS (3 tests). If the generated `SCHEMA` lacks a simulation-only `md_run` child or a `chromatin` child, that's a Task 1 transcription gap — fix the catalog, regenerate, re-run.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/dataOrganization/schema/shared.tsx frontend/src/components/dataOrganization/schema/__tests__/filter.test.ts
git commit -m "feat(schema-page): promote shared schema controls + filter with tests"
```

---

### Task 6: Real SchemaExplorer (Variant C layout) on the schema tab

**Files:**
- Create: `frontend/src/components/dataOrganization/schema/SchemaExplorer.tsx`
- Modify: `frontend/src/routes/data-organization.tsx`

**Interfaces:**
- Consumes: `SCHEMA` from `./schemaData`; `Controls`, `SchemaControls`, `filterTree`, `FieldsTable`, `EntityMeta` from `./shared`.
- Produces: `export function SchemaExplorer()` — no props (owns its own filter state); renders the tree + two-pane layout with the parent-entity breadcrumb over the sub-entity title.

- [ ] **Step 1: Author `SchemaExplorer.tsx` from the prototype Variant C + container**

Combine the prototype's `SchemaExplorer.tsx` (control state + heading) and `VariantC.tsx` (tree + two-pane, including the `parent`-breadcrumb overline added during prototyping) into one real component. Drop all `?variant` handling and the `PrototypeSwitcher`. Concretely: the container holds `useState<Controls>`, renders `<SchemaControls>` + the two-pane tree from `filterTree(SCHEMA, controls)`. The right pane shows `parent.name` as an overline above the selected entity's `name`, then `<EntityMeta>` + `<FieldsTable>` (all as in the prototype VariantC, which already typechecks).

- [ ] **Step 2: Point the route's schema tab at the real component**

In `frontend/src/routes/data-organization.tsx`:
- Change the import from `~/components/dataOrganization/schemaPrototype/SchemaExplorer` to `~/components/dataOrganization/schema/SchemaExplorer`.
- Remove `variant` from `DataOrgSearch` and from `validateSearch` (keep only `tab`).
- Replace `<SchemaExplorer variant={variant} onVariantChange={...} />` with `<SchemaExplorer />`.

```tsx
// DataOrgSearch shrinks to just the tab:
type DataOrgSearch = { tab: 'placing' | 'schema' }

export const Route = createFileRoute('/data-organization')({
  validateSearch: (search: Record<string, unknown>): DataOrgSearch => ({
    tab: search.tab === 'schema' ? 'schema' : 'placing',
  }),
  component: DataOrganization,
})
```

And in the component, drop `variant` from `Route.useSearch()` and simplify the tab body to `{tab === 'schema' ? <SchemaExplorer /> : ( <> ...placing... </> )}`.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no output (clean).

- [ ] **Step 4: Verify it renders (SSR smoke test)**

Run: `cd frontend && (timeout 60 npx vite dev --port 5197 &) && sleep 11 && curl -s "http://localhost:5197/data-organization?tab=schema" | grep -o "acquisition.toml" | head -1`
Expected: prints `acquisition.toml` (schema content server-rendered, no error boundary). Stop the server after.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dataOrganization/schema/SchemaExplorer.tsx frontend/src/routes/data-organization.tsx
git commit -m "feat(schema-page): real tree + two-pane schema explorer on data-organization"
```

---

### Task 7: Delete the prototype scaffolding

**Files:**
- Delete: `frontend/src/components/dataOrganization/schemaPrototype/` (entire directory: `schemaData.ts`, `shared.tsx`, `VariantA.tsx`, `VariantC.tsx`, `SchemaExplorer.tsx`, `PrototypeSwitcher.tsx`, `NOTES.md`)

**Interfaces:**
- Consumes: nothing (all references replaced in Task 6).

- [ ] **Step 1: Confirm nothing still imports the prototype**

Run: `cd frontend && grep -rn "schemaPrototype" src` 
Expected: no matches (Task 6 repointed the only importer).

- [ ] **Step 2: Delete the directory**

Run: `git rm -r frontend/src/components/dataOrganization/schemaPrototype`

- [ ] **Step 3: Typecheck + full frontend tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: clean typecheck; all vitest tests pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(schema-page): remove layout prototype scaffolding"
```

---

### Task 8: Full verification pass

**Files:** none (verification only).

- [ ] **Step 1: Backend suite + drift green**

Run: `.pixi/envs/api/bin/python -m pytest tests/test_schema_catalog_drift.py tests/test_form_fields_drift.py -q`
Expected: all pass.

- [ ] **Step 2: Regeneration is idempotent**

Run: `pixi run sync && git diff --exit-code docs/schema.md frontend/src/components/dataOrganization/schema/schemaData.ts`
Expected: exit 0 — the aggregate regen produces no diff.

- [ ] **Step 3: Drive the real page**

Run: `cd frontend && (timeout 90 npx vite dev --port 5196 &) && sleep 11`, then open `http://localhost:5196/data-organization?tab=schema`. Confirm: the tree lists Sample + Acquisition with nested sub-entities; clicking a sub-entity shows the parent overline (e.g. "Sample" over "Chromatin"); the arm/project toggles hide/show entities; the source toggle filters fields; every field shows a provenance badge. Stop the server.

- [ ] **Step 4: Final commit if any regen diffs remained**

```bash
git add -A && git commit -m "chore(schema): regenerate schema artifacts" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:**
- Interactive table w/ entity nesting → Tasks 5–6 (tree + two-pane, `children`).
- Toggle experimental/simulation, chromatin/non-chromatin, authored/derived + "from where" → `Controls` + `filterTree` + `source`/`kind`/`SourceBadge` (Tasks 3, 5, 6).
- Second tab on data-organization → Task 6 (tab already scaffolded; variant param removed).
- One true source / no drift → `schema_catalog.py` + generators + drift tests (Tasks 1–4).
- Regenerate schema.md, PK/FK dropped → Task 2.
- Variant C won, parent breadcrumb → Task 6.
- Delete prototype → Task 7.

**Placeholder scan:** The only "transcribe the rest" instruction (Task 1 Step 4) is backed by a failing drift test that enumerates exactly what's missing — completeness is machine-enforced, not left to judgment. All generator/test code is given in full.

**Type consistency:** `SchemaEntity`/`SchemaField`/`SourceKind`/`Arm` are defined once by `render_ts()` (Task 3) and consumed by `shared.tsx`/`SchemaExplorer.tsx` (Tasks 5–6). `Controls`/`SourceFilter`/`filterTree` defined in Task 5, consumed in Task 6. `CatalogField.kind` (Task 1) feeds both the md `Source Type` column (Task 2) and the ts `kind` (Task 3).
