"""Curated single source of truth for the DOCUMENTED data model.

Every field a researcher or reader should see, organized by entity and nesting.
Two generators render from this module: ``generate_schema_docs`` emits both
``docs/schema.md`` and the frontend ``schemaData.ts``. Completeness against the
SQLAlchemy ORM (the DB superset) is enforced by tests/test_schema_catalog_drift.py.

This mirrors the ADR-0002 pattern (form_fields.py): hand-authored Python source,
codegen'd artifacts, drift-tested. Types and notes are display strings carried
here (sourced from the prior docs/schema.md); the drift test guards that every
documented field is a real ORM column and every non-internal ORM column is
documented.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from catalog import orm


@dataclass(frozen=True)
class CatalogField:
    name: str
    type: str  # display string, e.g. 'text', 'float', 'list[float]', 'enum'
    source: str  # provenance label, e.g. 'sample.toml [sample]', 'MDOC', 'directory'
    notes: str = ""
    in_db: bool = True  # False = documented but not an ORM column (renamed_from)

    @property
    def kind(self) -> str:
        return "authored" if ".toml" in self.source else "derived"


@dataclass(frozen=True)
class CatalogEntity:
    key: str
    name: str
    cardinality: str
    parent: str | None
    orm: type
    arm: str | None = None  # 'experimental' | 'simulation' | None (both)
    chromatin_only: bool = False
    fields: list[CatalogField] = field(default_factory=list)


# Domain ORM classes the catalog documents (see Global Constraints).
DOMAIN_ORM: list[type] = [
    orm.SampleORM, orm.ChromatinORM, orm.LabelORM, orm.FiducialORM,
    orm.SimulationORM, orm.FreezingORM, orm.MillingORM, orm.MdRunORM,
    orm.AcquisitionORM, orm.MdSourceORM, orm.ReconstructionAlignmentORM,
    orm.RawTomogramORM, orm.PostProcessedTomogramORM, orm.AnnotationORM,
    orm.TiltSeriesORM,
]

# Operational/scanner-internal ORM classes with no documented-catalog entry
# (scan bookkeeping, issue tracking, deletion/soft-delete log, catalog meta).
# DOMAIN_ORM + OPERATIONAL_ORM must together cover every mapped ORM class —
# see test_domain_and_operational_orm_partition_all_tables.
OPERATIONAL_ORM: list[type] = [
    orm.ExtrasORM, orm.ScanRunORM, orm.ScanLogLineORM, orm.ScanSampleOutcomeORM,
    orm.DeletionEventORM, orm.IssueORM, orm.SampleScanStatusORM,
    orm.AcquisitionScanStatusORM, orm.ScanStateORM, orm.CatalogMetaORM,
]

# Internal/operational columns intentionally left out of the documented model.
UNDOCUMENTED_ORM_COLUMNS: dict[str, set[str]] = {
    "samples": {"deleted_at", "disk_size_bytes", "thumbnail_path"},
    "labels": {"ordinal"},
}

CATALOG: list[CatalogEntity] = [
    CatalogEntity(
        key="sample", name="Sample", cardinality="one per sample",
        parent=None, orm=orm.SampleORM,
        fields=[
            CatalogField("sample_id", "text", "directory", "Sample folder name."),
            CatalogField("lab_name", "enum", "sample.toml [sample]",
                         "collepardo, gouaux, rosen, or villa."),
            CatalogField("data_source", "enum", "directory",
                         "experimental (under Experimental/) or simulation (under "
                         "MdSimulation/); not authored in sample.toml."),
            CatalogField("project", "enum", "sample.toml [sample]",
                         "chromatin, synapse, or nanogold."),
            CatalogField("type", "text", "sample.toml [sample]", "e.g. cellular / reconstituted."),
            CatalogField("cell_type", "text", "sample.toml [sample]", "Required when type = cellular."),
            CatalogField("description", "text", "sample.toml [sample]", "Free text."),
            CatalogField("path", "text", "directory",
                         "Absolute sample-directory path; surfaced for the UI's copy-path / "
                         "open-in-file-browser buttons. Works even for samples with no "
                         "acquisitions."),
            CatalogField("renamed_from", "text", "sample.toml [sample]",
                         "Scan-time-only rename directive; not stored in the DB.", in_db=False),
        ],
    ),
    CatalogEntity(
        key="chromatin", name="Chromatin", cardinality="one per sample",
        parent="sample", orm=orm.ChromatinORM, chromatin_only=True,
        fields=[
            CatalogField("sample_id", "text", "directory", "Parent sample directory name."),
            CatalogField("substrate", "text", "sample.toml [chromatin]", "e.g. synthetic / native / n/a."),
            CatalogField("linker_length_bp", "float", "sample.toml [chromatin]",
                         "Homogenous linker length."),
            CatalogField("linker_pattern", "list[int]", "sample.toml [chromatin]",
                         "Patterned linker lengths."),
            CatalogField("linker_distribution", "text", "sample.toml [chromatin]",
                         "Free-text distribution description."),
            CatalogField("buffer", "text", "sample.toml [chromatin]",
                         "Monovalent/divalent species + conc + additives."),
            CatalogField("ptm", "text", "sample.toml [chromatin]"),
            CatalogField("histone_variants", "text", "sample.toml [chromatin]"),
            CatalogField("transcription_factors", "text", "sample.toml [chromatin]"),
            CatalogField("nucleosome_count", "integer", "sample.toml [chromatin]"),
            CatalogField("dna_length_bp", "integer", "sample.toml [chromatin]"),
            CatalogField("nucleosome_uM", "float", "sample.toml [chromatin]"),
            CatalogField("sequence_identity", "text", "sample.toml [chromatin]",
                         "Native-substrate only."),
            CatalogField("nucleosome_footprint", "list", "sample.toml [chromatin]",
                         "Native-substrate only."),
            CatalogField("linker_length_fraction", "float", "derived",
                         "sequence_footprint minus 1; computed on ingest."),
        ],
    ),
    CatalogEntity(
        key="label", name="Label", cardinality="0..N per sample",
        parent="sample", orm=orm.LabelORM, arm="experimental",
        fields=[
            CatalogField("sample_id", "text", "directory", "Parent sample directory name."),
            CatalogField("label_target", "text", "sample.toml [label]", "Protein name, e.g. AMPAR, NMDAR."),
            CatalogField("aunp_type", "text", "sample.toml [label]", "monomer, dimer, trimer, etc."),
            CatalogField("aunp_size_nm", "float or list of floats", "sample.toml [label]"),
            CatalogField("conjugation", "text", "sample.toml [label]",
                         "Fab / nanobody / chemical_tag / none."),
            CatalogField("conjugation_target", "text", "sample.toml [label]", "e.g. GluA2."),
            CatalogField("fluorophore", "text", "sample.toml [label]"),
            CatalogField("notes", "text", "sample.toml [label]"),
        ],
    ),
    CatalogEntity(
        key="fiducial", name="Fiducial AuNP", cardinality="one per sample",
        parent="sample", orm=orm.FiducialORM, arm="experimental",
        fields=[
            CatalogField("sample_id", "text", "directory", "Parent sample directory name."),
            CatalogField("aunp_size_nm", "float or list of floats", "sample.toml [fiducial]"),
            CatalogField("vendor", "text", "sample.toml [fiducial]"),
            CatalogField("catalog_number", "text", "sample.toml [fiducial]"),
            CatalogField("product_name", "text", "sample.toml [fiducial]"),
            CatalogField("concentration_value", "float", "sample.toml [fiducial]"),
            CatalogField("concentration_unit", "text", "sample.toml [fiducial]"),
        ],
    ),
    CatalogEntity(
        key="simulation", name="Simulation", cardinality="one per sample",
        parent="sample", orm=orm.SimulationORM, arm="simulation",
        fields=[
            CatalogField("sample_id", "text", "directory", "Parent sample directory name."),
            CatalogField("dataset_type", "enum", "directory",
                         "One of bulk, single_molecule, slab — derived from the "
                         "MdSimulation/{Bulk,SingleMolecule,Slab}/ subdirectory, not authored "
                         "in sample.toml."),
        ],
    ),
    CatalogEntity(
        key="freezing", name="Freezing", cardinality="one per sample",
        parent="sample", orm=orm.FreezingORM, arm="experimental",
        fields=[
            CatalogField("sample_id", "text", "directory", "Parent sample directory name."),
            CatalogField("grid_type", "text", "sample.toml [freezing]", 'e.g. "Quantifoil R2/2".'),
            CatalogField("solution_type", "text", "sample.toml [freezing]", 'e.g. "HEPES-based".'),
            CatalogField("cryoprotectant", "text", "sample.toml [freezing]", 'or "none".'),
            CatalogField("method", "text", "sample.toml [freezing]", "plunge_frozen / HPF."),
            CatalogField("planchette_size", "text", "sample.toml [freezing]", "HPF only."),
            CatalogField("spacer_thickness", "text", "sample.toml [freezing]", "HPF only."),
        ],
    ),
    CatalogEntity(
        key="milling", name="Milling", cardinality="one per sample",
        parent="sample", orm=orm.MillingORM, arm="experimental",
        fields=[
            CatalogField("sample_id", "text", "directory", "Parent sample directory name."),
            CatalogField("scheme", "text", "sample.toml [milling]", "e.g. cryo-FIB."),
            CatalogField("date", "date", "sample.toml [milling]", "YYYY-MM-DD."),
            CatalogField("quality", "text", "sample.toml [milling]"),
        ],
    ),
    CatalogEntity(
        key="md_run", name="MD run", cardinality="0..N per sample",
        parent="sample", orm=orm.MdRunORM, arm="simulation",
        fields=[
            CatalogField("md_run_id", "text", "directory",
                         "Run folder name under MdRuns/ — the source of identity."),
            CatalogField("sample_id", "text", "directory", "Parent sample directory name."),
            CatalogField("seed", "integer", "md_run.toml", "RNG seed for the run."),
            CatalogField("sample_time", "float", "md_run.toml", "Total simulated time."),
            CatalogField("timestep", "float", "md_run.toml", "Integration timestep."),
            CatalogField("computer", "text", "md_run.toml", "Name of the computer used."),
            CatalogField("reference_contact", "text", "md_run.toml",
                         "Reference or contact for the run."),
            CatalogField("force_field_version", "text", "md_run.toml", "Force-field version used."),
        ],
    ),
    CatalogEntity(
        key="acquisition", name="Acquisition", cardinality="one per imaging position",
        parent=None, orm=orm.AcquisitionORM,
        fields=[
            CatalogField("acquisition_id", "text", "directory",
                         "Acquisition folder name, e.g. Position_86."),
            CatalogField("sample_id", "text", "directory", "Parent sample directory name."),
            CatalogField("resolution", "float", "acquisition.toml [acquisition]",
                         "Angstrom. Nominal target."),
            CatalogField("tilt_spacing", "float", "acquisition.toml [acquisition]",
                         "Degrees. Target tilt step set at acquisition — researcher intent, "
                         "distinct from the MDOC-derived actual tilt_angles."),
            CatalogField("defocus_range", "text", "acquisition.toml [acquisition]",
                         "Micrometres, free-text. Target defocus range set before collection — "
                         "researcher intent, distinct from the MDOC-derived per-image actuals "
                         "(defocus_per_image)."),
            CatalogField("energy_filter", "text", "acquisition.toml [acquisition]", "Model name."),
            CatalogField("phase_plate", "boolean", "acquisition.toml [acquisition]"),
            CatalogField("microscope", "text", "acquisition.toml [acquisition]", "Model name."),
            CatalogField("facility", "text", "acquisition.toml [acquisition]",
                         "Imaging facility, e.g. Janelia."),
            CatalogField("acquisition_quality", "integer", "acquisition.toml [acquisition]",
                         "1-5 rubric, the author's estimate of the acquisition quality "
                         "(alignability + projection-image survival): 5 Excellent, 4 Good, "
                         "3 Medium, 2 Marginal, 1 Low."),
            CatalogField("pixel_size", "float", "MDOC", "Angstrom."),
            CatalogField("dose_per_tilt", "list[float]", "MDOC", "e/Å² per tilt."),
            CatalogField("total_dose", "float", "MDOC", "e/Å², summed."),
            CatalogField("tilt_min", "float", "MDOC", "Degrees. Minimum tilt angle recorded."),
            CatalogField("tilt_max", "float", "MDOC", "Degrees."),
            CatalogField("tilt_axis", "float", "MDOC", "Degrees."),
            CatalogField("tilt_angles", "list[float]", "MDOC",
                         "Full per-image tilt-angle list parsed from the Frames/ MDOC. Describes "
                         "the acquisition's tilt scheme, shared by all of its tilt series, and "
                         "powers the acquisition-level polar plot."),
            CatalogField("defocus_per_image", "list[float]", "MDOC", "Micrometres, per tilt."),
            CatalogField("date_collected", "date", "MDOC"),
            CatalogField("voltage", "float", "MDOC", "kV."),
            CatalogField("energy_filter_slit_width", "float", "MDOC", "eV."),
            CatalogField("camera", "text", ".eer / .tiff",
                         "Derived from frame extension (.eer -> Falcon; .tiff -> K3)."),
            CatalogField("frame_count", "integer", "MDOC", "Number of tilts."),
            CatalogField("path", "text", "directory",
                         "Absolute acquisition-directory path; surfaced for the UI's copy-path / "
                         "open-in-file-browser buttons. Synthesized acquisitions record the "
                         "directory the scanner walked."),
            CatalogField("renamed_from", "text", "acquisition.toml [acquisition]",
                         "Scan-time-only rename directive; not stored in the DB.", in_db=False),
        ],
    ),
    CatalogEntity(
        key="md_source", name="MD source", cardinality="one per acquisition",
        parent="acquisition", orm=orm.MdSourceORM, arm="simulation",
        fields=[
            CatalogField("sample_id", "text", "directory", "Parent sample directory name."),
            CatalogField("acquisition_id", "text", "directory", "Parent acquisition directory name."),
            CatalogField("md_run_id", "text", "acquisition.toml [md_source]",
                         "Should match an MdRuns/{id}/ folder name in the sample; a dangling "
                         "ref warns rather than failing the acquisition."),
            CatalogField("frame", "integer", "acquisition.toml [md_source]",
                         "Frame/snapshot index within the MD run."),
        ],
    ),
    CatalogEntity(
        key="raw_tomogram", name="Raw tomogram",
        cardinality="0..N per 3D alignment group",
        parent="reconstruction_alignment", orm=orm.RawTomogramORM,
        fields=[
            CatalogField("tomogram_id", "text", "directory",
                         "Reconstruction file's name without its extension, e.g. "
                         "bp_3dctf_bin4; the TOML id must match the stem."),
            CatalogField("acquisition_id", "text", "directory", "Parent acquisition folder name."),
            CatalogField("sample_id", "text", "directory", "Parent sample folder name."),
            CatalogField("reconstruction_alignment_id", "text", "directory",
                         "Enclosing Reconstructions/{id}/ folder — the 3D-alignment group "
                         "this belongs to. Part of the key: two groups may hold the same "
                         "file stem."),
            CatalogField("pipeline", "text", "reconstruction.toml [[raw_tomogram]]",
                         "Human description."),
            CatalogField("software", "text", "reconstruction.toml [[raw_tomogram]]"),
            CatalogField("voxel_size", "float", "MRC header",
                         "Ångström/pixel. Read by the scanner from the reconstruction MRC "
                         "header's voxel_size.x; not authored in any TOML."),
            CatalogField("mrc_voxel_size_missing", "boolean", "MRC header",
                         "True when the MRC header carries no voxel size (cella=0) — what "
                         "mrc-ng-server reads — so the Neuroglancer viewer would be mis-scaled "
                         "and the frontend disables its launch button. An explicit flag, set "
                         "alongside voxel_size when the header read comes back empty."),
            CatalogField("derived_from", "text", "reconstruction.toml [[raw_tomogram]]",
                         "The tilt series (under TiltSeries/) this was reconstructed from."),
            CatalogField("image_size_x", "integer", "MRC header"),
            CatalogField("image_size_y", "integer", "MRC header"),
            CatalogField("image_size_z", "integer", "MRC header"),
            CatalogField("mrc_path", "text", "directory", "Derived from prescribed layout."),
            CatalogField("zarr_path", "text", "directory", "Derived from prescribed layout."),
            CatalogField("zarr_axes", "text", "OME-Zarr .zattrs", "Axis order."),
            CatalogField("zarr_scale", "list[float]", "OME-Zarr .zattrs", "Multiscale scale factors."),
            CatalogField("renamed_from", "text", "reconstruction.toml [[raw_tomogram]]",
                         "Scan-time-only rename directive; not stored in the DB.", in_db=False),
        ],
    ),
    CatalogEntity(
        key="post_processed_tomogram", name="Post-processed tomogram",
        cardinality="0..N per 3D alignment group",
        parent="reconstruction_alignment", orm=orm.PostProcessedTomogramORM,
        fields=[
            CatalogField("tomogram_id", "text", "directory",
                         "Reconstruction file's name without its extension; the TOML id "
                         "must match the stem."),
            CatalogField("acquisition_id", "text", "directory", "Parent acquisition folder name."),
            CatalogField("sample_id", "text", "directory", "Parent sample folder name."),
            CatalogField("reconstruction_alignment_id", "text", "directory",
                         "Enclosing Reconstructions/{id}/ folder — the 3D-alignment group "
                         "this belongs to. Part of the key: two groups may hold the same "
                         "file stem."),
            CatalogField("denoising_software", "text",
                         "reconstruction.toml [[post_processed_tomogram]]"),
            CatalogField("ctf_software", "text",
                         "reconstruction.toml [[post_processed_tomogram]]"),
            CatalogField("missing_wedge_software", "text",
                         "reconstruction.toml [[post_processed_tomogram]]"),
            CatalogField("voxel_size", "float", "MRC header",
                         "Ångström/pixel. Read by the scanner from the reconstruction MRC "
                         "header's voxel_size.x; not authored in any TOML."),
            CatalogField("mrc_voxel_size_missing", "boolean", "MRC header",
                         "True when the MRC header carries no voxel size (cella=0) — what "
                         "mrc-ng-server reads — so the Neuroglancer viewer would be mis-scaled "
                         "and the frontend disables its launch button. An explicit flag, set "
                         "alongside voxel_size when the header read comes back empty."),
            CatalogField("derived_from", "list[text]",
                         "reconstruction.toml [[post_processed_tomogram]]",
                         "Lineage; references a raw or post-processed tomogram_id in this "
                         "acquisition (resolvable across sibling groups)."),
            CatalogField("image_size_x", "integer", "MRC header"),
            CatalogField("image_size_y", "integer", "MRC header"),
            CatalogField("image_size_z", "integer", "MRC header"),
            CatalogField("mrc_path", "text", "directory", "Derived from prescribed layout."),
            CatalogField("zarr_path", "text", "directory", "Derived from prescribed layout."),
            CatalogField("zarr_axes", "text", "OME-Zarr .zattrs", "Axis order."),
            CatalogField("zarr_scale", "list[float]", "OME-Zarr .zattrs", "Multiscale scale factors."),
            CatalogField("size_bytes", "integer", "filesystem",
                         "On-disk size recorded by the scanner via os.stat at parse time; "
                         "powers the home-page size stats and per-card size badges."),
            CatalogField("renamed_from", "text",
                         "reconstruction.toml [[post_processed_tomogram]]",
                         "Scan-time-only rename directive; not stored in the DB.", in_db=False),
        ],
    ),
    CatalogEntity(
        key="annotation", name="Annotation",
        cardinality="0..N per 3D alignment group",
        parent="reconstruction_alignment", orm=orm.AnnotationORM,
        fields=[
            CatalogField("annotation_id", "text", "directory",
                         "Annotation file's name without its extension, e.g. "
                         "membrain_seg_v10; the TOML id must match the stem."),
            CatalogField("acquisition_id", "text", "directory", "Parent acquisition folder name."),
            CatalogField("sample_id", "text", "directory", "Parent sample folder name."),
            CatalogField("reconstruction_alignment_id", "text", "directory",
                         "Enclosing Reconstructions/{id}/ folder — the 3D-alignment group "
                         "this belongs to. Part of the key: two groups may hold the same "
                         "file stem."),
            CatalogField("type", "text", "reconstruction.toml [[annotation]]",
                         "e.g. membrane_segmentation, nucleosome_placement, "
                         "nucleosome_orientation, sta_result."),
            CatalogField("derived_from", "text", "reconstruction.toml [[annotation]]",
                         "Id of the tomogram in this group the annotation was "
                         "derived from."),
            CatalogField("bounding_box", "text", "reconstruction.toml [[annotation]]",
                         "Id of the annotation file (under Annotations/) holding the "
                         "bounding box this annotation is associated with."),
            CatalogField("files", "list[text]", "directory",
                         ".star, .mrc, .ome.zarr, .png artifacts sharing this stem."),
            CatalogField("renamed_from", "text", "reconstruction.toml [[annotation]]",
                         "Scan-time-only rename directive; not stored in the DB.", in_db=False),
        ],
    ),
    CatalogEntity(
        key="reconstruction_alignment", name="3D alignment group",
        cardinality="0..N per acquisition",
        parent="acquisition", orm=orm.ReconstructionAlignmentORM,
        fields=[
            CatalogField("reconstruction_alignment_id", "text", "directory",
                         "Folder name under Reconstructions/. Does NOT have to match any "
                         "tilt_series_id — a tomogram's tilt-series lineage is recorded on "
                         "raw_tomogram.derived_from instead."),
            CatalogField("acquisition_id", "text", "directory", "Parent acquisition folder name."),
            CatalogField("sample_id", "text", "directory", "Parent sample folder name."),
            CatalogField("alignment_software", "text",
                         "reconstruction.toml [reconstruction_alignment]",
                         "e.g. IMOD, RELION, AreTomo3."),
            CatalogField("alignment_method", "text",
                         "reconstruction.toml [reconstruction_alignment]",
                         "e.g. patch_tracking, fiducial, subtomogram_averaging."),
            CatalogField("alignment_files", "list[text]", "directory",
                         "3D-alignment artifacts discovered under "
                         "Reconstructions/{id}/Alignment/."),
            CatalogField("mtime", "float", "directory", "Modification time, used to gate re-parsing."),
            CatalogField("renamed_from", "text",
                         "reconstruction.toml [reconstruction_alignment]",
                         "Scan-time-only rename directive; not stored in the DB.", in_db=False),
        ],
    ),
    CatalogEntity(
        key="tilt_series", name="Tilt series", cardinality="0..N per acquisition",
        parent="acquisition", orm=orm.TiltSeriesORM,
        fields=[
            CatalogField("tilt_series_id", "text", "directory",
                         "Folder name under TiltSeries/; the TOML id must match the folder."),
            CatalogField("acquisition_id", "text", "directory", "Parent acquisition folder name."),
            CatalogField("sample_id", "text", "directory", "Parent sample folder name."),
            CatalogField("derived_from", "text", "acquisition.toml [[tilt_series]]",
                         'Either the literal "Frames" or another tilt_series_id in the same '
                         "acquisition."),
            CatalogField("is_aligned", "boolean", "acquisition.toml [[tilt_series]]",
                         "Whether the stack is already geometrically transformed (aligned)."),
            CatalogField("alignment_software", "text", "acquisition.toml [[tilt_series]]",
                         "e.g. IMOD, AreTomo3."),
            CatalogField("alignment_method", "text", "acquisition.toml [[tilt_series]]",
                         "e.g. fiducial, patch_tracking, feature_tracking."),
            CatalogField("st_path", "text", "directory",
                         "Path to the stacked tilt-series .mrc file, resolved under "
                         "{tilt_series_id}/Stack/."),
            CatalogField("zarr_path", "text", "directory",
                         "Path to the OME-Zarr rendering under {tilt_series_id}/Stack/, when "
                         "present."),
            CatalogField("alignment_files", "list[text]", "directory",
                         "Alignment artifacts discovered under {tilt_series_id}/Alignment/."),
            CatalogField("mtime", "float", "directory", "Modification time, used to gate re-parsing."),
            CatalogField("renamed_from", "text", "acquisition.toml [[tilt_series]]",
                         "Scan-time-only rename directive; not stored in the DB.", in_db=False),
        ],
    ),
]
