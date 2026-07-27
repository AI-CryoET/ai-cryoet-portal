# Utility scripts

Utilities for the ai-cryoet portal:

- **Data staging** — `reorg_facility_to_portal.py` and `relion_to_portal.py`
  stage Janelia cryoET facility data and RELION pipeline output into the portal
  ingestion layout.
- **Data migration** — `migrate_reconstruction_groups.py` moves an existing
  data root from the flat `Reconstructions/{Tomograms,Annotations}/{id}/`
  layout to the 3D-alignment-grouped one.
- **Frontend icons** — `icon/` regenerates the snowflake app icon, navbar logo,
  and favicons used by the frontend.

## `reorg_facility_to_portal.py`

Reorganizes a flat folder of facility microscope output into the experimental
sample-directory template the portal expects:

```
{DEST}/{sample_id}/
    sample.toml
    {acquisition_id}/
        acquisition.toml
        Alignments/ …
        Frames/      <- all .eer frames + the (combined) <acq>.mdoc
        Gains/       <- the shared *.gain
        Reconstructions/ …
        TiltSeries/  <- <acq>.mrc (Tomo5 only)
```

### What it does automatically

- **Detects the acquisition style** from the folder contents:
  - **Tomo5** — series-level `*.mdoc` + initial-tilt-series `*.mrc` (typically
    Gouaux-lab samples).
  - **SerialEM** — per-frame `*.eer.mdoc` files (typically Rosen-lab samples).
    The per-frame mdocs are combined into one series-level `<acq>.mdoc`.

  The lab is a *convention*, not the identifier — the script keys off the
  acquisition style and lets you confirm or override the lab.

- **Populates `lab_name` in `sample.toml`.** The detected style implies a lab
  (Tomo5 → `gouaux`, SerialEM → `rosen`); you're prompted to accept or change
  it before it's written. Pass `--lab-name` to set it non-interactively.

### Placement modes — read this first

Frames are large (a single Tomo5 session is ~650 GB), so the script never
duplicates data unless you ask it to. Choose how files land in the layout:

| Flag         | What it does                                  | Speed   | Extra disk | Source        |
|--------------|-----------------------------------------------|---------|-----------|---------------|
| `--symlink`  | **(default)** symlink everything into place   | instant | none      | preserved     |
| `--move`     | relocate frames out of the source             | instant\* | none    | **consumed**  |
| `--copy`     | duplicate every byte                          | slow    | full size | preserved     |
| `--hardlink` | inode link (same filesystem only)             | instant\* | none    | preserved     |

\* instant only when source and destination are on the same filesystem.

Notes:
- `reflink`/copy-on-write is **not** available — the storage is NFS.
- In `--move` mode the shared gain reference is copied (it can't be moved into
  every acquisition); in link modes it's linked.
- Files the script *generates* (the combined SerialEM mdoc, `sample.toml`) are
  always real files, never links — so a symlink test still produces faithful
  metadata.

### Recommended workflow

1. **Dry run** — see exactly what will happen, touch nothing:
   ```bash
   ./reorg_facility_to_portal.py SOURCE_DIR --dry-run
   ```

2. **Symlink test (default)** — stage the full layout instantly with no extra
   disk, then inspect it (directory structure, frame grouping, the combined
   mdoc, rendered `sample.toml`):
   ```bash
   ./reorg_facility_to_portal.py SOURCE_DIR
   ```
   Symlinks make the staged tree obviously a set of pointers and trivial to
   throw away. When you're done looking, delete it:
   ```bash
   rm -rf {DEST}/{sample_id}
   ```

3. **Real run** — once the layout looks right, do it for real. Use `--move` to
   relocate the data out of the source (instant, frees the source), or `--copy`
   to leave the source untouched at the cost of duplicating every byte:
   ```bash
   ./reorg_facility_to_portal.py SOURCE_DIR --move
   # or, to keep the originals:
   ./reorg_facility_to_portal.py SOURCE_DIR --copy
   ```

### Options

| Option                 | Purpose                                                        |
|------------------------|----------------------------------------------------------------|
| `--dry-run`            | Print planned actions; change nothing.                         |
| `--sample-id ID`       | Output sample id (default: source folder name).                |
| `--style {auto,tomo5,serialem}` | Force the acquisition style (default: auto-detect).   |
| `--lab-name {gouaux,rosen,villa}` | Set `lab_name` and skip the confirmation prompt.   |
| `--dest DIR`           | Destination root for new sample folders.                       |
| `--template DIR`       | Sample-dir template to lay down.                               |
| `--symlink / --copy / --move / --hardlink` | Placement mode (default `--symlink`).      |

See `./reorg_facility_to_portal.py --help` for the full list and current
defaults.

---

## `relion_to_portal.py`

Maps a completed **RELION-5 tomography pipeline** directory into the same portal
sample layout. Where `reorg_facility_to_portal.py` ingests *raw facility output*,
this script ingests the *processed results* of a RELION project — tilt-series
alignments, reconstructions, and denoised tomograms — alongside the raw movies.

Jobs are located by their canonical `_rlnJobTypeLabel` (read from each
`jobNNN/job.star`), not by the arbitrary `jobNNN` number, so reruns and renamed
jobs route correctly. When several jobs share a family, the highest-numbered
successful one (with `RELION_JOB_EXIT_SUCCESS`) wins.

### Routing

