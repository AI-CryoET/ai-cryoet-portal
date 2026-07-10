# Data organization & metadata

This document describes the on-disk layout and TOML metadata scheme for the CryoET + AI project. It is the authoring guide for researchers and the contract that the catalog scanner (`catalog`) reads against.

The central design goal is answering one question across both the experimental and simulation arms of the project: **which conditions have we covered, and which still need cryoET imaging, simulation, or both?**

> **Status: draft / proposed.** Fields, controlled vocabularies, and directory conventions are expected to evolve as researchers start authoring metadata against it.

---

## Quick start: Researcher workflow for creating a new sample directory and adding metadata

### 0. (Optional) Set up VSCode for live TOML validation

Authoring TOML in **VSCode** with the [Even Better TOML](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml) extension gives you in-editor type checking, enum suggestions, and field hints as you fill in the templates. The `#:schema` directive at the top of each template points the extension at `src/schema/schema.json` (for `sample.toml`) and `src/schema/acquisition.schema.json` (for `acquisition.toml`).

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

Each `acquisition.toml` grows over time. Record the raw reconstruction once in `[raw_tomogram]`; for each new output — a denoised version, a segmentation, an STA result — append a new `[[post_processed_tomogram]]` or `[[annotation]]` entry to the relevant acquisition's file.

**Rules:**
- Do **not** delete or modify a tomogram or annotation entry once added. Reprocessing produces a **new** entry with a new `id`, placed at the bottom of the file.
- A tilt-series `id` must match a folder name under `TiltSeries/`. A tomogram or annotation `id` must match a **file name without extension** under `Reconstructions/{tilt_series_id}/Tomograms/` and `.../Annotations/` (experimental) or the flat `Reconstructions/Tomograms/` / `Reconstructions/Annotations/` (simulation).
- Use `derived_from` and `target_tomogram` to record lineage (see above).

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
      acquisition.toml                       # per-acquisition params + processing log
      Frames/                                # raw movie frames (.eer / .tiff) + .mdoc
      Gains/                                 # gain reference
      TiltSeries/
        {tilt_series_id}/                    # one subfolder per tilt series (raw and/or aligned)
          stack/                             # .mrc projection stack (+ .zarr / .rawtlt); MAY be empty
          alignment/                         # MAY be empty if this is the raw tilt series 
            alignment.json                   # affine matrix + interpolation recipe (or any other alignment data)
      Reconstructions/
        {tilt_series_id}/                  # grouped by the aligned tilt series that produced them
          Tomograms/
            {tomogram_id}.mrc              # id = file name without extension
            {tomogram_id}.zarr
          Annotations/
            {annotation_id}.star          # id = file name without extension
            {annotation_id}.mrc / .zarr
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
          Tomograms/
            {tomogram_id}.mrc              # id = file name without extension
            {tomogram_id}.zarr
          Annotations/
            {annotation_id}.star
            {annotation_id}.mrc / .zarr
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

- **Two metadata files per sample.** Sample-level conditions live in `sample.toml` at the sample root. Per-acquisition parameters and the processing log live in `{acquisition}/acquisition.toml`. Fields derivable from MDOC files and file headers are authored in neither file; the ingest pipeline will read them directly.
- **Reconstruction outputs are grouped under the aligned tilt series that produced them** (`Reconstructions/{tilt_series_id}/`), and each tomogram or annotation is a **file whose stem is its id** — e.g. `bp_3dctf_bin4.mrc` has id `bp_3dctf_bin4`. Distinct processing versions get distinct file stems, so collisions are avoided by the id-as-filename within a tilt-series group. Simulation omits the tilt-series level (there is no tilt series), placing files directly under a flat `Reconstructions/Tomograms/` and `Reconstructions/Annotations/`.
- **No `VoxelSpacing{N}/` subfolder.** Voxel spacing in Ångström is not encoded in the path or authored in `acquisition.toml`; the catalog scanner derives it (`voxel_size`) directly from each reconstruction's MRC header (`voxel_size.x`). Keeping voxel info out of the path and the TOML avoids duplicating information that already lives in the file itself.

Simulation data uses a parallel structure with domain-appropriate folder names. Both share the same schema, which is what makes cross-comparison possible.

### Example: mapping Gouaux lab data to this structure

This experimental sample lives under the `Experimental/` top-level arm:

```
Experimental/
gouauxlab_20250418_AMmilled29-2/             # sample identity = directory name
  sample.toml                                # sample-level conditions
  Position_86/                               # acquisition identity = directory name
    acquisition.toml                         # per-acquisition params + processing log
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
      ts_aligned/                            # grouped by the tilt series that produced them
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
  Position_87/
    acquisition.toml
    Frames/
    ...
```

Changes from the current `annotation_HHMI_reorg` layout:

1. Move the tomogram files under `Reconstructions/{tilt_series_id}/Tomograms/` and name each file's stem for its id — `*_BP_3DCTF_BIN4.mrc` → `bp_3dctf_bin4.mrc`, `*_BP_3DCTF_BIN4_ddw.mrc` → `bp_3dctf_bin4_ddw.mrc` (a tomogram's `.mrc` and `.zarr` share the stem).
2. Move the annotation files under `Reconstructions/{tilt_series_id}/Annotations/` and name each file's stem to match its id (schema rule: annotation `id` = file name without extension) — e.g. the star file becomes `activezone_1.star`.
3. Add `sample.toml` at the sample level.
4. Add `acquisition.toml` in each acquisition directory.
5. Create `TiltSeries/{tilt_series_id}/{stack,alignment}/` (pending `.eer` conversion). Multiple tilt series per acquisition — e.g. one raw and one aligned — are an expected, first-class case.

