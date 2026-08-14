# Browse-page ID Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a search box to the three browse pages (`/data`, `/experimental`, `/md-simulation`) that finds samples by any ID in the hierarchy — sample, acquisition, tomogram, or annotation — and surfaces the containing sample with its matching acquisition auto-expanded and marked.

**Architecture:** Extend the existing (dormant) `/samples` `q` param from a `sample_id`+`description` `LIKE` to an IDs-only match across the sample hierarchy via a single `UNION ALL` "match-locator" query; return per-sample match locations so the frontend can auto-expand. Add the missing input widget (the rest of the `q` pipeline already exists end-to-end). No new services, no schema/DB migration.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (SQLite), Pydantic v2, pixi envs; frontend TanStack Start/Router + react-query v5 + MUI v6 + material-react-table v3, types generated from OpenAPI, vitest.

## Global Constraints

- Python tests run through pixi: `pixi run -e api pytest` (never bare pytest). One file: `pixi run -e api pytest tests/catalog/test_api_search.py`.
- Frontend tests: `cd frontend && npm test` (vitest). Single file: `npm test -- src/utils/__tests__/foo.test.ts`.
- After ANY change to `src/catalog/api/schemas.py` or routes, regenerate the committed OpenAPI + frontend types with `pixi run -e api sync`, then commit `frontend/openapi.json` + `frontend/src/types.gen.ts`. The `test_openapi_drift.py` test fails if you forget.
- `q` matching is **IDs-only** — it must NOT match `description` or any free-text field (deliberate change from the old behavior; nothing consumes the old behavior).
- Searchable entities and their ID columns (all carry `sample_id` + `acquisition_id` except `SampleORM`): `SampleORM.sample_id`, `AcquisitionORM.acquisition_id`, `RawTomogramORM.tomogram_id`, `PostProcessedTomogramORM.tomogram_id`, `AnnotationORM.annotation_id`.
- Follow existing patterns; do not restructure unrelated code. Commit after each task.
- Out of scope (do NOT build): `tilt_series_id` matching, fuzzy/typo tolerance, autocomplete, any search-index service, and the `/filters/options` cache (that ships as a separate stacked PR — see the spec).

**Spec:** `docs/superpowers/specs/2026-08-10-browse-page-id-search-design.md`

---

## File Structure

Backend:
- `src/catalog/api/schemas.py` — add `SampleMatch` model; add `matches: list[SampleMatch]` to `SampleSummary`.
- `src/catalog/api/routes/samples.py` — add `_match_locator(q)` helper; replace the `q` `LIKE` block with an `IN (match-locator)` filter; populate `matches` on each returned summary.
- `tests/catalog/test_api_search.py` — new; self-contained fixture + search tests.

Frontend:
- `frontend/openapi.json`, `frontend/src/types.gen.ts` — regenerated (Task 2).
- `frontend/src/types.ts` — add `SampleMatch` re-export.
- `frontend/src/components/landing/SampleSearchField.tsx` — new shared input widget.
- `frontend/src/components/landing/SamplesBrowser.tsx`, `AllDataBrowser.tsx` — mount the widget.
- `frontend/src/components/landing/samplesMatchDisplay.ts` — new; pure helpers `expandedFromMatches` + `formatMatchSummary`.
- `frontend/src/components/landing/SamplesPortalTable.tsx` — controlled expand from matches; pass matches to the sub-table.
- `frontend/src/components/landing/AcquisitionsSubTable.tsx` — render the match marker.
- `frontend/src/components/landing/__tests__/samplesMatchDisplay.test.ts` — new; helper unit tests.
- `frontend/src/components/landing/__tests__/SampleSearchField.test.tsx` — new; widget test.

---

## Task 1: Backend — `matches` on the samples list, IDs-only

**Files:**
- Modify: `src/catalog/api/schemas.py` (SampleSummary ~17-35)
- Modify: `src/catalog/api/routes/samples.py` (imports line 7; `q` block 345-353; response 369-387)
- Test: `tests/catalog/test_api_search.py` (create)

**Interfaces:**
- Produces (Pydantic → OpenAPI → frontend): `SampleMatch { acquisition_id: str | None; kind: "sample"|"acquisition"|"tomogram"|"annotation"; matched_id: str }`, and `SampleSummary.matches: list[SampleMatch]` (empty when `q` absent or the row matched only at sample level with no descendant hits).
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

