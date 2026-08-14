# Browse-page ID search — design

**Date:** 2026-08-10
**Status:** Approved for planning
**Author:** allison-truhlar (with Claude)

## Goal

Add a free-text search field to the three main data pages — **All data**
(`/data`), **Experimental** (`/experimental`), and **MD simulations**
(`/md-simulation`) — that lets a user find records by ID anywhere in the data
hierarchy:

- `sample_id`
- `acquisition_id`
- `tomogram_id` (raw and post-processed)
- `annotation_id`

Matches on descendant IDs (tomogram/annotation/acquisition) resolve **up** to
the containing sample, which is shown in the results with its matching
acquisition auto-expanded and marked.
Note - after looking at the prototype, the auto-expansion didn't work in practice - 
for example, if you typed in a sample name in the search input, that sample gets 
expanded because all the acquistions match that sample id, but it's likely you were 
interested in the sample, not the acquisitions, since you were searching a sample id,
so the expansion is not useful. I replaced this design with highlighting all the 
acquistion rows that have a match in the acquisition id, tomogram id, or annotation
id. This does require the user to expand the sample row, however.

## Context / prior art

The browse-page search has been **latent backend plumbing since 2026-05-11**
(commit `674a0868`, "expand /samples with filters, aggregate counts, typed
detail"); `description` matching was added 2026-06-29 (`a3c25c74`). The `q`
param, its Zod schema, and the query-string builder all exist end-to-end —
**only the input widget on the browse pages was never built.** No UI has ever
driven the `/samples` `q` path, so its current behavior is safe to change.

Already present and working (do **not** rebuild):
- Registry-driven facet filters + `/filters/options` + dynamic facet gating
  (`filterGating.ts`).
- A debounced-`TextField` → `q` search pattern on the *warnings* page
  (`OutstandingIssuesTable.tsx`) — a template to copy.

### Engine decision (settled)

Stay on **SQLite**. A benchmark against the real prod DB (93 samples / 423
acquisitions / 211 tomograms, via `oc exec` on the API pod) showed:

| Endpoint | Median |
|---|---|
| `/samples` list | 14 ms |
| `/samples` filtered by `data_source` | 14 ms |
| `/samples?q=…` | 13 ms |
| `/filters/options` | **194 ms** |

Browsing/filtering/search are not a performance problem and won't be into the
low thousands of records. The only slow path is `/filters/options`, and its
cost is **64 sequential per-field queries**, not data volume — cacheable to
~0ms because options only change after a scan. A dedicated search engine
(OpenSearch/Typesense/Meilisearch) is **deferred**; revisit when
autocomplete/relevance ranking becomes a product requirement, or the catalog
crosses ~10k records. SQLite FTS5 is the noted intermediate step (in-process
BM25 ranking + prefix autocomplete, no new service) before a separate engine.

The `/filters/options` cache is **out of scope for this spec** — it ships as a
separate **stacked PR** on top of the search feature (see "Follow-on" below).

## Non-goals

- `tilt_series_id` matching (trivial union addition later if wanted).
- Fuzzy / typo tolerance, relevance ranking, autocomplete.
- Any search-index service.
- Changing the warnings/scan-log `q` searches (`manage.py:231`, `manage.py:367`)
  — these are independent code paths and are untouched.

## Design

### 1. Backend — match `q` against descendant IDs

**File:** `src/catalog/api/routes/samples.py` (the `q` block, ~lines 345–353).

Replace the current `sample_id`-OR-`description` `LIKE` with an **IDs-only**
match across the hierarchy. Every searchable child table carries a `sample_id`
column (confirmed by the `_scoped` joins in `routes/filters.py`), so the match
is a single `UNION ALL` **match-locator** subquery producing rows of:

```
(sample_id, acquisition_id, kind, matched_id)
```

- `kind ∈ {sample, acquisition, tomogram, annotation}`.
- Sample-level match → `acquisition_id IS NULL`.
- Tomogram rows come from both `raw_tomograms` and `post_processed_tomograms`.
- `matched_id` is the ID column that matched (`LOWER(col) LIKE '%q%'`).

The list query's `WHERE` becomes `samples.sample_id IN (SELECT DISTINCT
sample_id FROM <match-locator>)`. This composes unchanged with the existing
registry filters, sort, and pagination.

**Behavior change:** `q` no longer matches `description`. Intentional; nothing
depends on the old behavior.

### 2. Backend — response carries match locations

**File:** `src/catalog/api/schemas.py` — extend `SampleSummary`.

When `q` is present, populate a new optional field on each returned summary:

```python
matches: list[SampleMatch] = []   # empty/absent when q not supplied

class SampleMatch(BaseModel):
    acquisition_id: str | None   # None for a sample-level match
    kind: Literal["sample", "acquisition", "tomogram", "annotation"]
    matched_id: str
```

Computed by running the match-locator query **for just the current page's
sample_ids** (≤ `limit` rows), grouped by `sample_id`. No extra cost when `q`
is absent.

Regenerate the frontend types afterward: `pixi`-side no-op; run the frontend
`gen:types` task so `frontend/src/types.gen.ts` picks up `matches` /
`SampleMatch`.

### 3. Frontend — search widget + result behavior

**New:** a small shared `SampleSearchField` component (debounced MUI
`TextField`, ~15 lines, modeled on `OutstandingIssuesTable.tsx`) that calls the
existing `patch({ q: value || undefined })`. The `q` param already round-trips
through the URL, the 300ms debounce, the react-query key, and the backend.

**Wired into both:**
- `frontend/src/components/landing/SamplesBrowser.tsx` (experimental + md)
- `frontend/src/components/landing/AllDataBrowser.tsx` (all data)

placed in the header `Stack` next to the page title.

**Result behavior** (`SamplesPortalTable.tsx`): when `q` is active, and render higlighted
background on all acquisition rows inside `AcquisitionsSubTable` that have a match 
(e.g. `← contains tomogram 'tomo_xyz'`).

### 4. Testing

Backend (`tests/catalog/test_api_*.py`, alongside existing samples/filters tests):
- `q` matching each entity kind (`sample_id`, `acquisition_id`,
  `tomogram_id` for both raw and post-processed, `annotation_id`) returns the
  correct sample plus correct `matches` details.
- Non-matching `q` → empty result.
- `q` composes with a registry filter (intersection, not union).
- `description` no longer matches (regression guard on the intentional change).

Frontend:
- The search field round-trips `q` to the URL and back.

## Follow-on (separate stacked PR)

**Cache `/filters/options`.** Facet options change only after a scan, so cache
the computed `FiltersOptionsOut` keyed on the latest `scan_runs` id; when warm,
one cheap "latest scan id" lookup replaces the 64 per-field queries
(194ms → ~0). Invalidates automatically when a new scan completes. Small,
self-contained, and independently reviewable — stacked on the search branch.

## Risks / notes

- The `UNION ALL` locator runs per list request when `q` is set; at current and
  near-future scale this is sub-15ms. If it ever regresses, FTS5 is the next
  step (see engine decision).