---

## Metadata files

### `sample.toml` — sample-level conditions

One file per sample, placed at the root of the sample directory. Contains only what was imaged or simulated — not how. The sample directory name *is* the sample's identity, so `sample.id` is omitted from the file.

### `acquisition.toml` — per-acquisition parameters + processing log

One file per acquisition, placed at the root of each acquisition directory. It contains:

1. Researcher-authored imaging parameters not available from MDOC files (nominal resolution, nominal tilt spacing, target defocus range, energy filter model, phase plate, microscope model, imaging `facility`).
2. An **acquistion quality score** (`acquisition_quality`): an integer on a 1–5 rubric, the author's estimate of the acquistion quality (alignability + projection-image survival) — **5** Excellent (reconstructions could be publication-ready), **4** Good (useful for analysis such as subtomogram averaging or segmentation), **3** Medium (minor projection images discarded before reconstruction), **2** Marginal (major projection images discarded; usable only after heavy manual work), **1** Low (not alignable / not useful for analysis).
3. A **processing log**: a `[raw_tomogram]` table plus `[[post_processed_tomogram]]` and `[[annotation]]` entries appended over time as processing produces new outputs.

The acquisition directory name *is* the acquisition's identity, so `acquisition.id` is omitted from the file.

### `md_run.toml` — per-MD-run metadata (simulation samples only)

One file per MD run, placed at the root of each `MdRuns/{id}/` directory. The run directory name *is* the run's identity (`md_run_id`), so no `id` field is authored. It records the run's `seed`, `sample_time`, `timestep`, `computer`, `reference_contact`, and `force_field_version`. (This replaces the deprecated `[[md_run]]` blocks in `sample.toml`.)

---

## Schema rules

### Required fields

The only required authored field is `sample.project`. `sample.data_source` is set by the top-level directory (`Experimental/` vs `MdSimulation/`) and `dataset_type` by the `MdSimulation/<SubDir>/` directory — both are derived, not authored. All other fields are optional, allowing the schema to grow as researcher needs settle. The schema enums are `data_source`, `dataset_type`, `project`, and `lab_name` (authored under `[sample]`; one of `collepardo`, `gouaux`, `rosen`, `villa`) — all other fields are open text, with the potential to be tightened into enums later based on how researchers use them.

### Folder naming rules

Five names become primary keys in the portal database: the sample directory (`sample_id`), each acquisition directory (`acquisition_id`), and each tilt-series subfolder under `TiltSeries/` (`tilt_series_id`; the folder holds a `stack/` and an `alignment/` subdirectory) are **folder** names; each tomogram (`tomogram_id`) and each annotation (`annotation_id`) is a **file stem** — the file name without extension — under `Reconstructions/{tilt_series_id}/Tomograms/` and `.../Annotations/` (experimental) or the flat `Reconstructions/Tomograms/` / `Reconstructions/Annotations/` (simulation). The same strings may also be used in path expressions, URLs, and shell commands, so they are restricted to a conservative, cross-platform-safe allowlist.

A valid id must:

- be 1–128 characters long,
- contain only letters, numbers, `.`, `_`, and `-`,
- start and end with a letter or number,
- not contain `..`

### Extra fields

You may add any key-value pair to any section of `sample.toml` or `acquisition.toml` that is not yet in the schema. For example:

```toml
[chromatin]
substrate        = "synthetic"
linker_length_bp = 187.0
# Fields not yet in schema.py — captured here for later formalization:
ionic_strength_mM = 154.0
assembly_method   = "salt_dialysis"
```

Each Pydantic model is configured with `extra="allow"`, so unknown keys are preserved on the parsed record. The validator walks the tree after validation and reports every extra key as a **warning**, not an error — the file still passes and the extra fields survive into the ingest record. If a field proves useful, notify the SciComp team so it can be formally added to `schema.py` with the appropriate type and description.

### Lineage: `derived_from` and `target_tomogram`

`derived_from` records lineage across tomogram entries, and `target_tomogram` links annotations to the tomogram they were generated from. Both reference ids within the same `acquisition.toml`. (A tomogram's `tilt_series_id` is not authored here — it is derived from the enclosing `Reconstructions/{tilt_series_id}/` folder, or `None` for simulation; `target_tomogram` stays authored because a group folder holds many tomograms.)

```toml
# In .../Position_86/acquisition.toml

# Raw reconstruction (at most one [raw_tomogram] per acquisition)
[raw_tomogram]
id                     = "bp_3dctf_bin4"
derived_from           = []

# Denoised version derived from the raw
[[post_processed_tomogram]]
id                     = "bp_3dctf_bin4_ddw"
derived_from           = ["bp_3dctf_bin4"]

# Segmentation run on the denoised tomogram
[[annotation]]
id              = "membrain_seg_v10"
type            = "membrane_segmentation"
target_tomogram = "bp_3dctf_bin4_ddw"
```