Create `tests/catalog/test_api_search.py` with its own seed (unambiguous IDs so the description-regression assertion is clean):

```python
"""ID search over the sample hierarchy (GET /samples?q=...)."""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from schema import (
    Acquisition,
    AcquisitionFile,
    Annotation,
    PostProcessedTomogram,
    Sample,
    SampleRecord,
)
from schema.schema import DataSource, Project
from catalog import db, orm
from catalog.persistence import upsert_sample_record
from catalog.api.deps import get_session
from catalog.api.main import create_app


@pytest.fixture
def client(tmp_path):
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    app = create_app()
    app.state.engine = engine

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    s = Session()
    try:
        acq = AcquisitionFile(
            acquisition=Acquisition(acquisition_id="acq-100"),
            post_processed_tomogram=[
                PostProcessedTomogram(
                    id="tomo-777", reconstruction_alignment_id="align1"
                )
            ],
            annotation=[
                Annotation(
                    id="annot-999",
                    files=["x.mrc"],
                    reconstruction_alignment_id="align1",
                )
            ],
        )
        rec = SampleRecord(
            sample=Sample(
                sample_id="smp-alpha",
                data_source=DataSource.experimental,
                project=Project.chromatin,
                description="quickbrownfox marker",
            ),
            acquisitions={"acq-100": acq},
        )
        upsert_sample_record(s, rec, extras=[], run_id="run-1", now=time.time())
        # A second sample with none of the search tokens, to prove filtering.
        upsert_sample_record(
            s,
            SampleRecord(
                sample=Sample(
                    sample_id="smp-beta",
                    data_source=DataSource.simulation,
                    project=Project.nanogold,
                )
            ),
            extras=[],
            run_id="run-1",
            now=time.time(),
        )
        s.commit()
    finally:
        s.close()
    return TestClient(app)


def _by_id(resp):
    return {s["sample_id"]: s for s in resp.json()}


def test_q_matches_tomogram_id_surfaces_sample_and_acquisition(client):
    r = client.get("/samples", params={"q": "tomo-777"})
    assert r.status_code == 200
    samples = _by_id(r)
    assert set(samples) == {"smp-alpha"}
    tomo = [m for m in samples["smp-alpha"]["matches"] if m["kind"] == "tomogram"]
    assert tomo == [
        {"kind": "tomogram", "acquisition_id": "acq-100", "matched_id": "tomo-777"}
    ]


def test_q_matches_annotation_id(client):
    samples = _by_id(client.get("/samples", params={"q": "annot-999"}))
    assert set(samples) == {"smp-alpha"}
    assert any(m["kind"] == "annotation" for m in samples["smp-alpha"]["matches"])


def test_q_matches_acquisition_id(client):
    samples = _by_id(client.get("/samples", params={"q": "acq-100"}))
    assert set(samples) == {"smp-alpha"}
    assert any(m["kind"] == "acquisition" for m in samples["smp-alpha"]["matches"])


def test_q_matches_sample_id_with_null_acquisition(client):
    samples = _by_id(client.get("/samples", params={"q": "smp-alpha"}))
    assert set(samples) == {"smp-alpha"}
    assert {
        "kind": "sample",
        "acquisition_id": None,
        "matched_id": "smp-alpha",
    } in samples["smp-alpha"]["matches"]


def test_q_is_case_insensitive(client):
    assert set(_by_id(client.get("/samples", params={"q": "TOMO-777"}))) == {
        "smp-alpha"
    }


def test_q_no_match_returns_empty(client):
    assert client.get("/samples", params={"q": "no-such-id"}).json() == []


def test_q_does_not_match_description(client):
    # 'quickbrownfox' is only in smp-alpha.description — IDs-only search ignores it.
    assert client.get("/samples", params={"q": "quickbrownfox"}).json() == []


def test_matches_absent_without_q(client):
    samples = _by_id(client.get("/samples"))
    assert samples["smp-alpha"]["matches"] == []
    assert samples["smp-beta"]["matches"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run -e api pytest tests/catalog/test_api_search.py -q`
