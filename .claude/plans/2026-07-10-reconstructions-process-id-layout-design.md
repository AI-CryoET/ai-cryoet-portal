# Design: Reconstructions grouped by tilt-series id

**Date:** 2026-07-10
**Status:** proposed (revised after layout correction + code review; pending final spec sign-off)

> **Revision note.** An earlier draft assumed each grouping folder (`{process_id}`)
> held exactly one tomogram and that `target_tomogram` could therefore become
> *derived* from the folder. That was wrong. The grouping folder is the aligned
> **tilt series** (`{tilt_series_id}`), it holds **multiple** tomograms, and
> tomograms/annotations are stored as **files** whose `id` is the filename stem.
> `target_tomogram` stays **authored**; the field the layout *does* make
> derivable is the tomogram's **`tilt_series_id`** (its enclosing folder name).
> This document reflects the corrected model.

## Problem

Today a reconstruction's tomograms and its annotations live in two flat sibling
trees, neither structurally tied to the aligned tilt series that produced them:

```
{acquisition}/Reconstructions/
  Tomograms/{tomogram_id}/     *.mrc *.zarr
  Annotations/{annotation_id}/ *
```

The only link from a tomogram to the aligned tilt series it was reconstructed
from is the authored `tilt_series_id` field; there is no on-disk grouping of a
tilt series' reconstruction outputs. Researchers want all tomograms
reconstructed from one aligned tilt series — and the annotations on them —
co-located under a single `Reconstructions/{tilt_series_id}/` folder.

## Target layout

`{tilt_series_id}` is an **existing aligned tilt series id**: it matches a
`TiltSeries/{ts_id}/` folder and a `[[tilt_series]]` block in
`acquisition.toml`. One tilt-series folder holds **multiple** tomograms.
Tomograms and annotations are stored as **files** (not folders); each entity's
`id` is the **filename stem** — the name before the extension. **Both arms** use
this flat-file, id=stem model; they differ only in nesting depth. The
**experimental** arm nests files under a `{tilt_series_id}/` grouping folder; the
**simulation** arm has no tilt series, so its files sit directly under
`Reconstructions/Tomograms/` and `Reconstructions/Annotations/` — one level
shallower.

Experimental arm (nested under the tilt series):

```
{acquisition}/Reconstructions/
  {tilt_series_id}/                  # == an aligned tilt_series_id
    Tomograms/
      {tomo1}.mrc   {tomo1}.zarr     # [raw_tomogram]/[[post_processed_tomogram]] id = "tomo1"
      {tomo2}.mrc   {tomo2}.zarr     # id = "tomo2"
    Annotations/
      {ann1}.star                    # [[annotation]] id = "ann1"
      {ann2}.mrc                     # id = "ann2"
```

Simulation arm (flat, no tilt-series level — under `MdSimulation/.../SyntheticCryoET/{acq}/`):

```
{acquisition}/Reconstructions/
  Tomograms/
    backprojection.mrc  backprojection.zarr   # id = "backprojection"
  Annotations/
    {ann1}.mrc                                 # id = "ann1" (no sim annotations today; layout ready)
```

A **tomogram** is the set of files under `Tomograms/` sharing a stem — its
`.mrc` and matching `.zarr`/`.ome.zarr`; an **annotation** is the set of files
under `Annotations/` sharing a stem. The **stem** is computed by stripping a
multi-suffix Zarr extension (`.zarr` / `.ome.zarr`, per
`discovery.ZARR_DIR_SUFFIXES`) or the single final suffix — **not** `Path.stem`,
which would leave `foo.ome.zarr` as `foo.ome` and split it from its `foo.mrc`.
Only `.mrc` / `.zarr` / `.ome.zarr` entries are grouped as tomograms (a
`.gitkeep` or stray file is ignored — an extension allowlist mirroring the
existing annotation one, `discovery.ANNOTATION_FILE_EXTENSIONS`).

Real example (`gouauxlab_20241211_HippWaffle/HippWaffle_49`):

```
Reconstructions/
  ts_001/                            # aligned tilt series id
    Tomograms/
      bp_3dctf_bin4.mrc      bp_3dctf_bin4.zarr        # [raw_tomogram] id = "bp_3dctf_bin4"
      bp_3dctf_bin4_ddw.mrc  bp_3dctf_bin4_ddw.zarr    # [[post_processed_tomogram]] id = "bp_3dctf_bin4_ddw"
    Annotations/
      activezone_1.star       # id = "activezone_1"
      membrain_seg_v10.mrc    # id = "membrain_seg_v10"
```

