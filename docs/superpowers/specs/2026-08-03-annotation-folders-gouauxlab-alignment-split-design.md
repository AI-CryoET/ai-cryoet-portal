# Annotation id-folders + gouauxlab alignment split — design

Date: 2026-08-03
Branch: `feat/reconstruction-alignment-groups`

## Problem

The `Reconstructions/` reorg groups `Tomograms/` and `Annotations/` under a
`reconstruction_alignment_id` and **flattens** each side so every file sits
directly under `Tomograms/` or `Annotations/`, with the file stem as the id.

Two things break under flattening:

1. **Multi-file annotations collide.** One annotation is often several files,
   sometimes sharing an extension — e.g. `active_zonogram_0.png` +
   `active_zonogram_0_selected_aunps.png`, or `..._box.json` +
   `..._box_neuroglancer.json`. Two files can't both take the folder name, so
   the current migration either silently drops one (`.png` collision) or splits
   one annotation into several bogus entities. There is no way to keep an
   annotation's files together.

2. **gouauxlab acquisitions encode multiple 3D alignments in one
   `Reconstructions/`.** Folder-name suffixes (`_liza_az0`, `_liza_az2`,
   `_warp`, `_best_alignment`) mark *distinct alignments* that must become
   *separate* reconstruction groups. The current tilt-series-id grouping puts
   them all in one group.

This spec fixes both. It settles Theme 1 (identity/container) of
`docs/annotation-reorg-questions.md`. **Theme 2 (neuroglancer "open in viewer"
composition) is explicitly out of scope.**

## Ground truth (from the live data root)

- **Every `Annotations/{folder}/` is already exactly one annotation.** No folder
  holds multiple distinct annotations. `bounding_boxes/` looked like a "bag" in
  an earlier dry-run review, but those `Position_N` rows were *separate
  acquisitions* — each `bounding_boxes/` on disk holds one box (max distinct
  = 1). So **no stem-grouping / bag-splitting is ever needed.** The fix is to
  stop destroying the folders that already exist.