Expected: FAIL — `test_q_matches_tomogram_id...` fails because `q="tomo-777"` returns `[]` (old `q` only hits sample_id/description), and `matches` key is missing (KeyError).

- [ ] **Step 3: Add the `SampleMatch` schema and `matches` field**

In `src/catalog/api/schemas.py`, add `Literal` to the imports at the top:

```python
from typing import Literal

from pydantic import BaseModel
```

Then, immediately above `class SampleSummary(BaseModel):`, add:

```python
class SampleMatch(BaseModel):
    """Where a browse-page `q` search matched inside a sample. Sample-level
    matches carry ``acquisition_id=None``; descendant matches carry the
    acquisition so the frontend can auto-expand and mark it."""

    acquisition_id: str | None = None
    kind: Literal["sample", "acquisition", "tomogram", "annotation"]
    matched_id: str
```

And add this field to `SampleSummary` (after `md_preview_path`):

```python
    # Populated only when the list is called with `q`: the IDs (and their
    # acquisition, if any) that matched, so the browse table can auto-expand
    # the matching acquisitions. Empty when there is no `q`.
    matches: list[SampleMatch] = []
```

- [ ] **Step 4: Add the match-locator + wire it into the query and response**

In `src/catalog/api/routes/samples.py`, extend the SQLAlchemy import (line 7):

```python
from sqlalchemy import and_, exists, func, literal, null, or_, select, union_all
```

Add `SampleMatch` to the `catalog.api.schemas` import block (alongside `SampleSummary`).

Add this helper just below `_enum_val` (after line 39):

```python
def _match_locator(q: str):
    """UNION ALL of (sample_id, acquisition_id, kind, matched_id) rows where an
    ID at any level of the hierarchy matches `q` (case-insensitive substring).
    IDs-only — description and other free-text fields are intentionally not
    searched."""
    like = f"%{q.lower()}%"
    arms = [
        select(
            m.sample_id.label("sample_id"),
            (a if a is not None else null()).label("acquisition_id"),
            literal(k).label("kind"),
            i.label("matched_id"),
        ).where(func.lower(i).like(like))
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
```

Replace the `q` block (current lines 345-353) with:

```python
    # IDs-only free-text search across the hierarchy: keep only samples that
    # have a matching id at some level. See _match_locator.
    if q:
        locator = _match_locator(q).subquery()
        stmt = stmt.where(
            orm.SampleORM.sample_id.in_(select(locator.c.sample_id).distinct())
        )
```

Then, in the response section, compute per-page match details. Replace the `rows = session.execute(stmt).all()` line and the `return [...]` block (lines 368-387) with:

```python
    rows = session.execute(stmt).all()

    # Per-page match locations for auto-expand (only when searching).
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
```

- [ ] **Step 5: Run the search tests to verify they pass**

Run: `pixi run -e api pytest tests/catalog/test_api_search.py -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Run the existing samples tests (no regressions)**

Run: `pixi run -e api pytest tests/catalog/test_api.py -q`
Expected: PASS — existing list/filter/pagination tests unaffected (they don't pass `q`).

- [ ] **Step 7: Commit**

```bash
git add src/catalog/api/schemas.py src/catalog/api/routes/samples.py tests/catalog/test_api_search.py
git commit -m "feat(api): search /samples by ids across the hierarchy with match locations"
```

---

## Task 2: Regenerate OpenAPI + frontend types

**Files:**
- Modify (generated): `frontend/openapi.json`, `frontend/src/types.gen.ts`
- Modify: `frontend/src/types.ts`
- Test: `tests/catalog/test_openapi_drift.py` (existing — used as the check)

**Interfaces:**
- Produces: `SampleMatch` type exported from `~/types`; `SampleSummary.matches` present in generated types.

- [ ] **Step 1: Confirm the drift test currently fails (schema changed, artifacts stale)**

Run: `pixi run -e api pytest tests/catalog/test_openapi_drift.py -q`
Expected: FAIL — "openapi.json is stale against schemas.py".

- [ ] **Step 2: Regenerate the committed OpenAPI + types**

Run: `pixi run -e api sync`
This runs `python -m catalog.api.generate_openapi` (rewrites `frontend/openapi.json`) and `openapi-typescript` (rewrites `frontend/src/types.gen.ts`).

- [ ] **Step 3: Add the `SampleMatch` re-export to the barrel**

In `frontend/src/types.ts`, under the `// ── Sample list / summary ──` section (next to `export type SampleSummary`), add:

