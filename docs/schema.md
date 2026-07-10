# Database Model: CryoET + AI Portal

This document enumerates every field that will be stored in the portal database, organized by entity (Sample → Acquisition → Tomogram → Annotation). For each field it lists the data type and the **authoritative source**:

| Source | What it means |
|---|---|
| `sample.toml` | Researcher-authored sample-level metadata — one file at the sample root. Field definitions live in `schema.py`. Section shown in parentheses. |
| `acquisition.toml` | Researcher-authored per-acquisition parameters and processing log (`[raw_tomogram]`, `[[post_processed_tomogram]]`, `[[annotation]]` entries) — one file in each acquisition directory. Section shown in parentheses. |
| `MDOC` | Parsed from `.mdoc` files in the `Frames/` directory by `ingest_mdoc.py`. |
| `.eer` / `.tiff` | Derived from frame file extension or EER header metadata. |
| `MRC header` | Read from the `.mrc` file header on ingest. |
| `OME-Zarr .zattrs` | Read from the multiscale metadata in `.ome.zarr` arrays. |
| `directory` | Implicit from the prescribed directory structure — sample dir name, acquisition dir name, tilt-series folder name, the tilt-series group folder (`Reconstructions/{tilt_series_id}/`), and the tomogram/annotation **file stem** (file name without extension). |
| `derived` | Computed on ingest from other DB fields (e.g., tilt range formatted string). |

Researcher-authored fields live in one of two files: sample-level metadata in `sample.toml` at the sample root, and per-acquisition parameters plus the processing log in `acquisition.toml` inside each acquisition directory. Both files are governed by `schema.py`; the section in parentheses identifies the TOML table (`[sample]`, `[chromatin]`, `[acquisition]`, `[raw_tomogram]`, `[[post_processed_tomogram]]`, etc.). Fields coming from any other source are **not** entered by researchers and are not duplicated in either TOML (no-duplication principle).