- **The largest annotation folder is 9 files, all one active-zone annotation**
  (`.star` + zonogram `.mrc`/`.npy`/`.png` + selected-aunps `.png` + two
  annotators' picks). Same-extension duplication within one annotation is
  normal.
- **gouauxlab alignment markers** (complete vocabulary, whole data root):

  | Folder suffix        | Count | Group id            |
  |----------------------|-------|---------------------|
  | `_liza_az{N}`        | 154   | `cryosnail_az{N}`   |
  | `_az{N}` (no `liza`) | 4     | `cryosnail_az{N}`   |
  | `_liza_az{N}_rerun`  | 3     | `cryosnail_az{N}`   |
  | `_warp`              | 12    | `warp`              |
  | `_best_alignment`    | 4     | `best_alignment`    |
  | *(none)* `membrain_seg_v{N}` | 47 | unmarked      |
  | *(none)* `bounding_boxes`    | 46 | unmarked      |

  `az{N}` is **non-contiguous** (2 acquisitions are `az0`+`az2`, no `az1`), some
  are `az1`-only or `az2`-only, and 4 are `warp`-only. `warp` and `az{N}` never
  mix within one acquisition. Unmarked `membrain_seg_v{N}` appears **only** in
  single-alignment acquisitions; `bounding_boxes` appears in both.

## Decisions (all confirmed with the project lead)

| # | Decision |
|---|----------|
| D1 | Single-file annotation → collapse to a bare `Annotations/{id}.ext` (mixed model, mirrors the tomogram single-leaf rule). Multi-file annotation → keep the folder. |
| D2 | No bag-splitting — a folder is always one annotation. |
| D3 | gouauxlab gets a **separate migration path** keyed on the `Experimental/gouauxlab_*` sample prefix. |
| D4 | Group naming: numbered alignments → `cryosnail_az{N}` (keep the researcher's `azN` convention, do **not** expand to `activezone{N}`). `warp` → `warp`. `best_alignment` → `best_alignment`. (Deliberate: only the numbered groups carry the `cryosnail_` prefix.) |
| D5 | Alignment number is **literal** from the suffix: `az0`+`az2` → `cryosnail_az0` + `cryosnail_az2` (gap at 1 preserved). |
| D6 | The **group** is set by the alignment marker, **not** the `activezone_M` index. `activezone_1_liza_az0` → `cryosnail_az0`. |
| D7 | Annotation folders are **relocated, not renamed** — the id keeps its full original name incl. the (now-redundant) alignment suffix. No stripping (avoids id churn + collisions). |
| D8 | In a **multi-alignment** acquisition, an **unmarked** folder (`bounding_boxes`) is ambiguous → left at `Reconstructions/Annotations/{id}/` + a warning. In a **single-alignment** acquisition, unmarked folders are unambiguous → moved into the one group. |
| D9 | `raw_tomogram.derived_from` still points at the tilt-series id — lineage is unchanged; only the group folder name now differs from it. |
| D10 | Nested tomogram variant subdirs (`ctf`/`even`/`odd`/`gaussian`) collapse to `{sub.name}_{original-filename}` (e.g. `ctf_s207_8.00Apx.mrc`), keeping provenance; applied everywhere tomograms flatten (Part C). |

## Target layout

```
Reconstructions/{group}/
  Tomograms/{tomogram_id}.<ext>          # unchanged: flatten + folder-name prefix
  Annotations/{annotation_id}/<files…>   # multi-file: folder preserved verbatim
  Annotations/{annotation_id}.<ext>      # single-file: collapsed to bare file
  Alignment/                             # created empty
```

Tomograms still flatten (they do **not** get folder-preserve); the two sides
are now deliberately asymmetric. The one tomogram-side change is nested-variant
filenames (Part C). Everything else about tomogram flattening is unchanged.

## Part A — Annotation folder-preserve (ALL acquisitions)

### A1. Migration (`utils/migrate_reconstruction_groups.py`)

Replace the annotation side of `_expand_entity_folder` / `_entity_files` usage
with a **folder-preserve** planner:

- **Single leaf, no non-junk subdirs** → collapse to `Annotations/{folder}.ext`
  (the existing single-leaf rule; the folder name becomes the id).
- **Otherwise** (2+ leaves, or a same-extension pair, or nested subdirs) →
  `mv` the whole folder into `{group}/Annotations/{folder}/` untouched.

Consequences that simplify the code:

- An annotation's id is **always** its folder name — in both branches. So the
  `[[annotation]]` block never splits: `ann_renames` becomes the identity map
  `{folder: [folder]}`, and `_expand_blocks` stops rewriting annotation blocks
  (it still runs for tomograms). Block-to-group routing still uses the
  folder→group membership already computed in `main()`.
- Tomogram planning (`_entity_files`, `_expand_entity_folder`,
  `prepend_folder=True`) is untouched.

**The folder-preserve rule must be wired into all THREE annotation code paths**,
not just `plan_reconstructions`: `_plan_folder_as_group` (used by
`plan_folder_groups` for the no-usable-tilt-series-id case) and
`plan_shared_name_group` also currently flatten annotations via
`_expand_entity_folder` and must route their annotation side through the same
folder-preserve planner. Example: `rosenlab_.../s207` has two active
`[[tilt_series]]` so `group_id_for` returns `None` and every folder becomes its
own group via `_plan_folder_as_group`; its `Annotations/Missalignment/`
(single file) must still collapse to a bare `Missalignment.star`, and a
multi-file annotation reached this way must be preserved as a folder. Tomogram
handling in these paths stays as-is apart from Part C.

### A2. Scanner (`src/catalog/discovery.py::iter_annotations`)

Currently reads every file directly under `Annotations/` as an entity (by
stem). Add: a **plain (non-`.zarr`) subdir** is one annotation —
`annotation_id` = folder name, `files` = all allowlisted files inside it
(recurse), while still reading bare files and `.zarr`/`.ome.zarr` dirs as
single-file annotations. `AnnotationLocation.files` already models the
multi-file case, so only the enumeration changes.

### A3. Validate CLI reader (`src/schema/layout.py::entity_ids_in_dir`)

The loader reconciles authored ids against disk via `entity_ids_in_dir`, which
today counts only files + `.zarr` dirs. Add an `include_dirs: bool = False`
param; **annotations pass `True`** so a plain subdir counts as one id (= folder
name); **tomograms stay file-only** (`False`). Update the two annotation call
sites in `loader.py` (`_reconstruction_ids_on_disk`, `_check_reconstruction_files`).

> The read side is **group-name agnostic** — `cryosnail_az0` / `warp` /
> `best_alignment` are just group id strings. No read-side change is needed for
> Part B; A2/A3 cover both parts.

## Part B — gouauxlab alignment split (migration only)

Keyed on the sample dir matching `Experimental/gouauxlab_*`. This **replaces**
the tilt-series-id grouping for gouauxlab; non-gouauxlab acquisitions keep the
generic path (+ Part A).

### B1. Marker → group id

For a `Tomograms/{folder}` or `Annotations/{folder}` name, in order:

1. `_(?:liza_)?az(\d+)` present (a trailing `_rerun` is allowed after) →
   `cryosnail_az{N}` (literal N).
2. else `_warp` token → `warp`.
3. else `_best_alignment` token → `best_alignment`.
4. else → **unmarked** (`None`).

### B2. Assigning folders

Collect the set of distinct marked groups in the acquisition, then:

- **Single alignment** (exactly one distinct marker): move **every** folder —
  marked *and* unmarked — into that one group. (e.g. `az0`-only →
  `cryosnail_az0`; `warp`-only → `warp`, incl. the no-suffix
  `membrain_seg_v10`.)
- **Multiple alignments** (≥2 distinct markers): each **marked** folder → its
  own group; each **unmarked** folder (`bounding_boxes`) stays at
  `Reconstructions/{Tomograms,Annotations}/{id}/` + a warning.
- **No markers at all** (defensive; not present in current data): fall back to
  the generic tilt-series path.

Within each destination group, annotations follow Part A (single→bare,
multi→folder); tomograms flatten+prepend as today.

### B3. reconstruction.toml per group

One `reconstruction.toml` per `cryosnail_az{N}` / `warp` / `best_alignment`
group, with `reconstruction_alignment_id` implied by the folder name (not
authored). `raw_tomogram`/`post_processed_tomogram`/`annotation` blocks are
routed to the group whose folders produced their ids (existing
`_collect_group_blocks` machinery). `raw_tomogram.derived_from` = the
acquisition's tilt-series id (D9), obtained from `group_id_for` — decoupled
from the group folder name, which is the key change: today the migration uses
one value for both.

## Part C — Tomogram nested-variant filenames (ALL acquisitions)

A tomogram folder can hold nested variant subdirs (`ctf/`, `even/`, `odd/`,
`gaussian/`), each with one `.mrc`. Today the migration collapses these onto the
**subfolder name**, discarding the original filename
(`ctf/s207_8.00Apx.mrc` → `ctf.mrc`), so provenance is lost.

Change: prepend the subfolder name to the **original filename** instead —
`ctf/s207_8.00Apx.mrc` → `ctf_s207_8.00Apx.mrc`,
`gaussian/s207_gauss.mrc` → `gaussian_s207_gauss.mrc`.

This is a one-line change in `_expand_entity_folder`'s subdir branch
(`{prefix}{sub.name}{ext}` → `{prefix}{sub.name}_{entry.name}`). Because both
`plan_reconstructions` and `_plan_folder_as_group` / `plan_shared_name_group`
call that helper, it applies **everywhere tomograms flatten** (confirmed
decision), including the folder-as-group path `s207` hits. Top-level tomogram
files are unaffected: the tilt-series-group path still prepends the folder id
(`437e7da`), and the folder-as-group path still does not (the group dir already
carries the name). After Part A, `_expand_entity_folder` is tomogram-only, so
this does not touch annotations.

## Worked example — `gouauxlab_20260127_AMmilled50-3/Position_13_3`

Alignments present: `az0`, `az2`, `best_alignment` → **multi-alignment**, so
`bounding_boxes` (unmarked) stays + warns.

```
Reconstructions/
├── cryosnail_az0/Annotations/
│   ├── activezone_1_liza_az0/                 ← multi-file folder preserved
│   │     activezone_1.star, active_zonogram_1.mrc/.npy/.png,
│   │     active_zonogram_1_selected_aunps.png
│   └── membrain_seg_v10_liza_az0.mrc          ← single file → bare {folder}.ext
├── cryosnail_az2/Annotations/
│   ├── activezone_1_liza_az2/                 ← preserved
│   └── membrain_seg_v10_liza_az2.mrc          ← collapsed
├── best_alignment/Annotations/
│   ├── activezone_1_best_alignment/           ← preserved
│   └── membrain_seg_v10_best_alignment.mrc    ← collapsed
└── Annotations/
    └── bounding_boxes/                        ← unmoved + warning
          Position_13_3_active_zone_box.json, _neuroglancer.json, _neuroglancer.txt
```

Note D6/D7: `activezone_1_liza_az0` → group `cryosnail_az0` (marker `az0`, not
the `activezone_1` index), and the folder name is kept verbatim (the redundant
`_liza_az0` is not stripped).

Single-alignment counter-example — `Position_6` (only `az0`): everything,
including the unmarked `bounding_boxes/` and `membrain_seg_v10/`, moves into
`cryosnail_az0/`.

## Edge cases

- **`_rerun`** (`activezone_0_liza_az0_rerun`): marker still `az0` → same
  `cryosnail_az0` group, kept as a separate annotation folder alongside the
  non-rerun one (distinct folder names, no collision).
- **Leftover flat `Reconstructions/Annotations/`** holding a stayed
  `bounding_boxes/`: the scanner may read it as a stray empty group. Accepted;
  the warning surfaces it for manual filing (matches existing loose-file
  handling).
- **`Thumbs.db` / `.DS_Store` / `.gitkeep`**: ignored by the single-vs-multi
  test (an otherwise-single folder with a `Thumbs.db` still collapses); pruned
  by existing cleanup.
- **`.zarr` / `.ome.zarr` annotation**: still a single-file (store) annotation,
  id = stem — not treated as a preserve-folder.
- **Non-contiguous / non-zero az** (`az0`+`az2`, `az2`-only): literal N (D5) →
  `cryosnail_az2` with no renumbering.

## Files to change

| File | Change |
|------|--------|
| `utils/migrate_reconstruction_groups.py` | Annotation folder-preserve planner across all 3 paths (A1); gouauxlab marker→group path (B1–B3); nested-variant subdir naming `{sub.name}_{filename}` (C); decouple `derived_from` (tilt-series id) from group folder id. |
| `src/catalog/discovery.py` | `iter_annotations` reads plain subdirs as one annotation (A2). |
| `src/schema/layout.py` | `entity_ids_in_dir(..., include_dirs=False)`; annotations pass `True` (A3). |
| `src/schema/loader.py` | Two annotation call sites pass `include_dirs=True` (A3). |
| `tests/test_migrate_reconstruction_groups.py` | Folder-preserve, single→bare, gouauxlab split, ambiguous-bounding_boxes-warn, rerun, non-contiguous az. |
| `docs/data_organization.md` | Document the annotation folder layout + gouauxlab groups. |

## Out of scope

- Neuroglancer "open in viewer" layer composition (Theme 2 of
  `annotation-reorg-questions.md`).
- Renaming/normalizing annotation ids or stripping alignment suffixes (D7).
- Tomogram-side behavior beyond the nested-variant filename change (Part C):
  flattening, top-level prepend, and the tilt-series grouping are unchanged.
- Rosenlab loose `.catm.star` files under `Annotations/` — still warned, not
  handled here.

## Test plan

1. **Migration dry-run** on a copied subtree for `Position_13_3` (multi-align),
   `Position_6` (single `az0`), `HippWaffle_77` (`warp`), and a non-gouauxlab
   acquisition (`rosenlab_*/s207`, folder-as-group via 2 tilt series); assert the
   planned moves match the worked example, that `bounding_boxes` warns only in
   the multi-align case, and that s207's nested `ctf/even/odd/gaussian` land as
   `ctf_s207_8.00Apx.mrc` … (Part C).
2. **Idempotency**: a second `--apply` is a no-op (no moves left; existing
   `reconstruction.toml` not clobbered).
3. **Round-trip**: after `--apply`, `iter_annotations` yields one
   `AnnotationLocation` per preserved folder (all files grouped) and per bare
   collapsed file; `entity_ids_in_dir(..., include_dirs=True)` matches the
   authored `[[annotation]]` ids so the validate CLI reports no id mismatch.
4. **Extension-allowlist parity** between `layout.py` and the standalone
   migration script stays pinned (existing test).