```typescript
export type SampleMatch = Defined<Schemas['SampleMatch']>;
```

- [ ] **Step 4: Verify the drift test passes and types compile**

Run: `pixi run -e api pytest tests/catalog/test_openapi_drift.py -q`
Expected: PASS.
Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (confirms `Schemas['SampleMatch']` and `matches` exist).

- [ ] **Step 5: Commit**

```bash
git add frontend/openapi.json frontend/src/types.gen.ts frontend/src/types.ts
git commit -m "chore(frontend): regenerate types for SampleSummary.matches / SampleMatch"
```

---

## Task 3: Frontend — search widget wired into all three pages

**Files:**
- Create: `frontend/src/components/landing/SampleSearchField.tsx`
- Create: `frontend/src/components/landing/__tests__/SampleSearchField.test.tsx`
- Modify: `frontend/src/components/landing/SamplesBrowser.tsx` (header Stack ~130-147)
- Modify: `frontend/src/components/landing/AllDataBrowser.tsx` (header Stack ~125-142)

**Interfaces:**
- Produces: `<SampleSearchField value={string} onChange={(q: string) => void} />`.
- Consumes: the existing `patch(...)` in each browser; `search.q` from `SamplesSearchParams`. `patch({ q })` is safe — `applyGating` leaves non-registry keys like `q` untouched (verified: `filterGating.ts:107` `if (!field ...) continue`).

- [ ] **Step 1: Write the failing widget test**

Create `frontend/src/components/landing/__tests__/SampleSearchField.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SampleSearchField } from '../SampleSearchField';

describe('SampleSearchField', () => {
  it('shows the current value', () => {
    render(<SampleSearchField value="tomo-777" onChange={() => {}} />);
    expect(screen.getByRole('textbox')).toHaveValue('tomo-777');
  });

  it('calls onChange with the typed value', () => {
    const onChange = vi.fn();
    render(<SampleSearchField value="" onChange={onChange} />);
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'acq-100' }
    });
    expect(onChange).toHaveBeenCalledWith('acq-100');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- src/components/landing/__tests__/SampleSearchField.test.tsx`
Expected: FAIL — cannot resolve `../SampleSearchField`.

- [ ] **Step 3: Create the widget**

Create `frontend/src/components/landing/SampleSearchField.tsx`:

```tsx
import { TextField, InputAdornment } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';

// Controlled free-text search box for the browse pages. The URL (`q`) is the
// source of truth: value comes from the URL, onChange writes it back on every
// keystroke; the parent debounces the *query* (useDebounce), mirroring the
// warnings-page search (OutstandingIssuesTable).
export function SampleSearchField({
  value,
  onChange
}: {
  readonly value: string;
  readonly onChange: (q: string) => void;
}) {
  return (
    <TextField
      onChange={e => onChange(e.target.value)}
      placeholder="Search ids (sample, acquisition, tomogram, annotation)"
      size="small"
      slotProps={{
        input: {
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon fontSize="small" />
            </InputAdornment>
          )
        }
      }}
      sx={{ minWidth: { xs: '100%', sm: 360 }, maxWidth: 520 }}
      value={value}
    />
  );
}
```

- [ ] **Step 4: Run the widget test to verify it passes**

Run: `cd frontend && npm test -- src/components/landing/__tests__/SampleSearchField.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Mount it in `SamplesBrowser.tsx`**

Add the import near the other landing imports:

```tsx
import { SampleSearchField } from '~/components/landing/SampleSearchField';
```

In the header `Stack` (currently title + mobile Filters button, lines ~130-147), insert the field between the title and the button so it sits on the header row:

```tsx
          <Stack
            alignItems="center"
            direction="row"
            justifyContent="space-between"
            spacing={2}
          >
            <Typography component="h1" variant="h4">
              {title}
            </Typography>
            <SampleSearchField
              onChange={v => patch({ q: v || undefined })}
              value={search.q ?? ''}
            />
            <Button
              onClick={() => setFiltersOpen(true)}
              startIcon={<FilterListIcon />}
              sx={{ display: { xs: 'inline-flex', md: 'none' }, flexShrink: 0 }}
              variant="outlined"
            >
              Filters{chips.length > 0 ? ` (${chips.length})` : ''}
            </Button>
          </Stack>