**Key annotations**: `(PK)` marks a **primary key** — the column that uniquely identifies each row in that table. `(FK)` marks a **foreign key** — a column whose value references the primary key of another table, used to link rows across entities (e.g., a tomogram's `acquisition_id` points back to its parent acquisition row).

---

## 1. Sample entity

One row per sample. Primary key: `sample_id` (the sample directory name).

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `sample_id` | text (PK) | `directory` | derived | Sample folder name. |
| `lab_name` | enum | `sample.toml` (`[sample]`) | researcher authored | `collepardo`, `gouaux`, `rosen`, or `villa` |
| `data_source` | enum | directory (top-level arm) | derived | `experimental` (under `Experimental/`) or `simulation` (under `MdSimulation/`). Not authored in `sample.toml`. |
| `project` | enum | `sample.toml` (`[sample]`) | researcher authored | `chromatin`, `synapse`, or `nanogold`. |
| `type` | text | `sample.toml` (`[sample]`) | researcher authored | e.g. `cellular` / `reconstituted`. |
| `cell_type` | text | `sample.toml` (`[sample]`) | researcher authored | Required when `type = cellular`. |
| `description` | text | `sample.toml` (`[sample]`) | researcher authored | Free text. |
| `path` | text | `directory` | derived | Absolute sample-directory path; surfaced for the UI's copy-path / open-in-file-browser buttons. Works even for samples with no acquisitions. |
| `renamed_from` | text | `sample.toml` (`[sample]`) | researcher authored | **Not stored in the DB.** Scan-time-only directive (§08c): names the prior `sample_id` this directory was renamed from, so the scanner records a rename event instead of a false deletion + fresh-add. Excluded from the ORM mirror; never served in any API response. |

### 1a. Chromatin sub-entity (one row per sample when `project = chromatin`)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `substrate` | text | `sample.toml` (`[chromatin]`) | researcher authored | e.g. `synthetic` / `native` / `n/a`. |
| `linker_length_bp` | float | `sample.toml` (`[chromatin]`) | researcher authored | Homogenous linker length. |
| `linker_pattern` | list[int] | `sample.toml` (`[chromatin]`) | researcher authored | Patterned linker lengths. |
| `linker_distribution` | text | `sample.toml` (`[chromatin]`) | researcher authored | Free-text distribution description. |
| `buffer` | text | `sample.toml` (`[chromatin]`) | researcher authored | Monovalent/divalent species + conc + additives. |
| `ptm` | text | `sample.toml` (`[chromatin]`) | researcher authored | |
| `histone_variants` | text | `sample.toml` (`[chromatin]`) | researcher authored | |
| `transcription_factors` | text | `sample.toml` (`[chromatin]`) | researcher authored | |
| `nucleosome_count` | integer | `sample.toml` (`[chromatin]`) | researcher authored | |
| `dna_length_bp` | integer | `sample.toml` (`[chromatin]`) | researcher authored | |
| `nucleosome_uM` | float | `sample.toml` (`[chromatin]`) | researcher authored | |
| `sequence_identity` | text | `sample.toml` (`[chromatin]`) | researcher authored | Native-substrate only. |
| `nucleosome_footprint` | list | `sample.toml` (`[chromatin]`) | researcher authored | Native-substrate only. |
| `linker_length_fraction` | float | `derived` | derived | `sequence_footprint − 1`; computed on ingest. |

### 1b. Label sub-entity (0..N per sample)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `label_target` | text | `sample.toml` (`[label]`) | researcher authored | |
| `aunp_type` | text | `sample.toml` (`[label]`) | researcher authored | |
| `aunp_size_nm` | float or list of floats | `sample.toml` (`[label]`) | researcher authored | |
| `conjugation` | text | `sample.toml` (`[label]`) | researcher authored | Fab / nanobody / chemical_tag / none. |
| `conjugation_target` | text | `sample.toml` (`[label]`) | researcher authored | e.g. GluA2. |
| `fluorophore` | text | `sample.toml` (`[label]`) | researcher authored | |
| `notes` | text | `sample.toml` (`[label]`) | researcher authored | |

### 1c. Fiducial AuNP (one per sample)

| Field | Type | Source | Source Type |
|---|---|---|---|
| `aunp_size_nm` | float or list of floats | `sample.toml` (`[fiducial]`) | researcher authored |
| `vendor` | text | `sample.toml` (`[fiducial]`) | researcher authored |
| `catalog_number` | text | `sample.toml` (`[fiducial]`) | researcher authored |
| `product_name` | text | `sample.toml` (`[fiducial]`) | researcher authored |
| `concentration_value` | float | `sample.toml` (`[fiducial]`) | researcher authored |
| `concentration_unit` | text | `sample.toml` (`[fiducial]`) | researcher authored |

### 1d. Freezing sub-entity (one per sample)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `grid_type` | text | `sample.toml` (`[freezing]`) | researcher authored | |
| `solution_type` | text | `sample.toml` (`[freezing]`) | researcher authored | |
| `cryoprotectant` | text | `sample.toml` (`[freezing]`) | researcher authored | |
| `method` | text | `sample.toml` (`[freezing]`) | researcher authored | `plunge_frozen` / `HPF`. |
| `planchette_size` | text | `sample.toml` (`[freezing]`) | researcher authored | HPF only. |
| `spacer_thickness` | text | `sample.toml` (`[freezing]`) | researcher authored | HPF only. |

### 1e. Milling sub-entity (one per sample)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `scheme` | text | `sample.toml` (`[milling]`) | researcher authored | |
| `date` | date | `sample.toml` (`[milling]`) | researcher authored | YYYY-MM-DD. |
| `quality` | text | `sample.toml` (`[milling]`) | researcher authored | |

### 1f. Simulation sub-entity (one row per sample when `data_source = simulation`)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `dataset_type` | enum | `directory` (`MdSimulation/<SubDir>/`) | derived | One of `bulk`, `single_molecule`, `slab` — derived from the `MdSimulation/{Bulk,SingleMolecule,Slab}/` subdirectory, **not** authored in `sample.toml`. |

### 1g. MD run sub-entity (0..N per sample; simulation data only)

`MdRuns/{id}/md_run.toml` — one file per molecular-dynamics run, where the run's folder name under `{sample_dir}/MdRuns/{id}` *is* its identity (the `id` field is not authored, matching the sample/acquisition convention). Each folder holds that run's trajectories and frames. Rejected on `experimental` samples.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `md_run_id` | text (PK) | `directory` | derived | Run folder name under `MdRuns/` — the source of identity. |
| `seed` | integer | `MdRuns/{id}/md_run.toml` | researcher authored | RNG seed for the run. |
| `sample_time` | float | `MdRuns/{id}/md_run.toml` | researcher authored | Total simulated time. |
| `timestep` | float | `MdRuns/{id}/md_run.toml` | researcher authored | Integration timestep. |
| `computer` | text | `MdRuns/{id}/md_run.toml` | researcher authored | Name of the computer used. |
| `reference_contact` | text | `MdRuns/{id}/md_run.toml` | researcher authored | Reference or contact for the run. |
| `force_field_version` | text | `MdRuns/{id}/md_run.toml` | researcher authored | Force-field version used. |

---

## 2. Acquisition entity

One row per imaging position. Primary key: `(sample_id, acquisition_id)`.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `acquisition_id` | text (PK) | `directory` | derived | Acquisition folder name, e.g. `Position_86`. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample directory name. |
| `resolution` | float | `acquisition.toml` (`[acquisition]`) | researcher authored | Angstrom. Nominal target. |
| `tilt_spacing` | float | `acquisition.toml` (`[acquisition]`) | researcher authored | Degrees. **Target** tilt step set at acquisition — researcher intent, distinct from the MDOC-derived actual `tilt_angles`. |
| `defocus_range` | text | `acquisition.toml` (`[acquisition]`) | researcher authored | Micrometres, free-text. **Target** defocus range set before collection — researcher intent, distinct from the MDOC-derived per-image actuals (`defocus_per_image`). |
| `energy_filter` | text | `acquisition.toml` (`[acquisition]`) | researcher authored | Model name. |
| `phase_plate` | boolean | `acquisition.toml` (`[acquisition]`) | researcher authored | |
| `microscope` | text | `acquisition.toml` (`[acquisition]`) | researcher authored | Model name. |
| `facility` | text | `acquisition.toml` (`[acquisition]`) | researcher authored | Imaging facility, e.g. `Janelia`. |
| `acquisition_quality` | integer | `acquisition.toml` (`[acquisition]`) | researcher authored | 1–5 rubric, the author's estimate of the acquistion quality (alignability + projection-image survival): **5** Excellent (reconstructions could be publication-ready), **4** Good (useful for analysis — subtomogram avg, segmentation), **3** Medium (minor projection images discarded before reconstruction), **2** Marginal (major projection images discarded; usable only after heavy manual work), **1** Low (not alignable / not useful for analysis). |
| `pixel_size` | float | `MDOC` | derived | Angstrom. |
| `dose_per_tilt` | list[float] | `MDOC` | derived | e/Å² per tilt. |
| `total_dose` | float | `MDOC` (summed) | derived | e/Å². |
| `tilt_min` | float | `MDOC` | derived | Degrees. Minimum tilt angle recorded. |
| `tilt_max` | float | `MDOC` | derived | Degrees. |
| `tilt_axis` | float | `MDOC` | derived | Degrees. |
| `tilt_angles` | list[float] | `MDOC` | derived | Full per-image tilt-angle list parsed from the `Frames/` MDOC. Describes the acquisition's tilt scheme, shared by all of its tilt series, and powers the acquisition-level polar plot. |
| `defocus_per_image` | list[float] | `MDOC` | derived | Micrometres, per tilt. |
| `date_collected` | date | `MDOC` | derived | |
| `voltage` | float | `MDOC` | derived | kV. |
| `energy_filter_slit_width` | float | `MDOC` | derived | eV. |
| `camera` | text | `.eer` / `.tiff` | derived | Derived from frame extension (`.eer` → Falcon; `.tiff` → K3). |
| `frame_count` | integer | `MDOC` | derived | Number of tilts. |
| `path` | text | `directory` | derived | Absolute acquisition-directory path; surfaced for the UI's copy-path / open-in-file-browser buttons. Synthesized acquisitions record the directory the scanner walked. |
| `renamed_from` | text | `acquisition.toml` (`[acquisition]`) | researcher authored | **Not stored in the DB.** Scan-time-only directive (§08c) — see `Sample.renamed_from`. |

### 2a. Tilt series sub-entity (0..N per acquisition)

One row per tilt series within an acquisition. Primary key:
`(sample_id, acquisition_id, tilt_series_id)`, where `tilt_series_id` is the
name of the folder under `TiltSeries/`. These rows are **researcher-authored**
as `[[tilt_series]]` blocks in `acquisition.toml` (one block per `TiltSeries/{tilt_series_id}/`
folder — there is no per-folder `tiltseries.toml`); the catalog scanner enriches
each authored row with filesystem-derived paths and timestamps. **Multiple tilt
series per acquisition are expected** — a raw/unaligned series (not required), an
aligned series derived from either the frames or the raw tilt series, another alignment derived from the first alignment, etc.

Each `TiltSeries/{tilt_series_id}/` folder holds a `stack/` subdirectory (the
`.mrc` projection stack, plus optional `.zarr` / `.rawtlt`; may be empty) and an
`alignment/` subdirectory (`alignment.json` affine matrix + interpolation recipe).
Alignment is no longer a separate top-level entity — it is folded into the tilt
series as transformation parameters (`is_aligned`, `alignment_software`,
`alignment_method`, plus the discovered `alignment_files`).

The MDOC-derived **tilt geometry now lives on the parent `Acquisition`** (see
the `tilt_angles` field above and the related `tilt_min` / `tilt_max` /
`tilt_axis` / `pixel_size` / `voltage` fields). The MDOC stays in `Frames/` and
describes the acquisition's tilt scheme, shared by all of its tilt series, so the
polar plot is rendered at the acquisition level rather than per tilt series.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `tilt_series_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[[tilt_series]].id`) | researcher authored | Folder name under `TiltSeries/`; the TOML `id` must match the folder. |
| `acquisition_id` | text (FK) | `directory` | derived | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample folder name. |
| `derived_from` | text | `acquisition.toml` (`[[tilt_series]]`) | researcher authored | Either the literal `"Frames"` or another `tilt_series_id` in the same acquisition. |
| `is_aligned` | boolean | `acquisition.toml` (`[[tilt_series]]`) | researcher authored | Whether the stack is already geometrically transformed (aligned). |
| `alignment_software` | text | `acquisition.toml` (`[[tilt_series]]`) | researcher authored | e.g. `IMOD`, `AreTomo3`. |
| `alignment_method` | text | `acquisition.toml` (`[[tilt_series]]`) | researcher authored | e.g. `fiducial`, `patch_tracking`, `feature_tracking`. |
| `st_path` | text | `directory` | derived | Path to the stacked tilt-series `.mrc` file, resolved under `{tilt_series_id}/stack/`. |
| `zarr_path` | text | `directory` | derived | Path to the OME-Zarr rendering under `{tilt_series_id}/stack/`, when present. |
| `alignment_files` | list[text] | `directory` | derived | Alignment artifacts discovered under `{tilt_series_id}/alignment/`. |
| `mtime` | float | `directory` | derived | Modification time, used to gate re-parsing. |
| `renamed_from` | text | `acquisition.toml` (`[[tilt_series]]`) | researcher authored | **Not stored in the DB.** Scan-time-only directive (§08c) — see `Sample.renamed_from`. |