Both tomograms' authored `tilt_series_id` = `"ts_001"`, which equals the
enclosing `Reconstructions/{ts_id}/` folder name.

## What is authored vs. derived

The reorg is mostly structural — an `id` now binds to a file stem rather than a
folder name — but the grouping folder makes one field **derivable** that wasn't
before: the tomogram's `tilt_series_id` *is* the enclosing folder name.

| Field | Before | After |
|---|---|---|
| tomogram `id` (`[raw_tomogram]` / `[[post_processed_tomogram]]`) | authored == `Reconstructions/Tomograms/{id}/` folder name | authored == the tomogram **file stem** under `Reconstructions/[{ts_id}/]Tomograms/` (the `{ts_id}` level is experimental-only) |
| annotation `id` (`[[annotation]]`) | authored == `Reconstructions/Annotations/{id}/` folder name | authored == the annotation **file stem** under `Reconstructions/[{ts_id}/]Annotations/` |
| tomogram `tilt_series_id` | authored, references a `[[tilt_series]]` id | **experimental: derived** — injected from the enclosing `Reconstructions/{ts_id}/` folder by both the scanner and the `validate` CLI; dropped from the template and no longer an authored input on the form. **Simulation: `None`** (no `{ts_id}` folder) |
| annotation `target_tomogram` | authored | **authored — unchanged**; the tilt-series folder holds many tomograms so it can't identify one, the link stays in the TOML |

The Pydantic schema and DB are **unchanged**: `tilt_series_id` remains a stored
field on the tomogram models; it is now injected from the path (by both the
scanner and the `validate` CLI) instead of read from the TOML. The cross-ref
validator (tomogram `tilt_series_id` must reference a declared `[[tilt_series]]`
id) still applies and is satisfied by construction — injection is **gated on a
declared match** (undeclared `{ts_id}` folders inject nothing and warn; see
step 2), so it can never feed the validator an unmatched id. The authoring form
loses the tomogram `tilt_series_id` input (see step 4); `target_tomogram` on
annotations stays authored.

### Accepted: annotation↔tomogram stays non-structural

Because a tilt-series folder holds multiple tomograms and annotations sit flat
in that folder's `Annotations/`, this reorg makes only the **tomogram→tilt_series**
link structural (folder name == `tilt_series_id`). The **annotation→tomogram**
link is still carried solely by the authored `target_tomogram`. The cross-ref
validator (annotation `target_tomogram` must reference a tomogram id in the same
acquisition) still applies as it does today.

### Known limitation (accepted)

The annotation primary key stays `(sample_id, acquisition_id, annotation_id)`.
Nesting annotations under tilt-series folders makes it *physically* possible to
create the same `annotation_id` under two different `{tilt_series_id}` folders
in one acquisition; that would collide on the PK. This is caught by existing
validation and surfaced as a warning — annotation ids must remain unique within
an acquisition, as they are today.

The same now applies to **tomogram** ids. A file stem repeated under two
`{tilt_series_id}` folders (`ts_a/Tomograms/tomoX.mrc`,
`ts_b/Tomograms/tomoX.mrc`) yields one `tomogram_id` (`tomoX`) with two
candidate `tilt_series_id` values. The old flat `Tomograms/` guaranteed unique
folder names; the nested model does not. The assembler keys injection by
`tomogram_id`, so a duplicate would inject `tilt_series_id`/`mrc_path` twice —
last-write-wins by directory sort order. Tomogram ids must therefore also remain
unique within an acquisition; the assembler emits a duplicate-id warning and
skips the second injection rather than silently overwriting.

## Code changes (dependency order)

Both arms move to the flat-file, id=stem model; they differ only in nesting.
Discovery/loader/migration branch once on `data_source`: experimental nests under
`Reconstructions/{ts_id}/`, simulation stays one level shallower directly under
`Reconstructions/Tomograms|Annotations/` (no tilt series, so `tilt_series_id` is
`None`).

