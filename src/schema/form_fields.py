"""Authored-field registry for the TOML authoring forms (ADR-0002).

Single source of truth, in Python, for which ``schema.py`` fields the authoring
forms expose and how to render them. Codegen'd to
``frontend/src/utils/formFields.ts`` by ``generate_form_fields.py``; both the
completeness and the codegen-parity drift tests live in
``tests/test_form_fields_drift.py``.

Each form is split into **sections** (``FORM_SECTIONS``), one per TOML table.
A section is either *root* (its fields sit at the top level of the file, like
``md_run.toml``), a named ``[table]``, or a repeatable ``[[table]]``. Only the
**authored** subset of each section's model is rendered. Two field roles are
collected but not written as ordinary values:

- the directory-derived identity field (``md_run_id`` / ``acquisition_id`` /
  ``sample_id``, injected from the folder name by the loader) is the
  non-persisted *intended-id* field (``is_id=True``): it drives the "save as …"
  placement hint and satisfies model validation, but the endpoint drops it;
- ``derived=True`` fields are populated on ingest (MDOC/MRC/directory) and are
  never authored — they are classified here only so the completeness drift test
  stays honest, and the renderer skips them.

The ``sample`` and ``acquisition`` forms are **composite**: their backing model
(``SampleRecord`` / ``AcquisitionFile``) is built from nested sub-models, one
per TOML table, so ``FORM_SECTIONS`` records the per-section structure (title,
repeatability, conditional gating, cross-ref/immutability metadata). The
``md_run`` form is flat — a single root section whose model *is* the form model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schema.schema import (
    Acquisition,
    AcquisitionFile,
    Annotation,
    Chromatin,
    Fiducial,
    Freezing,
    Label,
    LabName,
    MdRun,
    MdSource,
    Milling,
    PostProcessedTomogram,
    Project,
    RawTomogram,
    ReconstructionAlignment,
    ReconstructionFile,
    Sample,
    SampleRecord,
    TiltSeries,
)


@dataclass(frozen=True)
class FormField:
    form: str  # 'md_run' | 'acquisition' | 'sample'
    section: str  # toml table the field belongs to
    field: str  # model field name; also the TOML key (except the id field)
    label: str
    # 'text' | 'integer' | 'number' | 'select' | 'multiselect' | 'boolean'
    # | 'date' | 'list'
    input: str
    required: bool = False
    # The non-persisted intended-id field: collected for the placement hint and
    # model validation, never written into the output file (directory-derived).
    is_id: bool = False
    # Ingest-populated (MDOC/MRC/directory) — classified for the drift test but
    # not rendered as an authored input.
    derived: bool = False
    options: tuple[str, ...] = ()  # enum / fixed select choices (e.g. quality 1-5)
    help: str = ""
    # Authored fields render; derived (MDOC/MRC/directory) fields are classified
    # but hidden — listed only so the completeness drift test stays honest.
    authored: bool = True
    # Cross-reference: render a dropdown of in-form ids from this *id namespace*
    # (e.g. derived_from offers the "tilt_series" or "tomogram" namespace ids,
    # plus the field's section literals like "Frames").
    cross_ref: str | None = None
    # API-assisted free-text: suggest ids of this kind from the loaded sample
    # context (e.g. md_source.md_run_id suggests the sample's known md_runs).
    api_suggest: str | None = None
    # Model alias, when the TOML key differs from the field name (tilt_series_id
    # is authored as ``id``). Used to remap uploaded keys back to the field.
    alias: str | None = None


@dataclass(frozen=True)
class FormSection:
    form: str
    section: str  # nested key on the form model; the TOML table name
    title: str  # display heading ('' for a root single-section form)
    # Pydantic sub-model backing this section. Used by the completeness drift
    # test and (server-side) never emitted to TS.
    model: type = field(default=object, repr=False)
    # [[table]] — add/remove multiple entries.
    repeatable: bool = False
    # Fields sit at the file's top level (md_run.toml) rather than under a
    # ``[section]`` table. Drives whether the payload nests under the key.
    root: bool = False
    # Conditional gating, mirroring the filter GROUPS metadata (filter_fields.py
    # / filterFields.ts): an arm-gated section shows only for that data_source
    # (md_source ⇒ simulation); a chromatin-gated section hides for synapse and
    # disables for other non-chromatin projects (see ADR-0003 + the filter
    # gating).
    requires_data_source: str | None = None  # 'experimental' | 'simulation'
    requires_project: str | None = None  # 'chromatin'
    # Extra "literal" cross-ref options always offered alongside in-form ids.
    cross_ref_literals: tuple[str, ...] = ()
    # The id namespace this section's required-id field feeds. Cross-ref fields
    # name a namespace; the renderer pools ids across every section sharing it
    # (raw + post-processed tomograms share the "tomogram" namespace).
    id_namespace: str | None = None
    # Processing-log immutability (ADR-0004): entries present when the file was
    # loaded render read-only; only session-added entries stay editable.
    immutable_on_load: bool = False


@dataclass(frozen=True)
class FormMeta:
    form: str
    title: str
    # Placement-hint template; ``{id}`` filled from the intended-id field. The
    # id is the directory name, not file content — hint only.
    placement: str
    filename: str
    # Composite forms post nested ``{section: data}`` and render per-section;
    # flat forms post their fields at the top level.
    composite: bool = False


FORM_META: list[FormMeta] = [
    FormMeta(
        form="md_run",
        title="MD run",
        placement="MdRuns/{id}/md_run.toml",
        filename="md_run.toml",
    ),
    FormMeta(
        form="acquisition",
        title="Acquisition",
        placement="{sample_id}/{id}/acquisition.toml",
        filename="acquisition.toml",
        composite=True,
    ),
    FormMeta(
        form="sample",
        title="Sample",
        placement="{id}/sample.toml",
        filename="sample.toml",
        composite=True,
    ),
    FormMeta(
        "reconstruction",
        "Reconstruction",
        "{sample_id}/{acquisition_id}/Reconstructions/{id}/reconstruction.toml",
        "reconstruction.toml",
        composite=True,
    ),
]


# Top-level fields of a composite form's model that are not authored as form
# sections. ``acquisitions`` is the acquisition form's domain; ``reconstructions``
# is the per-folder reconstruction.toml's domain; ``simulation`` (only the
# derived dataset_type) and ``md_run`` (its own md_run.toml file) are not
# authored in sample.toml. Pinned so a *new* sub-model can't slip in
# unclassified (test_form_fields_drift).
EXCLUDED_TOP_FIELDS: dict[str, set[str]] = {
    "sample": {"simulation", "md_run", "acquisitions", "reconstructions"},
}


FORM_SECTIONS: list[FormSection] = [
    # md_run.toml is a flat top-level file: one root section, no [md_run] table.
    FormSection("md_run", "md_run", "", MdRun, root=True),

    # ---- acquisition.toml (composite; [acquisition] + optional [md_source] +
    #      [[tilt_series]] + processing log) ---------------------------------
    FormSection("acquisition", "acquisition", "Acquisition", model=Acquisition),
    FormSection(
        "acquisition", "md_source", "MD source (simulation)", model=MdSource,
        requires_data_source="simulation",
    ),
    FormSection(
        "acquisition", "tilt_series", "Tilt series", model=TiltSeries,
        repeatable=True, cross_ref_literals=("Frames",),
        id_namespace="tilt_series", immutable_on_load=True,
    ),
    FormSection(
        "acquisition", "reconstruction_alignment", "3D alignment",
        model=ReconstructionAlignment, repeatable=True,
        id_namespace="reconstruction_alignment", immutable_on_load=True,
    ),
    # Processing log (ADR-0004): raw + post-processed tomograms share one id
    # namespace ("tomogram") that post_processed_tomogram.derived_from
    # references.
    FormSection(
        "acquisition", "raw_tomogram", "Raw tomograms", model=RawTomogram,
        repeatable=True, id_namespace="tomogram", immutable_on_load=True,
    ),
    FormSection(
        "acquisition", "post_processed_tomogram", "Post-processed tomograms",
        model=PostProcessedTomogram, repeatable=True,
        id_namespace="tomogram", immutable_on_load=True,
    ),
    FormSection(
        "acquisition", "annotation", "Annotations", model=Annotation,
        repeatable=True, immutable_on_load=True,
    ),

    # ---- sample.toml (composite; mirrors templates/sample.toml) -----------
    FormSection("sample", "sample", "Sample", model=Sample),
    FormSection(
        "sample", "chromatin", "Chromatin", model=Chromatin,
        requires_project="chromatin",
    ),
    FormSection(
        "sample", "label", "Gold-nanoparticle labels", model=Label,
        repeatable=True, requires_data_source="experimental",
    ),
    FormSection(
        "sample", "fiducial", "Fiducial AuNP", model=Fiducial,
        requires_data_source="experimental",
    ),
    FormSection(
        "sample", "freezing", "Freezing / grid prep", model=Freezing,
        requires_data_source="experimental",
    ),
    FormSection(
        "sample", "milling", "Milling", model=Milling,
        requires_data_source="experimental",
    ),

    # ---- reconstruction.toml — one file per Reconstructions/{id}/ group. The
    #      folder name IS the group id, so [reconstruction_alignment] is a
    #      single table (unlike acquisition's repeatable version).
    FormSection(
        "reconstruction", "reconstruction_alignment", "3D alignment",
        model=ReconstructionAlignment,
    ),
    FormSection(
        "reconstruction", "raw_tomogram", "Raw tomograms", model=RawTomogram,
        repeatable=True, id_namespace="tomogram",
    ),
    FormSection(
        "reconstruction", "post_processed_tomogram", "Post-processed tomograms",
        model=PostProcessedTomogram, repeatable=True, id_namespace="tomogram",
    ),
    FormSection(
        "reconstruction", "annotation", "Annotations", model=Annotation,
        repeatable=True,
    ),
]


def _derived(form: str, section: str, *fields: str) -> list[FormField]:
    """Classify MDOC/MRC/directory-derived fields: accounted for by the
    completeness drift test, never rendered (``authored=False``)."""
    return [
        FormField(form, section, f, f, "text", authored=False) for f in fields
    ]


FORM_FIELDS: list[FormField] = [
    # ---- md_run ([md_run]; one md_run.toml per run) -----------------------
    FormField(
        "md_run", "md_run", "md_run_id", "Run id", "text",
        required=True, is_id=True,
        help="Folder name under MdRuns/. Sets identity; not written into the file.",
    ),
    FormField("md_run", "md_run", "seed", "Seed", "integer",
              help="Random seed for the run."),
    FormField("md_run", "md_run", "sample_time", "Sample time", "number",
              help="Total simulated time."),
    FormField("md_run", "md_run", "timestep", "Timestep", "number",
              help="Integration timestep."),
    FormField("md_run", "md_run", "computer", "Computer", "text",
              help="Name of the computer used."),
    FormField("md_run", "md_run", "reference_contact", "Reference / contact", "text",
              help="Reference or contact for this run."),
    FormField("md_run", "md_run", "force_field_version", "Force field version", "text",
              help="Force field name/version."),

    # ---- acquisition [acquisition] — researcher-authored imaging params ----
    FormField(
        "acquisition", "acquisition", "acquisition_id", "Acquisition id", "text",
        required=True, is_id=True,
        help="Acquisition folder name. Sets identity; not written into the file.",
    ),
    FormField(
        "acquisition", "acquisition", "renamed_from", "Renamed from", "text",
        help="Previous acquisition id if you renamed this directory, so the "
             "scanner records a rename instead of a deletion + new acquisition.",
    ),
    FormField("acquisition", "acquisition", "resolution", "Resolution (Å)", "number",
              help="Nominal resolution in Å, e.g. 3.5"),
    FormField("acquisition", "acquisition", "tilt_spacing", "Tilt spacing (°)", "number",
              help="Target tilt step in degrees, e.g. 3.0 (intent; actual angles "
                   "come from the MDOC)."),
    FormField("acquisition", "acquisition", "defocus_range", "Defocus range (µm)", "text",
              help='Target defocus range in µm, e.g. "-1.5 to -3.0" (intent; '
                   "per-image actuals come from the MDOC)."),
    FormField("acquisition", "acquisition", "energy_filter", "Energy filter", "text",
              help='Model name, e.g. "Selectris", "GIF Quantum", "none".'),
    FormField("acquisition", "acquisition", "phase_plate", "Phase plate", "boolean",
              help="true | false"),
    FormField("acquisition", "acquisition", "microscope", "Microscope", "text",
              help='Model name, e.g. "Titan Krios", "Glacios".'),
    FormField("acquisition", "acquisition", "facility", "Facility", "text",
              help='Imaging facility, e.g. "Janelia".'),
    FormField(
        "acquisition", "acquisition", "acquisition_quality", "Quality (1–5)", "select",
        options=("1", "2", "3", "4", "5"),
        help="5 Excellent … 1 Low (alignability + projection-image survival).",
    ),
    # MDOC / MRC / frame-extension / directory-derived — classified, not rendered.
    *_derived(
        "acquisition", "acquisition",
        "pixel_size", "dose_per_tilt", "total_dose", "tilt_min", "tilt_max",
        "tilt_axis", "tilt_angles", "defocus_per_image", "date_collected",
        "voltage", "energy_filter_slit_width", "frame_count", "camera", "path",
    ),

    # ---- acquisition [md_source] — simulation provenance ------------------
    FormField(
        "acquisition", "md_source", "md_run_id", "MD run id", "text",
        api_suggest="md_run",
        help="MUST match a MdRuns/{id}/ folder name (the md_run.toml id). "
             "Suggested from the sample's runs; free text also accepted.",
    ),
    FormField("acquisition", "md_source", "frame", "Frame", "integer",
              help="Frame / snapshot index in the MD run."),

    # ---- acquisition [[tilt_series]] — one per tilt series ----------------
    FormField(
        "acquisition", "tilt_series", "tilt_series_id", "Tilt series id", "text",
        required=True, alias="id",
        help="MUST equal the tilt series' folder name under TiltSeries/.",
    ),
    FormField(
        "acquisition", "tilt_series", "renamed_from", "Renamed from", "text",
        help="Previous tilt series id if you renamed this directory, so the "
             "scanner records a rename instead of a deletion + new tilt series.",
    ),
    FormField(
        "acquisition", "tilt_series", "derived_from", "Derived from", "select",
        cross_ref="tilt_series",
        help='"Frames" (raw) or another tilt series in this acquisition.',
    ),
    FormField("acquisition", "tilt_series", "is_aligned", "Is aligned", "boolean",
              help="true | false; indicates whether the tilt series is aligned."),
    FormField("acquisition", "tilt_series", "alignment_software", "Alignment software", "text",
              help='e.g. "IMOD 4.12", "AreTomo3".'),
    FormField("acquisition", "tilt_series", "alignment_method", "Alignment method", "text",
              help="e.g. fiducial | patch_tracking | feature_tracking"),
    *_derived(
        "acquisition", "tilt_series",
        "sample_id", "acquisition_id", "st_path", "zarr_path",
        "alignment_files", "mtime",
    ),

    # ---- acquisition [[reconstruction_alignment]] — one per 3D alignment group --
    FormField(
        "acquisition", "reconstruction_alignment", "reconstruction_alignment_id",
        "3D alignment id", "text", required=True, alias="id",
        help="MUST equal the folder name under Reconstructions/. Does NOT have "
             "to match any tilt series id.",
    ),
    FormField(
        "acquisition", "reconstruction_alignment", "renamed_from", "Renamed from",
        "text",
        help="Previous 3D alignment id if you renamed this directory, so the "
             "scanner records a rename instead of a deletion + new group.",
    ),
    FormField("acquisition", "reconstruction_alignment", "alignment_software",
              "Alignment software", "text",
              help='e.g. "IMOD 4.12", "RELION", "AreTomo3".'),
    FormField("acquisition", "reconstruction_alignment", "alignment_method",
              "Alignment method", "text",
              help="e.g. patch_tracking | fiducial | subtomogram_averaging"),
    *_derived(
        "acquisition", "reconstruction_alignment",
        "sample_id", "acquisition_id", "alignment_files", "mtime",
    ),

    # ---- acquisition [[raw_tomogram]] — one per reconstruction off a tilt series --
    FormField(
        "acquisition", "raw_tomogram", "tomogram_id", "Tomogram id", "text",
        required=True, alias="id",
        help="MUST equal the tomogram file's name without extension.",
    ),
    FormField(
        "acquisition", "raw_tomogram", "renamed_from", "Renamed from", "text",
        help="Previous tomogram id if you renamed this directory, so the "
             "scanner records a rename instead of a deletion + new tomogram.",
    ),
    FormField("acquisition", "raw_tomogram", "pipeline", "Pipeline", "text",
              help='e.g. "backprojection + 3D CTF correction".'),
    FormField("acquisition", "raw_tomogram", "software", "Software", "text",
              help='e.g. "IMOD 4.12 + novaCTF".'),
    FormField(
        "acquisition", "raw_tomogram", "derived_from", "Derived from", "select",
        cross_ref="tilt_series",
        help="The tilt series (under TiltSeries/) this was reconstructed from.",
    ),
    *_derived(
        "acquisition", "raw_tomogram",
        "reconstruction_alignment_id",
        "image_size_x", "image_size_y", "image_size_z", "voxel_size",
        "mrc_path", "zarr_path", "zarr_axes", "zarr_scale",
    ),

    # ---- acquisition [[post_processed_tomogram]] — one per processed output --
    FormField(
        "acquisition", "post_processed_tomogram", "tomogram_id", "Tomogram id",
        "text", required=True, alias="id",
        help="MUST equal the tomogram file's name without extension.",
    ),
    FormField(
        "acquisition", "post_processed_tomogram", "renamed_from", "Renamed from",
        "text",
        help="Previous tomogram id if you renamed this directory, so the "
             "scanner records a rename instead of a deletion + new tomogram.",
    ),
    FormField("acquisition", "post_processed_tomogram", "denoising_software",
              "Denoising software", "text"),
    FormField("acquisition", "post_processed_tomogram", "ctf_software",
              "CTF software", "text"),
    FormField("acquisition", "post_processed_tomogram", "missing_wedge_software",
              "Missing-wedge software", "text"),
    FormField(
        "acquisition", "post_processed_tomogram", "derived_from", "Derived from",
        "multiselect", cross_ref="tomogram",
        help="Id of the single tomogram, or ids of the multiple tomograms, in "
             "this acquisition this was derived from.",
    ),
    *_derived(
        "acquisition", "post_processed_tomogram",
        "reconstruction_alignment_id",
        "image_size_x", "image_size_y", "image_size_z", "voxel_size",
        "mrc_path", "zarr_path", "zarr_axes", "zarr_scale", "size_bytes",
    ),

    # ---- acquisition [[annotation]] — one per segmentation -----------------
    FormField(
        "acquisition", "annotation", "annotation_id", "Annotation id", "text",
        required=True, alias="id",
        help='MUST equal the annotation\'s folder name, e.g. "membrain_seg_v10".',
    ),
    FormField(
        "acquisition", "annotation", "renamed_from", "Renamed from", "text",
        help="Previous annotation id if you renamed this directory, so the "
             "scanner records a rename instead of a deletion + new annotation.",
    ),
    FormField("acquisition", "annotation", "type", "Type", "text",
              help="e.g. membrane_segmentation | nucleosome_placement | active_zone"),
    *_derived("acquisition", "annotation", "reconstruction_alignment_id", "files"),

    # ---- sample / [sample] ------------------------------------------------
    FormField(
        "sample", "sample", "sample_id", "Sample id", "text",
        is_id=True,
        help="Sample directory name. Sets identity; not written into the file.",
    ),
    FormField(
        "sample", "sample", "renamed_from", "Renamed from", "text",
        help="Previous sample id if you renamed this directory, so the scanner "
             "records a rename instead of a deletion + new sample.",
    ),
    # data_source is the non-persisted arm shape control (derived from the
    # directory on ingest): it drives which sections show but is never written.
    # The renderer surfaces it as a dedicated experimental/simulation toggle.
    FormField("sample", "sample", "data_source", "Data source", "select", derived=True),
    FormField(
        "sample", "sample", "project", "Project", "select",
        required=True, options=tuple(p.value for p in Project),
        help="synapse | chromatin | nanogold",
    ),
    FormField(
        "sample", "sample", "lab_name", "Lab", "select",
        options=tuple(n.value for n in LabName),
        help="collepardo | gouaux | rosen | villa",
    ),
    FormField("sample", "sample", "type", "Type", "text",
              help="e.g. tissue | cellular | reconstituted"),
    FormField("sample", "sample", "cell_type", "Cell type", "text",
              help='Required if type = "cellular".'),
    FormField("sample", "sample", "description", "Description", "text",
              help="Optional free-text description."),
    FormField("sample", "sample", "path", "Path", "text", derived=True),

    # ---- sample / [chromatin] --------------------------------------------
    FormField("sample", "chromatin", "substrate", "Substrate", "text",
              help="e.g. synthetic | native | n/a"),
    FormField("sample", "chromatin", "linker_length_bp", "Linker length (bp)", "number",
              help="Homogenous linker length in bp."),
    FormField("sample", "chromatin", "linker_pattern", "Linker pattern", "list",
              help="Patterned linker lengths, e.g. 20, 50, 20, 50"),
    FormField("sample", "chromatin", "linker_distribution", "Linker distribution", "text",
              help="Free-text for non-homogenous, non-patterned linkers."),
    FormField("sample", "chromatin", "buffer", "Buffer", "text",
              help='e.g. "2.0 mM MgCl2, 150 mM KCl"'),
    FormField("sample", "chromatin", "ptm", "PTM", "text",
              help="e.g. none | H3K9me3 | H3K27me3 | H3K27Ac | H4K16Ac"),
    FormField("sample", "chromatin", "histone_variants", "Histone variants", "text",
              help="e.g. canonical | macroH2A | H2A.Z"),
    FormField("sample", "chromatin", "transcription_factors", "Transcription factors", "text",
              help="e.g. none | HP1a | Brd4"),
    FormField("sample", "chromatin", "nucleosome_count", "Nucleosome count", "integer"),
    FormField("sample", "chromatin", "dna_length_bp", "DNA length (bp)", "integer"),
    FormField("sample", "chromatin", "nucleosome_uM", "Nucleosome (uM)", "number"),
    FormField("sample", "chromatin", "sequence_identity", "Sequence identity", "text"),
    FormField("sample", "chromatin", "nucleosome_footprint", "Nucleosome footprint", "list",
              help="List of ints"),
    FormField("sample", "chromatin", "linker_length_fraction",
              "Linker length fraction", "number", derived=True),

    # ---- sample / [[label]] (repeatable) ---------------------------------
    FormField("sample", "label", "label_target", "Label target", "text",
              help="Protein name, e.g. AMPAR, NMDAR, etc."),
    FormField("sample", "label", "aunp_type", "AuNP type", "text",
              help="monomer, dimer, trimer, etc."),
    FormField("sample", "label", "aunp_size_nm", "AuNP size (nm)", "list",
              help="float or list, e.g. 1.4 or 1.4, 2.2"),
    FormField("sample", "label", "conjugation", "Conjugation", "text",
              help="e.g. Fab | nanobody | chemical_tag | none"),
    FormField("sample", "label", "conjugation_target", "Conjugation target", "text",
              help="e.g. GluA2, H3K9me3"),
    FormField("sample", "label", "fluorophore", "Fluorophore", "text"),
    FormField("sample", "label", "notes", "Notes", "text", help="Optional."),

    # ---- sample / [fiducial] ---------------------------------------------
    FormField("sample", "fiducial", "aunp_size_nm", "AuNP size (nm)", "number",
              help="Fiducial diameter in nm."),
    FormField("sample", "fiducial", "vendor", "Vendor", "text", help="Vendor name."),
    FormField("sample", "fiducial", "catalog_number", "Catalog number", "text"),
    FormField("sample", "fiducial", "product_name", "Product name", "text"),
    FormField("sample", "fiducial", "concentration_value", "Concentration value", "number"),
    FormField("sample", "fiducial", "concentration_unit", "Concentration unit", "text"),

    # ---- sample / [freezing] ---------------------------------------------
    FormField("sample", "freezing", "grid_type", "Grid type", "text",
              help='e.g. "Quantifoil R2/2"'),
    FormField("sample", "freezing", "solution_type", "Solution type", "text",
              help='e.g. "HEPES-based"'),
    FormField("sample", "freezing", "cryoprotectant", "Cryoprotectant", "text",
              help='or "none"'),
    FormField("sample", "freezing", "method", "Method", "text",
              help="plunge_frozen | HPF"),
    FormField("sample", "freezing", "planchette_size", "Planchette size", "text",
              help='e.g. "3 mm"'),
    FormField("sample", "freezing", "spacer_thickness", "Spacer thickness", "text",
              help='e.g. "100 um"'),

    # ---- sample / [milling] ----------------------------------------------
    FormField("sample", "milling", "scheme", "Scheme", "text", help="e.g. cryo-FIB"),
    FormField("sample", "milling", "date", "Milling date", "date", help="YYYY-MM-DD"),
    FormField("sample", "milling", "quality", "Quality", "text",
              help="Comment on FIB quality."),

    # ---- reconstruction [reconstruction_alignment] — single table; the folder
    #      name IS the group id (ReconstructionFile has no id of its own) -----
    FormField(
        "reconstruction", "reconstruction_alignment", "reconstruction_alignment_id",
        "3D alignment id", "text", required=True, is_id=True, alias="id",
        help="Reconstructions/ folder name. Sets identity; not written into the file.",
    ),
    FormField(
        "reconstruction", "reconstruction_alignment", "renamed_from", "Renamed from",
        "text",
        help="Previous 3D alignment id if you renamed this directory, so the "
             "scanner records a rename instead of a deletion + new group.",
    ),
    FormField("reconstruction", "reconstruction_alignment", "alignment_software",
              "Alignment software", "text",
              help='e.g. "IMOD 4.12", "RELION", "AreTomo3".'),
    FormField("reconstruction", "reconstruction_alignment", "alignment_method",
              "Alignment method", "text",
              help="e.g. patch_tracking | fiducial | subtomogram_averaging"),
    *_derived(
        "reconstruction", "reconstruction_alignment",
        "sample_id", "acquisition_id", "alignment_files", "mtime",
    ),

    # ---- reconstruction [[raw_tomogram]] — one per reconstruction off a tilt series --
    FormField(
        "reconstruction", "raw_tomogram", "tomogram_id", "Tomogram id", "text",
        required=True, alias="id",
        help="MUST equal the tomogram file's name without extension.",
    ),
    FormField(
        "reconstruction", "raw_tomogram", "renamed_from", "Renamed from", "text",
        help="Previous tomogram id if you renamed this file, so the "
             "scanner records a rename instead of a deletion + new tomogram.",
    ),
    FormField("reconstruction", "raw_tomogram", "pipeline", "Pipeline", "text",
              help='e.g. "backprojection + 3D CTF correction".'),
    FormField("reconstruction", "raw_tomogram", "software", "Software", "text",
              help='e.g. "IMOD 4.12 + novaCTF".'),
    FormField(
        "reconstruction", "raw_tomogram", "derived_from", "Derived from", "select",
        api_suggest="tilt_series",
        help="The tilt series (under TiltSeries/) this was reconstructed from.",
    ),
    *_derived(
        "reconstruction", "raw_tomogram",
        "reconstruction_alignment_id",
        "image_size_x", "image_size_y", "image_size_z", "voxel_size",
        "mrc_path", "zarr_path", "zarr_axes", "zarr_scale",
    ),

    # ---- reconstruction [[post_processed_tomogram]] — one per processed output --
    FormField(
        "reconstruction", "post_processed_tomogram", "tomogram_id", "Tomogram id",
        "text", required=True, alias="id",
        help="MUST equal the tomogram file's name without extension.",
    ),
    FormField(
        "reconstruction", "post_processed_tomogram", "renamed_from", "Renamed from",
        "text",
        help="Previous tomogram id if you renamed this file, so the "
             "scanner records a rename instead of a deletion + new tomogram.",
    ),
    FormField("reconstruction", "post_processed_tomogram", "denoising_software",
              "Denoising software", "text"),
    FormField("reconstruction", "post_processed_tomogram", "ctf_software",
              "CTF software", "text"),
    FormField("reconstruction", "post_processed_tomogram", "missing_wedge_software",
              "Missing-wedge software", "text"),
    FormField(
        "reconstruction", "post_processed_tomogram", "derived_from", "Derived from",
        "multiselect", cross_ref="tomogram",
        help="Id of the single tomogram, or ids of the multiple tomograms, in "
             "this acquisition this was derived from.",
    ),
    *_derived(
        "reconstruction", "post_processed_tomogram",
        "reconstruction_alignment_id",
        "image_size_x", "image_size_y", "image_size_z", "voxel_size",
        "mrc_path", "zarr_path", "zarr_axes", "zarr_scale", "size_bytes",
    ),

    # ---- reconstruction [[annotation]] — one per segmentation --------------
    FormField(
        "reconstruction", "annotation", "annotation_id", "Annotation id", "text",
        required=True, alias="id",
        help='MUST equal the annotation file\'s name without extension, e.g. '
             '"membrain_seg_v10".',
    ),
    FormField(
        "reconstruction", "annotation", "renamed_from", "Renamed from", "text",
        help="Previous annotation id if you renamed this file, so the "
             "scanner records a rename instead of a deletion + new annotation.",
    ),
    FormField("reconstruction", "annotation", "type", "Type", "text",
              help="e.g. membrane_segmentation | nucleosome_placement | active_zone"),
    *_derived("reconstruction", "annotation", "reconstruction_alignment_id", "files"),
]


# Form kind -> backing Pydantic model. Drives the completeness drift test:
# every field on a covered model (recursing into a composite form's section
# sub-models) must be classified in FORM_FIELDS.
FORMS = {
    "md_run": MdRun,
    "acquisition": AcquisitionFile,
    "sample": SampleRecord,
    "reconstruction": ReconstructionFile,
}
