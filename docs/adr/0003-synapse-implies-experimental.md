# ADR-0003: `project = synapse` implies `data_source = experimental`

## Status
Accepted

## Context
The forms gate which sections appear from `data_source` (experimental vs
simulation) and `project`, reusing the filter `GROUPS` metadata
(`appliesTo` / `requiresProject`). When seeding a form from an uploaded file,
`data_source` must be reverse-inferred from which blocks are present, since it
is never written to the file.

During grilling it was established as a **durable domain fact** that synapse
data is never simulation-derived. The codebase did not encode this — the only
project-based rule was `requiresProject: 'chromatin'`. An invariant the forms
enforced but the schema permitted would just relocate the inconsistency.

## Decision
Encode `synapse ⇒ experimental` once, with `schema.py` as the source of truth.

- `schema.py` (`SampleRecord._check_project_blocks` or a sibling validator):
  reject `project = synapse` combined with `data_source = simulation` (and the
  simulation-only blocks).
- Mirror it in the shared gating metadata (`filterFields.ts` /
  `filter_fields.py`), e.g. a `requiresDataSource: 'experimental'` on the
  project, so **both** the authoring forms and the landing-page filter panel
  honor it.
- Form reverse-inference treats `project = synapse` as a hard
  simulation-excluder.

## Consequences
- A schema change separate from the form work, and a **prerequisite** for the
  gating behavior. Land it (with its drift test) before/with the gating.
- Existing data must already satisfy the invariant, or ingestion of a
  synapse+simulation sample will now fail — verify before shipping.
- If synapse simulations ever become real, this ADR must be reopened.

## Verification (2026-06-30)
Confirmed against the current catalog (`catalog.db`, 26 samples) that no
existing sample violates the invariant — the synapse + simulation count is 0:

```
sqlite> SELECT project, data_source, count(*) FROM samples GROUP BY 1, 2;
chromatin|experimental|2
chromatin|simulation|18
nanogold|experimental|1
synapse|experimental|5        -- all 5 synapse samples are experimental; 0 simulation
```