1. **`src/catalog/discovery.py`**
   - `AcquisitionLocation`: keep `reconstructions_dir = {acq}/Reconstructions` for
     both arms; the per-arm difference is only nesting depth (experimental adds a
     `{ts_id}/` level, simulation doesn't). **Delete the dead `SyntheticCryoET/`
     tomogram fallback** (`discovery.py:282-289`): drop the `synth_tomos` probe so
     `tomograms_dir` resolves solely from `Reconstructions/Tomograms/`. No real
     data uses the nested `{acq}/SyntheticCryoET/{id}/` container (verified: zero
     across `$CATALOG_DATA_ROOT`); only `test_validate_sample.py:511` creates it.
   - A **shared stem helper** (see Target layout) does the grouping for both arms:
     keep only `.mrc`/`.zarr`/`.ome.zarr` (tomograms) or the annotation extension
     allowlist; group by stem; yield one `*Location` per stem.
   - `iter_tomograms`: **experimental** — for each `Reconstructions/{ts_id}/Tomograms/`,
     yield one `TomogramLocation` per stem with `tomogram_id = stem`,
     `mrc_files`/`zarr_dirs` for that stem, `tilt_series_id = {ts_id}`.
     **Simulation** — group files directly under `Reconstructions/Tomograms/`,
     `tilt_series_id = None`.
   - `iter_annotations`: **experimental** — `Reconstructions/{ts_id}/Annotations/`,
     `tilt_series_id = {ts_id}`. **Simulation** — `Reconstructions/Annotations/`
     directly, `tilt_series_id = None`. **Build the simulation annotation path now**
     (explicitly requested) even though there is no sim annotation data yet
     (verified: 19 sim samples, zero annotations).
   - `TomogramLocation` / `AnnotationLocation`: add a nullable `tilt_series_id`
     field (`None` on the simulation arm).
   - `parse_targets_for_sample`: point tomogram mrc/zarr mtime targets at the new
     file locations (both arms).

2. **`src/schema/loader.py`** — the `validate` CLI path; it **must** derive
   `tilt_series_id` too, so `pixi run validate` and the scanner agree.
   - `_TOMOGRAM_PARENT_DIRS` / `_ANNOTATION_PARENT_DIRS`: now match a **file
     stem**, not a dir. A tomogram id matches a file stem under
     `Reconstructions/*/Tomograms/` (experimental) or `Reconstructions/Tomograms/`
     (simulation); an annotation id matches a file stem under
     `Reconstructions/*/Annotations/` (experimental) or `Reconstructions/Annotations/`
     (simulation). **Remove the `"SyntheticCryoET"` entry from
     `_TOMOGRAM_PARENT_DIRS`** — dead fallback, deleted in step 1.
   - `_has_matching_folder` / `_candidate_folder_names`: switch from "a *dir*
     named `{id}`" to "a *file stem* `{id}`" across the nested tilt-series folders
     (rename to reflect stems; reuse the shared stem helper). Fuzzy suggestions
     draw from on-disk file stems.
   - **Derive `tilt_series_id` in the loader — this is *new* machinery.** Today
     the loader has no tomogram→folder association: `_has_matching_folder` only
     answers yes/no, and tomogram `id` is authored, never injected. Add a lookup
     that finds each tomogram's enclosing `Reconstructions/{ts_id}/` folder and
     injects `tilt_series_id` before validation. **Experimental arm only** —
     simulation tomograms have no `{ts_id}` folder and keep `tilt_series_id = None`.
     **Gate the injection on a
     declared match:** inject only when the `{ts_id}` folder name equals a
     declared `[[tilt_series]]` id; otherwise leave `tilt_series_id = None` and
     warn (`undeclared reconstruction group`). If the TOML still carries an
     authored `tilt_series_id` (legacy / un-migrated), the derived value wins;
     warn on mismatch.
   - **Why the gate matters:** `AcquisitionFile._check_cross_refs`
     (`schema.py:447-451`) *raises* on a `tilt_series_id` with no matching
     `[[tilt_series]]`, and re-validation runs after injection (`loader.py:671`,
     `assembler.py:675`). Injecting an undeclared folder name would hard-fail the
     whole sample (`assembly_failed`, `record=None`) instead of warning — gating
     keeps the cross-ref satisfied by construction.

3. **`src/catalog/assembler.py`**
   - Set each tomogram's `tilt_series_id` from the discovered `TomogramLocation`,
     applying the **same declared-match gate** as the loader. Key injection by
     `tomogram_id` and **skip + warn on a duplicate** tomogram id (see Known
     limitation) so a repeated stem across two `{ts_id}` folders can't silently
     overwrite.
   - **No change to `target_tomogram` handling** — keep trusting the authored
     value. The `annotation_without_target_tomogram` warning stays reachable
     (target is authored and may be omitted); the `undeclared_annotation_folder`
     path is unchanged apart from the new nested location.

4. **`src/schema/form_fields.py` + frontend authoring form**
   - **Reclassify** (do not delete) the tomogram `tilt_series_id` field as
     *derived*: move it into the `_derived(...)` lists for `[raw_tomogram]` and
     `[[post_processed_tomogram]]` (`authored=False`), exactly as `mrc_path`/`path`
     are handled. Deleting the `FormField` would leave the model field
     unclassified and fail the completeness drift test
     (`tests/test_form_fields_drift.py:50`). The `formFields.ts` codegen and the
     authoring form follow automatically (parity test at
     `test_form_fields_drift.py:64`) — it drops from the authored inputs.
   - `target_tomogram` stays an authored `FormField` on the annotation section —
     unchanged. Frontend *display* of `tilt_series_id` (record still carries the
     value) is unaffected.

5. **`templates/`** — both arms lose the per-id folder level.
   - **Experimental:** replace
     `sample_id_experimental/acquisition_id/Reconstructions/Tomograms/tomogram_id/`
     and `.../Reconstructions/Annotations/annotation_id/` with
     `.../Reconstructions/tilt_series_id/Tomograms/.gitkeep` and
     `.../Reconstructions/tilt_series_id/Annotations/.gitkeep`.
   - **Simulation:** replace
     `sample_id_simulation/SyntheticCryoET/acquisition_id/Reconstructions/Tomograms/tomogram_id/`
     and `.../Reconstructions/Annotations/annotation_id/` with the flat
     `.../Reconstructions/Tomograms/.gitkeep` and
     `.../Reconstructions/Annotations/.gitkeep` (no tilt-series level).
   - `templates/acquisition.toml` (and the skeleton copies): update the `id`
     comments — tomogram `id` "MUST equal the tomogram file's name without
     extension under `Reconstructions/{tilt_series_id}/Tomograms/`"; annotation
     `id` likewise for `Annotations/`. **Drop the `tilt_series_id` line** from
     the `[raw_tomogram]` / `[[post_processed_tomogram]]` blocks (now derived)
     and replace it with a comment that the tomogram lives under
     `Reconstructions/{tilt_series_id}/` and inherits that id from the folder.
     Keep the `target_tomogram` line.

6. **`docs/data_organization.md`** — document the new layout and the
   authored-vs-derived table.

7. **Tests**
   - `tests/test_repo_consistency.py` (lines ~81-90): update expected template
     skeleton paths to the new layout.
   - `tests/test_id_validation.py`, `tests/test_validate_sample.py`,
     `tests/catalog/test_discovery.py`, `tests/catalog/test_assembler.py`,
     and `tests/catalog/fixtures/`: update inline
     `Reconstructions/Tomograms/{id}/` / `Reconstructions/Annotations/{id}/`
     (dirs) to the new `Reconstructions/{ts_id}/Tomograms/{id}.mrc` /
     `.../Annotations/{id}.*` (experimental) and the flat
     `Reconstructions/Tomograms/{id}.mrc` / `.../Annotations/{id}.*` (simulation).
   - Add discovery tests: two tomograms + two annotations under one `{ts_id}`
     folder (ids from file stems; `tilt_series_id` from the parent folder); a
     `foo.mrc` + `foo.ome.zarr` pair collapsing into **one** entity (guards the
     stem rule); a `.gitkeep`/stray file being ignored (extension allowlist); a
     duplicate stem across two `{ts_id}` folders producing the duplicate-id
     warning; and the **simulation** arm discovering flat
     `Reconstructions/Tomograms/{id}.mrc` files with `tilt_series_id=None` plus
     the new flat `Reconstructions/Annotations/` path. Assert
     `tests/test_form_fields_drift.py` stays green after the reclassify.
   - **Delete `test_tomogram_id_matched_under_synthetic_layout`**
     (`test_validate_sample.py:511`) — the `SyntheticCryoET` fallback it asserts
     is removed. Add the migration self-check below.

## Migration script (`utils/reorg_reconstructions.py`)

Follows the existing standalone-script style in `utils/`
(`reorg_facility_to_portal.py`). **Dry-run by default**; `--apply` performs the
moves. Operates on `$CATALOG_DATA_ROOT` (or a `--root` arg), across both arms.

Per acquisition, parse `acquisition.toml` for tomogram ids (+ each one's
authored `tilt_series_id`) and the `annotation_id → target_tomogram` map, then:

1. **Tomograms** — for each `Reconstructions/Tomograms/{tid}/`, collapse the
   folder to files named `{tid}.<ext>`; the destination depends on the arm:
   - *Experimental:* → `Reconstructions/{ts_id}/Tomograms/{tid}.<ext>`, where
     `ts_id` is the tomogram's authored `tilt_series_id`.
   - *Simulation:* → `Reconstructions/Tomograms/{tid}.<ext>` (up one level, no
     tilt-series folder). E.g. `Reconstructions/Tomograms/backprojection/<f>.mrc`
     → `Reconstructions/Tomograms/backprojection.mrc`.
   - Both: **rename each moved file to `{tid}.<ext>`** so the tomogram id (the
     folder name today) survives as the new file stem — otherwise it silently
     changes to the raw filename and breaks every `derived_from`,
     `target_tomogram`, and DB PK that references it. The raw+post `.mrc`/`.zarr`
     pair each carry the id stem. A folder holding multiple files that collide on
     `{tid}.<ext>` (e.g. two `.mrc` half-maps — `mrc_files` is already plural in
     discovery) → **block that tomogram's move and warn**.
2. **Annotations** — for each `Reconstructions/Annotations/{aid}/`, collapse to
   files named `{aid}.<ext>`:
   - *Experimental:* resolve the target tomogram's `tilt_series_id` and move to
     `Reconstructions/{ts_id}/Annotations/{aid}.<ext>`.
   - *Simulation:* → `Reconstructions/Annotations/{aid}.<ext>` (no tilt-series
     level; no sim annotation data exists today, but the migration handles it if
     present).
   - Same-extension collision within a folder → **block and warn** (can't
     collapse to one stem).
3. **Strip the now-derived `tilt_series_id`** line from each `[raw_tomogram]` /
   `[[post_processed_tomogram]]` block so migrated files match the new template
   (behind a flag; default on). Use a line-level regex edit (tomllib is
   read-only and the file is heavily commented); the `tilt_series_id =` key is
   unambiguous — `[[tilt_series]]` blocks use `id`, not `tilt_series_id`. Leave
   `target_tomogram` on annotations intact.
4. Remove the now-empty `Reconstructions/Tomograms/` and
   `Reconstructions/Annotations/` dirs; rewrite placeholder-only skeletons to
   the new empty skeleton.

**Warn-and-skip cases (never guess a destination):**
- **[Experimental] tomogram with no authored `tilt_series_id`** — including
  frames-only acquisitions with no `acquisition.toml` (nothing to read the id
  from) → cannot pick a `{ts_id}` folder → leave in place and warn (`ambiguous
  target tilt series`). (Simulation needs no `tilt_series_id` — it has no
  tilt-series level — so it's never skipped for this reason.)
- **Annotation whose `target_tomogram` is missing/ambiguous** → leave in place
  and warn. Never move to a guessed tomogram/tilt series.
- **Same-extension collision** on a tomogram or annotation folder (see steps
  1–2) → leave and warn.

Output:
- **Dry-run:** per-acquisition listing of planned `mv`s (old → new) plus every
  warning. No filesystem changes.
- **`--apply`:** performs the moves, then prints the same report with
  ✓/skipped status. Idempotent — re-running on migrated data is a no-op.

Moves use `os.rename`/`shutil.move` within the same filesystem. The script never
deletes real data — only empty scaffolding dirs after their contents have moved.

### Migration self-check

A small `test_reorg_reconstructions.py` (or `__main__` `demo()`): build a
synthetic experimental acquisition with two tomograms sharing one
`tilt_series_id` plus one targeted annotation and one untargetable annotation,
**and** a simulation acquisition whose tomogram must collapse to
`Reconstructions/Tomograms/{id}.mrc` (no `{ts_id}` level). Run the planner in
dry-run and assert the planned moves match each arm's layout, ids are preserved
via rename, and the untargetable annotation is left + warned.

## Out of scope

- No change to the Pydantic schema, the catalog DB schema, or Alembic migrations.
- **No `Alignments/` tree.** This reorg groups by the *existing* `tilt_series_id`;
  the 2026-06-18 decision to fold alignment into `TiltSeries/` and have tomograms
  reference `tilt_series_id` stands.
- `target_tomogram` stays authored; the annotation form and all frontend
  display are unchanged. Only the tomogram `tilt_series_id` input leaves the
  authoring form (now derived).
- **Simulation is reorganized too — but flat, without the tilt-series level.**
  Sim tomograms/annotations become files directly under `Reconstructions/Tomograms/`
  and `Reconstructions/Annotations/` (id = stem), collapsing today's per-id
  folders. No `{ts_id}` grouping and `tilt_series_id` stays `None` (sim has no
  tilt series). The dead `SyntheticCryoET/` tomogram fallback is **removed** (see
  step 1) — no real data used it. Both arms share the flat-file model;
  discovery/loader/migration branch once on `data_source` for the nesting level only.
- No change to `TiltSeries/`, `Frames/`, `Gains/`, MdRuns, or the simulation
  `GroundTruth/` tree.