```

- [ ] **Step 6: Mount it in `AllDataBrowser.tsx`**

Same import, and the same `<SampleSearchField ... />` block inserted into its header `Stack` (lines ~125-142), between the title and the Filters `Button`.

- [ ] **Step 7: Verify typecheck + full frontend suite**

Run: `cd frontend && npx tsc --noEmit && npm test`
Expected: no type errors; all tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/landing/SampleSearchField.tsx \
        frontend/src/components/landing/__tests__/SampleSearchField.test.tsx \
        frontend/src/components/landing/SamplesBrowser.tsx \
        frontend/src/components/landing/AllDataBrowser.tsx
git commit -m "feat(frontend): add id search box to the browse pages"
```

---

## Task 4: Frontend — auto-expand matched samples and mark the match

**Files:**
- Create: `frontend/src/components/landing/samplesMatchDisplay.ts`
- Create: `frontend/src/components/landing/__tests__/samplesMatchDisplay.test.ts`
- Modify: `frontend/src/components/landing/SamplesPortalTable.tsx` (state.expanded ~189-192; renderDetailPanel ~160-165)
- Modify: `frontend/src/components/landing/AcquisitionsSubTable.tsx` (props + marker line)

**Interfaces:**
- Produces: `expandedFromMatches(rows: SampleSummary[]): Record<string, boolean>` — `{ [sample_id]: true }` for rows with ≥1 match; and `formatMatchSummary(matches: SampleMatch[]): string`.
- Consumes: `SampleSummary.matches` (Task 1/2), `AcquisitionsSubTable` gains an optional `matches?: SampleMatch[]` prop.

- [ ] **Step 1: Write the failing helper test**

Create `frontend/src/components/landing/__tests__/samplesMatchDisplay.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { SampleSummary, SampleMatch } from '~/types';
import {
  expandedFromMatches,
  formatMatchSummary
} from '../samplesMatchDisplay';

const row = (
  sample_id: string,
  matches: SampleMatch[]
): SampleSummary => ({ sample_id, matches }) as unknown as SampleSummary;

describe('expandedFromMatches', () => {
  it('expands only rows that have matches', () => {
    const rows = [
      row('a', [
        { kind: 'tomogram', acquisition_id: 'acq1', matched_id: 't1' }
      ]),
      row('b', [])
    ];
    expect(expandedFromMatches(rows)).toEqual({ a: true });
  });

  it('returns {} when nothing matched', () => {
    expect(expandedFromMatches([row('a', [])])).toEqual({});
  });
});

describe('formatMatchSummary', () => {
  it('lists descendant matches with their acquisition', () => {
    expect(
      formatMatchSummary([
        { kind: 'tomogram', acquisition_id: 'acq-100', matched_id: 'tomo-777' },
        { kind: 'annotation', acquisition_id: 'acq-100', matched_id: 'annot-999' }
      ])
    ).toBe(
      "Search match: tomogram 'tomo-777' in acq-100, annotation 'annot-999' in acq-100"
    );
  });

  it('handles a sample-level-only match', () => {
    expect(
      formatMatchSummary([
        { kind: 'sample', acquisition_id: null, matched_id: 'smp-alpha' }
      ])
    ).toBe('Search match: this sample');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- src/components/landing/__tests__/samplesMatchDisplay.test.ts`
Expected: FAIL — cannot resolve `../samplesMatchDisplay`.

- [ ] **Step 3: Implement the helpers**

Create `frontend/src/components/landing/samplesMatchDisplay.ts`:

