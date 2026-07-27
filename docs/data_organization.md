# Data organization & metadata

This document describes the on-disk layout and TOML metadata scheme for the CryoET + AI project. It is the authoring guide for researchers and the contract that the catalog scanner (`catalog`) reads against.

The central design goal is answering one question across both the experimental and simulation arms of the project: **which conditions have we covered, and which still need cryoET imaging, simulation, or both?**

> **Status: draft / proposed.** Fields, controlled vocabularies, and directory conventions are expected to evolve as researchers start authoring metadata against it.

---

## Quick start: Researcher workflow for creating a new sample directory and adding metadata

### 0. (Optional) Set up VSCode for live TOML validation

Authoring TOML in **VSCode** with the [Even Better TOML](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml) extension gives you in-editor type checking, enum suggestions, and field hints as you fill in the templates. The `#:schema` directive at the top of each template points the extension at `src/schema/schema.json` (for `sample.toml`), `src/schema/acquisition.schema.json` (for `acquisition.toml`), `src/schema/md_run.schema.json` (for `md_run.toml`), and `src/schema/reconstruction.schema.json` (for `reconstruction.toml`).

Skipping the editor setup is fine — `pixi run validate {sample_dir}` (step 5) catches the same errors at the end.

### 1. Lay out the sample directory