| RELION job family             | Portal destination                                         |
|-------------------------------|------------------------------------------------------------|
| `relion.importtomo`           | `Frames/` (raw movies + mdoc + shared gain)                |
| `relion.aligntiltseries`      | split: `<acq>.mrc` + `<acq>.rawtlt` → `TiltSeries/`; `*.aln` + `*.com` → `Alignments/` |
| `relion.reconstructtomograms` | `Reconstructions/Tomograms/reconstruct_halves/`            |
| `relion.denoisetomo`          | `Reconstructions/Tomograms/denoised/`                      |
| `relion.motioncorr`           | skipped (regenerable motion-corrected frames)              |
| `relion.ctffind`              | skipped (CTF metadata only)                                |
| `relion.excludetilts`         | skipped (tilt-selection star only)                         |

Derived/QC files inside routed jobs (e.g. `_aligned.mrc`, `_ctf.mrc`, `*.eps`,
`*.log`) are intentionally left behind.

### Placement modes

Like the facility script, files are placed by `--symlink` / `--copy` / `--move`
(mutually exclusive), defaulting to `--symlink`. **One difference to note:**

- It is a **dry run by default** — even with a placement mode chosen, it prints
  the plan and writes nothing until you pass `--apply`.

### Recommended workflow

1. **Dry run** (the default) — inspect the discovered jobs and the routing plan:
   ```bash
   ./relion_to_portal.py PIPELINE_DIR TARGET_SAMPLE_DIR
   ```

2. **Symlink test (default)** — stage the layout instantly to inspect it, then
   `rm -rf`:
   ```bash
   ./relion_to_portal.py PIPELINE_DIR TARGET_SAMPLE_DIR --apply
   ```

3. **Real run** — copy (preserves the pipeline) or move (consumes it):
   ```bash
   ./relion_to_portal.py PIPELINE_DIR TARGET_SAMPLE_DIR --apply --copy
   ```

### Options

| Option            | Purpose                                                            |
|-------------------|--------------------------------------------------------------------|
| `--apply`         | Actually perform the action (without it, dry run).                 |
| `--symlink / --copy / --move` | Placement action (default `--symlink`).                |
| `--manifest CSV`  | Write a per-file routed-vs-unrouted inventory (with sizes) to CSV. |

The `--manifest` option is useful for auditing exactly which pipeline files were
routed where and which were left behind (and why).

See `./relion_to_portal.py --help` for details.

---

## `icon/` — frontend icon generators

Scripts that regenerate the AI+CryoET snowflake icons used by the frontend (the
navbar logo and the browser favicon). The design is a snowflake / neural-network
hybrid in two colors: petrol `#145266` (background) and icy blue `#a8d4f0`
(nodes/branches) — the same palette the MUI theme is derived from.

| Script                     | Output                                                                 |
|----------------------------|------------------------------------------------------------------------|
| `create_ai_cryoet_svg.py`  | `frontend/public/favicon.svg` (petrol tile) and `frontend/src/assets/snowflake-logo.svg` (transparent, for the navbar). Written straight into the frontend. |
| `create_ai_cryoet_icon.py` | The original raster renders (`ai_cryoet_snowflake_*.png`, written to the current directory). Its 1024px output is the source for the `.ico` / `apple-touch` fallbacks. |

### Regenerating the frontend icons

```bash
# 1. Vector assets — written directly into the frontend:
python utils/icon/create_ai_cryoet_svg.py

# 2. Raster fallbacks — render the source PNG, then derive the .ico + apple-touch.
#    Needs Pillow (`pip install Pillow`) for the render and ImageMagick for convert:
cd utils/icon
python create_ai_cryoet_icon.py            # produces ai_cryoet_snowflake_1024.png (+512, +132)
convert ai_cryoet_snowflake_1024.png -define icon:auto-resize=16,32,48,64 \
    ../../frontend/public/favicon.ico
convert ai_cryoet_snowflake_1024.png -resize 180x180 \
    ../../frontend/public/apple-touch-icon.png
rm ai_cryoet_snowflake_*.png               # intermediates; not committed
```

The `<link>` tags that reference these live in `frontend/src/routes/__root.tsx`;
the navbar logo is imported in `frontend/src/components/Header.tsx`.

## `migrate_reconstruction_groups.py`

One-shot migration to the 3D-alignment-grouped reconstruction layout. For each
acquisition it moves

```
Reconstructions/Tomograms/{tomogram_id}/<file>
Reconstructions/Annotations/{annotation_id}/<file>
```

to

```
Reconstructions/{reconstruction_alignment_id}/Tomograms/{tomogram_id}.<ext>
Reconstructions/{reconstruction_alignment_id}/Annotations/{annotation_id}.<ext>
Reconstructions/{reconstruction_alignment_id}/Alignment/
```

and splits the acquisition.toml processing log into one `reconstruction.toml`
per group (dropping the removed `tilt_series_id` / `target_tomogram` fields and
setting `raw_tomogram.derived_from` to the acquisition's tilt-series id).

The group id comes from the acquisition's single `[[tilt_series]]` id — the only
unambiguous choice available from the old data. An acquisition with zero or
several tilt series has no such id, so each `{id}/` folder becomes its own group
instead. A tomogram and an annotation sharing a name always split into their own
group: that pairing is itself evidence of a distinct reconstruction attempt.

Dry-run by default; `--apply` performs the moves and writes the files. Re-running
after an apply is a no-op. Anything ambiguous (two files with the same extension
in one `{id}/` folder, a destination-name collision, a loose file directly under
`Tomograms/`) is reported to stderr and left in place.

```bash
./utils/migrate_reconstruction_groups.py --root /groups/cryoet/cryoet/data
./utils/migrate_reconstruction_groups.py --root /groups/cryoet/cryoet/data --apply
```