```ts
import type { SampleSummary, SampleMatch } from '~/types';

// Row ids (= sample_id, see SamplesPortalTable getRowId) to auto-expand: every
// sample the server reported a search match for.
export function expandedFromMatches(
  rows: SampleSummary[]
): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const r of rows) {
    if (r.matches && r.matches.length > 0) {
      out[r.sample_id] = true;
    }
  }
  return out;
}

// Human-readable marker shown atop an expanded sample's acquisitions. Sample-id
// hits carry no acquisition, so when only the sample matched we say so.
export function formatMatchSummary(matches: SampleMatch[]): string {
  const parts = matches
    .filter(m => m.kind !== 'sample')
    .map(
      m =>
        `${m.kind} '${m.matched_id}'` +
        (m.acquisition_id ? ` in ${m.acquisition_id}` : '')
    );
  return parts.length > 0
    ? `Search match: ${parts.join(', ')}`
    : 'Search match: this sample';
}
```

- [ ] **Step 4: Run the helper test to verify it passes**

Run: `cd frontend && npm test -- src/components/landing/__tests__/samplesMatchDisplay.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Auto-expand matched rows in `SamplesPortalTable.tsx`**

Add imports:

```tsx
import { expandedFromMatches } from './samplesMatchDisplay';
```

Inside the component (after `const { rows, loading, filters, expandAllDetails } = props;`), compute:

```tsx
    // When searching, the server tags each row with `matches`; expand exactly
    // those rows so the hit's acquisition is visible. Acquisition-filter mode
    // (expandAllDetails) still wins and opens everything.
    const searchExpanded = useMemo(() => expandedFromMatches(rows), [rows]);
    const hasSearchMatches = Object.keys(searchExpanded).length > 0;
```

Change the `state` block (currently lines ~189-192) to:

```tsx
      state: {
        isLoading: loading,
        ...(expandAllDetails
          ? { expanded: true }
          : hasSearchMatches
            ? { expanded: searchExpanded }
            : {})
      },
```

Change `renderDetailPanel` (lines ~160-165) to pass the row's matches:

```tsx
      renderDetailPanel: ({ row }) => (
        <AcquisitionsSubTable
          filters={filters}
          matches={row.original.matches}
          sampleId={row.original.sample_id}
        />
      ),
```

- [ ] **Step 6: Render the marker in `AcquisitionsSubTable.tsx`**

Add imports:

```tsx
import type { SampleMatch } from '~/types';
import { formatMatchSummary } from './samplesMatchDisplay';
```

Extend the props:

```tsx
export function AcquisitionsSubTable({
  sampleId,
  filters,
  matches
}: {
  readonly sampleId: string;
  readonly filters?: SamplesSearchParams;
  readonly matches?: SampleMatch[];
}) {
```

Render the marker just inside the outer `<Box>`, above the "Acquisitions" overline:

```tsx
      {matches && matches.length > 0 ? (
        <Typography
          color="primary"
          sx={{ display: 'block', mb: 0.5, fontWeight: 600 }}
          variant="body2"
        >
          {formatMatchSummary(matches)}
        </Typography>
      ) : null}
```

- [ ] **Step 7: Typecheck + full frontend suite**

Run: `cd frontend && npx tsc --noEmit && npm test`
Expected: no type errors; all tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/landing/samplesMatchDisplay.ts \
        frontend/src/components/landing/__tests__/samplesMatchDisplay.test.ts \
        frontend/src/components/landing/SamplesPortalTable.tsx \
        frontend/src/components/landing/AcquisitionsSubTable.tsx
git commit -m "feat(frontend): auto-expand and mark search-matched acquisitions"
```

---

## Final verification (after all tasks)

- [ ] Backend: `pixi run -e api pytest -q` — full suite green.
- [ ] Frontend: `cd frontend && npx tsc --noEmit && npm test` — types + suite green.
- [ ] Manual smoke (optional, via `pixi run` dev server or the `run` skill): on `/experimental`, type a tomogram id → the containing sample row auto-expands and shows "Search match: tomogram '…' in …"; clearing the box restores the normal list.

## Notes for the implementer

- The old `q` behavior (matching `description`) is intentionally removed. `test_q_does_not_match_description` guards this.
- Do not add a DB migration — no columns change; `matches` is computed at request time.
- The match-locator runs twice per search request (once to filter, once to fetch page details). At current scale this is sub-15ms; do not prematurely optimize. If it ever matters, FTS5 is the documented next step (see spec).
- `applyGating` passes `q` through unchanged, so routing `patch({ q })` through it is safe and keeps the single write path.