Copy the starter directory that matches your data arm — `templates/sample_id_experimental/` for experimental cryoET data or `templates/sample_id_simulation/` for MD + synthetic cryoET data — into the right top-level arm: experimental samples go under `Experimental/`, and simulation samples go under `MdSimulation/{Bulk|SingleMolecule|Slab}/` (the subdirectory you choose sets the sample's `dataset_type`). The starter directory contains empty directories to scaffold the correct directory structure. Then follow the naming instructions below.

Rename the top-level `sample_id_*` directory to the desired sample id.

```
gouauxlab_20250418_AMmilled29-2/
```

Inside, make a copy of `acquisition_id`. Then update one of the directories to the desired acquisition id for your first acquisition. Repeat this process every time you want to add a new acquisition. (For simulation samples, the `acquisition_id` template lives inside `SyntheticCryoET/`; copy and rename it there.)

```
gouauxlab_20250418_AMmilled29-2/
  Position_86/
  Position_87/
```

### 2. Fill out `{sample_id}/sample.toml`

- Complete as many fields marked `<FILL IN>` as you can. For now, the only required authored field is `sample.project` (`sample.data_source` is set by the directory the sample lives under, not authored).
- Delete the `[synapse]` block if your project is `chromatin`, or vice versa.
- Optionally, uncomment and complete the `[[aunp]]`, `[freezing]`, and `[milling]` blocks.

### 3. Fill out `{sample_id}/{acquisition_id}/acquisition.toml` in each acquisition directory

- Complete as many fields marked `<FILL IN>` as you can. For now, no fields are required.

### 4. Append to the processing log as outputs are produced

Each `Reconstructions/{reconstruction_alignment_id}/reconstruction.toml` grows over time. Record the raw reconstruction once in `[[raw_tomogram]]`; for each new output — a denoised version, a segmentation, an STA result — append a new `[[post_processed_tomogram]]` or `[[annotation]]` entry to the relevant group's file.

**Rules:**
- Do **not** delete or modify a tomogram or annotation entry once added. Reprocessing produces a **new** entry with a new `id`, placed at the bottom of the file.
- A tilt-series `id` must match a folder name under `TiltSeries/`. A reconstruction-alignment `id` must match a folder name under `Reconstructions/` (it is not authored inside `reconstruction.toml` — the folder name *is* the id). A tomogram or annotation `id` must match a **file name without extension** under that same `Reconstructions/{reconstruction_alignment_id}/Tomograms/` and `.../Annotations/`.
- Use `derived_from` to record lineage (see above); a raw tomogram's `derived_from` points at a `[[tilt_series]]` id back in the acquisition's `acquisition.toml` — a plain id, resolved across files by the validator.

> **Legacy layout.** Older acquisitions may still carry `[[raw_tomogram]]` / `[[post_processed_tomogram]]` / `[[annotation]]` blocks directly in `acquisition.toml` instead of a per-group `reconstruction.toml`. The loader still reads these for any group that has no `reconstruction.toml` of its own, but emits a deprecation warning — migrate them by moving each block into `Reconstructions/{reconstruction_alignment_id}/reconstruction.toml` (matched by tomogram/annotation file stem) and deleting it from `acquisition.toml`. This fallback will be removed in a future release.

#### Authoring `reconstruction.toml` from the portal

You don't have to hand-write `reconstruction.toml`. From an acquisition's page in the portal there is **one** link, labelled `Create updated reconstruction.toml (<group id>)`, naming the acquisition's first 3D-alignment group — it opens an authoring form pre-filled from that one group's current file. The other groups aren't missing a link each; instead, the form has a group selector at the top listing every 3D-alignment group in the acquisition, and switching it reloads the form for whichever group you pick — that selector, not the acquisition page, is how you reach the rest. Picking `New group…` (its first option) resets the form to author a group that doesn't exist on disk yet. `raw_tomogram.derived_from` is a dropdown populated from the tilt-series ids already recorded in the acquisition's `acquisition.toml`, so you don't have to retype them by hand. You can also seed the form by uploading an existing `reconstruction.toml`, or by entering a group id in the form's "Load from portal by id" field.

**The portal downloads the file; it does not save it to disk for you.** When you finish the form, your browser downloads the resulting `reconstruction.toml` — there is no path by which the portal writes into the data directory itself. The form shows a placement hint with the destination path (`{sample_id}/{acquisition_id}/Reconstructions/{reconstruction_alignment_id}/reconstruction.toml`); move the downloaded file there yourself, overwriting the group's existing file if it had one.

**The form never writes the group id into the file — do not add one.** As described above, `reconstruction_alignment_id` comes from the folder name, not from a field in the TOML, and the form respects that: it never emits an `id` under `[reconstruction_alignment]`. If you type one in anyway (e.g. by editing the downloaded file by hand, or pasting from another group's file), it is **silently ignored**: the loader overwrites it with the folder name before validating, so you get no error and no warning — the group is filed under the folder name regardless of what the `id` says. This is the easiest authoring mistake to make without noticing, and nothing in the pipeline will tell you that you made it.

### 5. Validate

The validate script checks `sample.toml` and every `acquisition.toml` under the sample directory and reports any fields that violate the schema. Validation also runs during database ingestion — see `docs/schema.md` for the full list of fields that will be stored, including those auto-derived from MDOCs, MRC headers, OME-Zarr metadata, and directory structure.

#### Option 1: With pixi

1. [Install pixi](https://pixi.prefix.dev/latest/installation/).
2. The first time you use pixi for this repo, run `pixi install` to install the environment.
3. Run the validation with this command:

```
pixi run validate {sample_dir}
```

#### Option 2: Without pixi

Alternatively, you can run the validator with any Python ≥3.11 — the only runtime dependencies are `pydantic` and `rapidfuzz`, both pure-Python.

For example, using Python's built-in `venv` module:

```bash
# from the repo root
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
python -m schema.validate {sample_dir}
```

`pip install -e .` reads the same dependency list pixi uses (`[project.dependencies]` in `pyproject.toml`).

[`uv`](https://docs.astral.sh/uv/) works as a drop-in for `pip`/`venv`.

---

## Directory structure

The data root has **two top-level arms**, and the arm a sample lives under is
the source of truth for its `data_source` (and, for simulation, its
`dataset_type`):

```
{data_root}/
  Experimental/                              # data_source = experimental
    {sample_id}/ ...
  MdSimulation/                              # data_source = simulation
    Bulk/            {sample_id}/ ...        # dataset_type = bulk
    SingleMolecule/  {sample_id}/ ...        # dataset_type = single_molecule
    Slab/            {sample_id}/ ...        # dataset_type = slab
```

`data_source` is derived from the top-level directory (`Experimental` vs
`MdSimulation`), and a simulation sample's `dataset_type` is derived from the
`MdSimulation/<SubDir>/` it sits under — **neither is authored in
`sample.toml`**. Any `data_source` left over in a legacy `sample.toml` is
simply overridden by the directory.

### CryoET (experimental) data — under `Experimental/`

```
Experimental/
  {sample_id}/                               # sample identity = directory name
    sample.toml                              # sample-level conditions
    {acquisition_id}/                        # acquisition identity = directory name
      acquisition.toml                       # per-acquisition params + tilt-series metadata
      Frames/                                # raw movie frames (.eer / .tiff) + .mdoc
      Gains/                                 # gain reference
      TiltSeries/
        {tilt_series_id}/                    # one subfolder per tilt series (raw and/or aligned)
          stack/                             # .mrc projection stack (+ .zarr / .rawtlt); MAY be empty
          alignment/                         # MAY be empty if this is the raw tilt series 
            alignment.json                   # affine matrix + interpolation recipe (or any other alignment data)
      Reconstructions/
        {reconstruction_alignment_id}/      # a 3D alignment group; id does NOT have to match any tilt_series_id
          reconstruction.toml               # 3D alignment params + processing log for this group
          Tomograms/
            {tomogram_id}.mrc              # id = file name without extension
            {tomogram_id}.zarr
          Annotations/
            {annotation_id}.star          # id = file name without extension
            {annotation_id}.mrc / .zarr
          Alignment/                       # 3D alignment metadata for this group; MAY be empty
            alignment.json
```

### MD simulation (sample) and associated synthetic cryoET (acquisitions) data — under `MdSimulation/<SubDir>/`

```
MdSimulation/{Bulk|SingleMolecule|Slab}/
  {sample_id}/
    sample.toml                              # sample-level conditions
    MdRuns/                                  # simulation only: one subfolder per MD run
      {md_run_id}/                           # the folder name IS the run's id
        md_run.toml                          # seed, sample_time, timestep, computer, …
        Trajectories/                        # raw simulation output
        Snapshots/                           # extracted conformations (frames)
    SyntheticCryoET/                         # wraps all synthetic-cryoET acquisitions for this sample
      {acquisition_id}/                      # synthetic cryoET from one md_run frame
        acquisition.toml                     # per-acquisition params + [md_source]
        TiltSeries/
          {tilt_series_id}/                  # one subfolder per tilt series
            stack/
            alignment/
        Reconstructions/
          {reconstruction_alignment_id}/    # a 3D alignment group; id does NOT have to match any tilt_series_id
            reconstruction.toml            # 3D alignment params + processing log for this group
            Tomograms/
              {tomogram_id}.mrc              # id = file name without extension
              {tomogram_id}.zarr
            Annotations/
              {annotation_id}.star
              {annotation_id}.mrc / .zarr
            Alignment/                       # 3D alignment metadata for this group; MAY be empty
              alignment.json
```

For simulation samples, the raw MD data lives under `MdRuns/{md_run_id}/` — one
subfolder per MD run. Each run is described by its own `MdRuns/{id}/md_run.toml`
file, and the **folder name is the run's identity** (`md_run_id`); there is no
`id` field authored in the file. Each acquisition is the synthetic cryoET
generated from a single frame of one run; its directory sits inside
`SyntheticCryoET/`, sibling to `MdRuns/`, and its `[md_source]` block records
which `md_run_id` and `frame` it came from. The `md_source.md_run_id` should
match an `MdRuns/{id}/` folder name; a dangling reference warns rather than
failing the acquisition. Both `MdRuns/{id}/md_run.toml` and `[md_source]` are
relevant only to simulation samples and are rejected on experimental samples.

The directory skeleton is adapted from the [CZI CryoET Data Portal](https://chanzuckerberg.github.io/cryoet-data-portal/stable/cryoet_data_portal_docsite_data.html) at the Sample > Acquisition > (Frames, Gains, TiltSeries, Reconstructions) level, with three deliberate departures:

- **Several metadata files per sample, split by scope.** Sample-level conditions live in `sample.toml` at the sample root. Per-acquisition imaging parameters and tilt-series metadata live in `{acquisition}/acquisition.toml`. The processing log — `[[raw_tomogram]]`, `[[post_processed_tomogram]]`, `[[annotation]]` — lives one level deeper, in each group's own `Reconstructions/{reconstruction_alignment_id}/reconstruction.toml` (see below). Fields derivable from MDOC files and file headers are authored in none of these files; the ingest pipeline will read them directly.
- **Reconstruction outputs are grouped by 3D alignment** (`Reconstructions/{reconstruction_alignment_id}/`), and each tomogram or annotation is a **file whose stem is its id** — e.g. `bp_3dctf_bin4.mrc` has id `bp_3dctf_bin4`. A `reconstruction_alignment_id` is its own identity — it does **not** have to match any `tilt_series_id`; a tomogram's tilt-series lineage is instead recorded on `[[raw_tomogram]]`'s `derived_from`. Distinct processing versions get distinct file stems, so collisions are avoided by the id-as-filename within a group. Both arms share this layout, differing only in the tilt-series level that sits alongside it (simulation may have none).
- **No `VoxelSpacing{N}/` subfolder.** Voxel spacing in Ångström is not encoded in the path or authored in `acquisition.toml`; the catalog scanner derives it (`voxel_size`) directly from each reconstruction's MRC header (`voxel_size.x`). Keeping voxel info out of the path and the TOML avoids duplicating information that already lives in the file itself.

Simulation data uses a parallel structure with domain-appropriate folder names. Both share the same schema, which is what makes cross-comparison possible.

### Example: mapping Gouaux lab data to this structure

This experimental sample lives under the `Experimental/` top-level arm:

```
Experimental/
gouauxlab_20250418_AMmilled29-2/             # sample identity = directory name
  sample.toml                                # sample-level conditions
  Position_86/                               # acquisition identity = directory name
    acquisition.toml                         # per-acquisition params + tilt-series metadata
    Frames/
      *.eer
      *.eer.mdoc                             # acquisition metadata lives here
    Gains/
      gain_reference.gain
    TiltSeries/                              # TO CREATE: from .eer conversion
      ts_raw/                                # raw, unaligned tilt series
        stack/
          *.mrc
          *.zarr
          *.rawtlt
        alignment/
      ts_aligned/                            # aligned tilt series (derived_from = "ts_raw")
        stack/
          *.mrc
        alignment/
          alignment.json                     # affine matrix + interpolation recipe
    Reconstructions/
      recon_1/                               # a 3D alignment group (derived_from "ts_aligned"; id is independent of it)
        reconstruction.toml                  # 3D alignment params + processing log for recon_1
        Tomograms/
          bp_3dctf_bin4.mrc                  # id = file stem "bp_3dctf_bin4"
          bp_3dctf_bin4.zarr
          bp_3dctf_bin4_ddw.mrc              # id = file stem "bp_3dctf_bin4_ddw"
          bp_3dctf_bin4_ddw.zarr
        Annotations/
          activezone_1.star                 # id = file stem "activezone_1"
          activezone_1.mrc
          activezone_1.zarr
          activezone_1_annotated.png
          membrain_seg_v10.mrc              # id = file stem "membrain_seg_v10"
          membrain_seg_v10.zarr
        Alignment/                           # 3D alignment metadata for this group
          alignment.json
  Position_87/
    acquisition.toml
    Frames/
    ...
```

Changes from the current `annotation_HHMI_reorg` layout:

1. Move the tomogram files under `Reconstructions/{reconstruction_alignment_id}/Tomograms/` and name each file's stem for its id — `*_BP_3DCTF_BIN4.mrc` → `bp_3dctf_bin4.mrc`, `*_BP_3DCTF_BIN4_ddw.mrc` → `bp_3dctf_bin4_ddw.mrc` (a tomogram's `.mrc` and `.zarr` share the stem).
2. Move the annotation files under `Reconstructions/{reconstruction_alignment_id}/Annotations/` and name each file's stem to match its id (schema rule: annotation `id` = file name without extension) — e.g. the star file becomes `activezone_1.star`.
3. Add `sample.toml` at the sample level.
4. Add `acquisition.toml` in each acquisition directory.
5. Create `TiltSeries/{tilt_series_id}/{stack,alignment}/` (pending `.eer` conversion). Multiple tilt series per acquisition — e.g. one raw and one aligned — are an expected, first-class case.
6. Create `Reconstructions/{reconstruction_alignment_id}/Alignment/` for the group's 3D alignment metadata, and add a `reconstruction.toml` alongside it to record the group's alignment params and processing log.

---

## Metadata files

### `sample.toml` — sample-level conditions

One file per sample, placed at the root of the sample directory. Contains only what was imaged or simulated — not how. The sample directory name *is* the sample's identity, so `sample.id` is omitted from the file.

### `acquisition.toml` — per-acquisition parameters + tilt-series metadata

One file per acquisition, placed at the root of each acquisition directory. It contains:

1. Researcher-authored imaging parameters not available from MDOC files (nominal resolution, nominal tilt spacing, target defocus range, energy filter model, phase plate, microscope model, imaging `facility`).
2. An **acquistion quality score** (`acquisition_quality`): an integer on a 1–5 rubric, the author's estimate of the acquistion quality (alignability + projection-image survival) — **5** Excellent (reconstructions could be publication-ready), **4** Good (useful for analysis such as subtomogram averaging or segmentation), **3** Medium (minor projection images discarded before reconstruction), **2** Marginal (major projection images discarded; usable only after heavy manual work), **1** Low (not alignable / not useful for analysis).
3. One `[[tilt_series]]` block per `TiltSeries/{tilt_series_id}/` folder.
4. For simulation samples only, the `[md_source]` block recording the MD run + frame this acquisition's synthetic data came from.

The acquisition directory name *is* the acquisition's identity, so `acquisition.id` is omitted from the file.

> **Legacy:** older acquisitions may still carry the processing log (`[[raw_tomogram]]`, `[[post_processed_tomogram]]`, `[[annotation]]`) directly in `acquisition.toml`. That layout is deprecated in favor of `reconstruction.toml` — see below.

### `reconstruction.toml` — per-reconstruction-group 3D alignment + processing log

One file per 3D alignment group, placed at the root of each `Reconstructions/{reconstruction_alignment_id}/` directory. The folder name *is* the group's identity (`reconstruction_alignment_id`), so no `id` field is authored — the loader injects it from the path at load time. It contains:

1. A `[reconstruction_alignment]` table with the group's 3D alignment parameters (`alignment_software`, `alignment_method`).
2. The **processing log** for this group: one `[[raw_tomogram]]` entry per raw reconstruction, plus `[[post_processed_tomogram]]` and `[[annotation]]` entries appended over time as processing produces new outputs. A tomogram or annotation's `id` must equal a file stem under this same folder's `Tomograms/` or `Annotations/`.

Cross-file references stay plain ids: a `[[raw_tomogram]]`'s `derived_from` names a `[[tilt_series]]` id back in the acquisition's `acquisition.toml`, and the validator resolves it across the two files (a dangling reference warns rather than failing the group).

**Dual-read / deprecation policy:** the catalog scanner and validator read `reconstruction.toml` when present. If a `Reconstructions/{id}/` group has no `reconstruction.toml`, they fall back to reading that group's processing-log blocks from the legacy location — `[[raw_tomogram]]` / `[[post_processed_tomogram]]` / `[[annotation]]` still embedded in `acquisition.toml` — and emit a **deprecation warning** asking researchers to migrate the blocks into the group's own `reconstruction.toml`. This fallback exists only to ease the transition and will be removed in a future release; new reconstructions should always get a `reconstruction.toml`.

### `md_run.toml` — per-MD-run metadata (simulation samples only)

One file per MD run, placed at the root of each `MdRuns/{id}/` directory. The run directory name *is* the run's identity (`md_run_id`), so no `id` field is authored. It records the run's `seed`, `sample_time`, `timestep`, `computer`, `reference_contact`, and `force_field_version`. (This replaces the deprecated `[[md_run]]` blocks in `sample.toml`.)

---

## Schema rules

### Required fields

The only required authored field is `sample.project`. `sample.data_source` is set by the top-level directory (`Experimental/` vs `MdSimulation/`) and `dataset_type` by the `MdSimulation/<SubDir>/` directory — both are derived, not authored. All other fields are optional, allowing the schema to grow as researcher needs settle. The schema enums are `data_source`, `dataset_type`, `project`, and `lab_name` (authored under `[sample]`; one of `collepardo`, `gouaux`, `rosen`, `villa`) — all other fields are open text, with the potential to be tightened into enums later based on how researchers use them.

### Folder naming rules

Six names become primary keys in the portal database: the sample directory (`sample_id`), each acquisition directory (`acquisition_id`), each tilt-series subfolder under `TiltSeries/` (`tilt_series_id`; the folder holds a `stack/` and an `alignment/` subdirectory), and each 3D-alignment subfolder under `Reconstructions/` (`reconstruction_alignment_id`; the folder holds a `Tomograms/`, an `Annotations/`, and an `Alignment/` subdirectory) are **folder** names; each tomogram (`tomogram_id`) and each annotation (`annotation_id`) is a **file stem** — the file name without extension — under `Reconstructions/{reconstruction_alignment_id}/Tomograms/` and `.../Annotations/`. The same strings may also be used in path expressions, URLs, and shell commands, so they are restricted to a conservative, cross-platform-safe allowlist.

A valid id must:

- be 1–128 characters long,
- contain only letters, numbers, `.`, `_`, and `-`,
- start and end with a letter or number,
- not contain `..`

### Ids are scoped to their alignment group

A `tomogram_id` or `annotation_id` is a file stem, unique only within its own `Reconstructions/{reconstruction_alignment_id}/` folder. Two groups in the same acquisition may each hold a `denoised.mrc`:

```
Position_86/Reconstructions/
├── recon_1/Tomograms/denoised.mrc     # ✓ distinct tomograms
└── recon_2/Tomograms/denoised.mrc     # ✓ same stem, different group
```

The portal keys both on `(sample_id, acquisition_id, reconstruction_alignment_id, tomogram_id)`, so each gets its own row, its own detail entry, and its own preview URL.

### Extra fields

You may add any key-value pair to any section of `sample.toml`, `acquisition.toml`, or `reconstruction.toml` that is not yet in the schema. For example:

```toml
[chromatin]
substrate        = "synthetic"
linker_length_bp = 187.0
# Fields not yet in schema.py — captured here for later formalization:
ionic_strength_mM = 154.0
assembly_method   = "salt_dialysis"
```

Each Pydantic model is configured with `extra="allow"`, so unknown keys are preserved on the parsed record. The validator walks the tree after validation and reports every extra key as a **warning**, not an error — the file still passes and the extra fields survive into the ingest record. If a field proves useful, notify the SciComp team so it can be formally added to `schema.py` with the appropriate type and description.

### Lineage: `derived_from`

`derived_from` records lineage. On `[[raw_tomogram]]` it is **text** — the `tilt_series_id` (a `[[tilt_series]]` entry back in the group's acquisition's `acquisition.toml`) the tomogram was reconstructed from. On `[[post_processed_tomogram]]` it is **list[text]** — the id(s) of the tomogram(s) it was derived from, each a raw or post-processed `tomogram_id` anywhere in the acquisition: in this same `reconstruction.toml` group, or in a sibling reconstruction group's `reconstruction.toml`. Both `[[raw_tomogram]].derived_from` and `[[post_processed_tomogram]].derived_from` are written as plain ids; the validator builds the `tomogram_id` namespace across all of the acquisition's `reconstruction.toml` files (and, for raw tomograms, the acquisition's `acquisition.toml`) and resolves references across files (a dangling reference warns rather than failing the group).

An annotation has no `target_tomogram` field — it belongs to the whole `Reconstructions/{reconstruction_alignment_id}/` group, since every tomogram in that group represents the same inferred biological structure.

```toml
# In .../Position_86/Reconstructions/recon_1/reconstruction.toml
# (the folder name "recon_1" IS the reconstruction_alignment_id — not repeated here)

# Raw reconstruction (one entry per raw_tomogram produced)
[[raw_tomogram]]
id                     = "bp_3dctf_bin4"
derived_from           = "ts_aligned"   # a [[tilt_series]] id in .../Position_86/acquisition.toml

# Denoised version derived from the raw
[[post_processed_tomogram]]
id                     = "bp_3dctf_bin4_ddw"
derived_from           = ["bp_3dctf_bin4"]

# Segmentation covering the whole 3D alignment group
[[annotation]]
id   = "membrain_seg_v10"
type = "membrane_segmentation"
```