### 2b. MD source sub-entity (one per acquisition; simulation data only)

`acquisition.toml` (`[md_source]`) — records which MD run + frame this acquisition's synthetic data came from. Rejected on `experimental` samples.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `md_run_id` | text (FK) | `acquisition.toml` (`[md_source]`) | researcher authored | Should match an `MdRuns/{id}/` folder name in the sample; a dangling ref warns rather than failing the acquisition. |
| `frame` | integer | `acquisition.toml` (`[md_source]`) | researcher authored | Frame/snapshot index within the MD run. |

---

## 3. Tomogram entities

Raw and post-processed tomograms are split into two tables. They share one
`tomogram_id` namespace within an acquisition: `derived_from` and an
annotation's `target_tomogram` may reference either a raw or a post-processed
tomogram in the same `acquisition.toml`.

### 3a. Raw tomogram (one row per acquisition, optional)

`acquisition.toml` (`[raw_tomogram]`) — at most one per acquisition. Primary key: `(sample_id, acquisition_id, tomogram_id)`.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `tomogram_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[raw_tomogram].id`) | researcher authored | Tomogram **file stem** under `Reconstructions/{tilt_series_id}/Tomograms/` (experimental) or `Reconstructions/Tomograms/` (simulation), e.g. `bp_3dctf_bin4`; the TOML `id` must match the file name without extension. |
| `acquisition_id` | text (FK) | `directory` | derived | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample folder name. |
| `tilt_series_id` | text | `directory` | derived | Enclosing `Reconstructions/{tilt_series_id}/` folder (experimental), gated on a declared `[[tilt_series]]`; `None` for simulation. Formerly authored. |
| `pipeline` | text | `acquisition.toml` (`[raw_tomogram]`) | researcher authored | Human description. |
| `software` | text | `acquisition.toml` (`[raw_tomogram]`) | researcher authored | |
| `voxel_size` | float | `MRC header` | derived | Ångström/pixel. Populated by the catalog scanner from the reconstruction MRC header's `voxel_size.x`; not authored in any TOML. |
| `derived_from` | list[text] | `acquisition.toml` (`[raw_tomogram]`) | researcher authored | Lineage; empty for raw reconstructions. |
| `image_size_x` | integer | `MRC header` | derived | |
| `image_size_y` | integer | `MRC header` | derived | |
| `image_size_z` | integer | `MRC header` | derived | |
| `mrc_path` | text | `directory` | derived | Derived from prescribed layout. |
| `zarr_path` | text | `directory` | derived | Derived from prescribed layout. |
| `zarr_axes` | text | `OME-Zarr .zattrs` | derived | Axis order. |
| `zarr_scale` | list[float] | `OME-Zarr .zattrs` | derived | Multiscale scale factors. |
| `renamed_from` | text | `acquisition.toml` (`[raw_tomogram]`) | researcher authored | **Not stored in the DB.** Scan-time-only directive (§08c) — see `Sample.renamed_from`. |

