# Utility scripts

Utilities for the ai-cryoet portal:

- **Data staging** — `reorg_facility_to_portal.py` stages Janelia cryoET
  facility data into the portal ingestion layout.
- **Data migration** — `migrate_reconstruction_groups.py` moves an existing
  data root from the flat `Reconstructions/{Tomograms,Annotations}/{id}/`
  layout to the 3D-alignment-grouped one.
- **Local dev testing** — `repopulate_test_data.sh` refreshes the
  `scratch/data/` test tree from the real data root.
- **Frontend icons** — `icon/` regenerates the snowflake app icon, navbar logo,
  and favicons used by the frontend.
- **Archived** — `archive/` holds retired scripts kept for reference, currently
  `relion_to_portal.py` (see [Archived](#archived) below).

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

## Archived

Retired scripts kept under `archive/` for reference, not maintained.

### `archive/relion_to_portal.py`

Mapped a completed **RELION-5 tomography pipeline** directory (tilt-series
alignments, reconstructions, denoised tomograms, plus the raw movies) into the
portal sample layout — the processed-results counterpart to
`reorg_facility_to_portal.py`.

**Why it was archived:** there is no remaining RELION data to reorganize. It
also predates the 3D-alignment-grouped `Reconstructions/` layout — it still
writes the old flat `Reconstructions/Tomograms/{reconstruct_halves,denoised}/`
paths — so it would have to be rewritten for the current format
(`Reconstructions/{reconstruction_alignment_id}/…`; see
`migrate_reconstruction_groups.py`) before it could be used again. Moved to
`utils/archive/relion_to_portal.py` rather than deleted so that rewrite has a
starting point if RELION output ever needs staging.

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

A `{id}/` folder normally collapses onto its own name — every file in it is one
entity's artifacts, so `recon.mrc` + `recon.ome.zarr` become `{id}.mrc` +
`{id}.ome.zarr`. When two files share an extension that is impossible (one name,
two files), so the folder's contents are treated as **separate entities keeping
their own filenames**, and each stem becomes an id. The authored block for `{id}`
is rewritten into one block per resulting stem either way, so no declaration is
left dangling. Every such split is reported to stderr naming the ids it produced
— review them, because the ids change from the folder name to the file stems.

Dry-run by default; `--apply` performs the moves and writes the files. Re-running
after an apply is a no-op. What is still reported and left in place: a
destination-name collision, and a loose file directly under `Tomograms/` or
`Annotations/` (no `{id}/` folder says which group it belongs to).

```bash
./utils/migrate_reconstruction_groups.py --root /groups/cryoet/cryoet/data
./utils/migrate_reconstruction_groups.py --root /groups/cryoet/cryoet/data --apply
```

## `repopulate_test_data.sh`

Resets the local `scratch/data/` test tree to a fresh copy of a handful of
samples from the real data root — the fastest way to re-run the migration from a
clean slate. Hardlinks where the NFS allows it (so it costs almost no disk), but
gives every `.toml` its own inode, since the migration rewrites those in place
and a shared inode would corrupt the source data. Edit the `SAMPLES` array to
change the test set; `SRC`/`DEST` are hardcoded to the real data root and
`scratch/data/`.

```bash
./utils/repopulate_test_data.sh
```

Files owned by other users can't be deleted by `--delete`, so stale foreign
files may survive a reset — the script warns and keeps going.
