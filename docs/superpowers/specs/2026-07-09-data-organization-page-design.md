# `/data-organization` page — design

## Purpose

A researcher-facing guide answering "I have new data — where does it go on the
Janelia file share so the scanner ingests it correctly?" Reorganizes the
content of `docs/data_organization.md` (upstream repo) into an
upload-oriented, starting-point framing rather than a spec dump.

Route: `/data-organization`. Static content page (no data loader), same layout
shape as the `/author` page (breadcrumb + `Stack` of sections).

## Sections

1. **Where to find the data**
   - All data lives on the Janelia file share, reachable over the Janelia VPN,
     under the `cryoet` share's `data/` directory (the data root).
   - Starter templates live on the same share at `scratch/templates/`
     (`scratch` is a checkout of this repo).
   - Data-root tree (block #1): the two top-level arms and how the arm is the
     source of truth for `data_source` (and, for simulation, `dataset_type`).
     These are **derived from directory placement, never authored**.

2. **Adding an experimental dataset**
   - Points to `scratch/templates/sample_id_experimental/` + a **Download
     template** button (zip).
   - Experimental tree (block #2) as a file tree.
   - Inline links from the `sample.toml` / `acquisition.toml` nodes to the
     **Sample** and **Acquisition** `/author` tabs.

3. **Adding an MD simulation dataset**
   - Points to `scratch/templates/sample_id_simulation/` + a **Download
     template** button (zip).
   - Simulation tree (block #3) as a file tree.
   - Inline links from the `sample.toml` / `md_run.toml` / `acquisition.toml`
     nodes to the **Sample**, **MD run**, and **Acquisition** `/author` tabs.

4. **Append to the processing log as outputs are produced**
   - Each `acquisition.toml` grows over time. Record the raw reconstruction
     once in `[raw_tomogram]`; append a new `[[post_processed_tomogram]]` or
     `[[annotation]]` block for each new output (denoised version,
     segmentation, STA result, …).
   - Rules: never delete or modify an existing tomogram/annotation entry
     (reprocessing makes a new entry with a new id at the bottom of the file);
     the `id` must match a folder name under `TiltSeries/`,
     `Reconstructions/Tomograms/`, or `Reconstructions/Annotations/`; use
     `derived_from` and `target_tomogram` to record lineage.

## Tree component

`@mui/x-tree-view@^7` `RichTreeView` (v7 pairs with the frontend's MUI v6;
`^9` requires MUI v7/v9 — see Dependencies). Each tree is a static nested-data
array (`{ id, label, comment?, kind: 'dir' | 'file', href? }`); a custom item
slot renders a folder/file icon, the name, and the trailing `# comment` in
muted text. Trees are default-expanded and read-only (no selection). Nodes
with `href` render their label as a link to the relevant `/author` tab.

Rationale: the trees are ~20 lines deep each; a data array is far less verbose
to author and maintain than hand-written nested `<TreeItem>` JSX.

## Navigation

Add `{ to: "/data-organization", label: "Data organization" }` as the **first**
entry in `DATA_MANAGEMENT_LINKS` in `frontend/src/components/Header.tsx`. That
array feeds both the desktop dropdown and the mobile accordion, so both update
from the one change.

## Template download

The two starter template directories are zipped and served as static files.

- **Generator**: a Python script beside `src/schema/sync_templates.py` (which
  already owns template tooling and knows the paths) walks
  `templates/sample_id_experimental/` and `templates/sample_id_simulation/`
  and writes `frontend/public/templates/{name}.zip`. Zips are **deterministic**
  (entries sorted, fixed `date_time`, fixed external attrs) so a byte-compare
  is stable across runs. Empty skeleton dirs (`Frames/`, `Gains/`, …) are
  included as directory entries.
- **Drift guard**: a `--check` mode, wired into
  `tests/test_repo_consistency.py` (same pattern as the existing
  `sync_templates --check`), regenerates the zips in memory and byte-compares
  against the committed files; drift fails the test suite.
- **Serving**: `frontend/public/` is served at web root and is inside the
  frontend Docker build context, so the button is a plain
  `<a href="/templates/sample_id_experimental.zip" download>` — no API or
  build-context changes.

Tradeoff: two small binary zips are committed to the repo. Accepted because the
frontend Docker context is `frontend/` only and the API image doesn't ship
`templates/`, so neither can zip at build/runtime without a structural change;
the drift test keeps the committed zips honest.

## Dependencies

`@mui/x-tree-view@^7` must be installed in `frontend/` (currently absent there;
the stray `^9.9.0` pin in the *root* `package.json` is wrong for this project —
frontend is MUI v6 — and will be dropped). Install:
`cd frontend && npm install @mui/x-tree-view@^7`.

## Out of scope

- No search-param state on the route (static page).
- No API endpoint for templates (static files instead).
- No changes to the canonical templates or the schema.