### 3b. Post-processed tomogram (0..N per acquisition)

`acquisition.toml` (`[[post_processed_tomogram]]`) — one entry per processing output. Primary key: `(sample_id, acquisition_id, tomogram_id)`.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `tomogram_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[[post_processed_tomogram]].id`) | researcher authored | Tomogram **file stem** under `Reconstructions/{tilt_series_id}/Tomograms/` (experimental) or `Reconstructions/Tomograms/` (simulation); the TOML `id` must match the file name without extension. |
| `acquisition_id` | text (FK) | `directory` | derived | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample folder name. |
| `tilt_series_id` | text | `directory` | derived | Enclosing `Reconstructions/{tilt_series_id}/` folder (experimental), gated on a declared `[[tilt_series]]`; `None` for simulation. Formerly authored. |
| `denoising_software` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | |
| `ctf_software` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | |
| `missing_wedge_software` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | |
| `voxel_size` | float | `MRC header` | derived | Ångström/pixel. Populated by the catalog scanner from the reconstruction MRC header's `voxel_size.x`; not authored in any TOML. |
| `derived_from` | list[text] | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | Lineage; references a raw or post-processed `tomogram_id` in this acquisition. |
| `image_size_x` | integer | `MRC header` | derived | |
| `image_size_y` | integer | `MRC header` | derived | |
| `image_size_z` | integer | `MRC header` | derived | |
| `mrc_path` | text | `directory` | derived | Derived from prescribed layout. |
| `zarr_path` | text | `directory` | derived | Derived from prescribed layout. |
| `zarr_axes` | text | `OME-Zarr .zattrs` | derived | Axis order. |
| `zarr_scale` | list[float] | `OME-Zarr .zattrs` | derived | Multiscale scale factors. |
| `size_bytes` | integer | `filesystem` | derived | On-disk size recorded by the scanner via `os.stat` at parse time; powers the home-page size stats and per-card size badges. |
| `renamed_from` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | **Not stored in the DB.** Scan-time-only directive (§08c) — see `Sample.renamed_from`. |

---

## 4. Annotation entity

One row per annotation output. Primary key: `(sample_id, acquisition_id, annotation_id)`.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `annotation_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[[annotation]].id`) | researcher authored | Annotation **file stem** under `Reconstructions/{tilt_series_id}/Annotations/` (experimental) or `Reconstructions/Annotations/` (simulation), e.g. `membrain_seg_v10`; the TOML `id` must match the file name without extension. |
| `acquisition_id` | text (FK) | `directory` | derived | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample folder name. |
| `type` | text | `acquisition.toml` (`[[annotation]]`) | researcher authored | e.g. `membrane_segmentation`, `nucleosome_placement`, `nucleosome_orientation`, `sta_result`. |
| `target_tomogram` | text (FK) | `acquisition.toml` (`[[annotation]]`) | researcher authored | Tomogram this was generated from. |
| `files` | list[text] | `directory` | derived | `.star`, `.mrc`, `.ome.zarr`, `.png` artifacts discovered in the folder. |
| `renamed_from` | text | `acquisition.toml` (`[[annotation]]`) | researcher authored | **Not stored in the DB.** Scan-time-only directive (§08c) — see `Sample.renamed_from`. |
