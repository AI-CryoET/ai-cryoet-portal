"""Authored-field registry for the TOML authoring forms (ADR-0002).

Single source of truth, in Python, for which ``schema.py`` fields the authoring
forms expose and how to render them. Codegen'd to
``frontend/src/utils/formFields.ts`` by ``generate_form_fields.py``; both the
completeness and the codegen-parity drift tests live in
``tests/test_form_fields_drift.py``.

Each form is split into **sections** (``FORM_SECTIONS``), one per TOML table.
A section is either *root* (its fields sit at the top level of the file, like
``md_run.toml``), a named ``[table]``, or a repeatable ``[[table]]``. Every
field on a section's backing model must be classified in ``FORM_FIELDS`` —
authored fields render; ``authored=False`` fields are MDOC/MRC/directory-derived
and are listed only so the completeness drift test can prove nothing was missed.

The directory-derived identity field (``md_run_id`` / ``acquisition_id``) is the
non-persisted *intended-id* field (``is_id=True``): collected to drive the
"save as …" placement hint and to satisfy model validation, but dropped from the
written file by the endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass

from schema.schema import (
    Acquisition,
    Annotation,
    MdRun,
    MdSource,
    PostProcessedTomogram,
    RawTomogram,
    TiltSeries,
)


@dataclass(frozen=True)
class FormField:
    form: str  # 'md_run' | 'acquisition'
    section: str  # toml table the field belongs to
    field: str  # model field name; also the TOML key (except the id field)
    label: str
    input: str  # 'text' | 'integer' | 'number' | 'select' | 'boolean' | 'date'
    required: bool = False
    # The non-persisted intended-id field: collected for the placement hint and
    # model validation, never written into the output file (directory-derived).
    is_id: bool = False
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
    # Fixed select options (e.g. acquisition_quality 1–5).
    options: tuple[str, ...] = ()
    # Model alias, when the TOML key differs from the field name (tilt_series_id
    # is authored as ``id``). Used to remap uploaded keys back to the field.
    alias: str | None = None


@dataclass(frozen=True)
class FormSection:
    form: str
    section: str  # toml table name
    title: str  # display heading ('' for a root single-section form)
    # Python-only: backing model for the completeness drift test. Not codegen'd.
    model: type
    # [[table]] — add/remove multiple entries.
    repeatable: bool = False
    # Fields sit at the file's top level (md_run.toml) rather than under a
    # ``[section]`` table. Drives whether the payload nests under the key.
    root: bool = False
    # Section appears only for this data_source (md_source ⇒ simulation).
    requires_data_source: str | None = None
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
    ),
]


FORM_SECTIONS: list[FormSection] = [
    # md_run.toml is a flat top-level file: one root section, no [md_run] table.
    FormSection("md_run", "md_run", "", MdRun, root=True),
    # acquisition.toml: [acquisition] + optional [md_source] + [[tilt_series]].
    FormSection("acquisition", "acquisition", "Acquisition", Acquisition),
    FormSection(
        "acquisition", "md_source", "MD source (simulation)", MdSource,
        requires_data_source="simulation",
    ),
    FormSection(
        "acquisition", "tilt_series", "Tilt series", TiltSeries,
        repeatable=True, cross_ref_literals=("Frames",),
        id_namespace="tilt_series", immutable_on_load=True,
    ),
    # Processing log (ADR-0004): raw + post-processed tomograms share one id
    # namespace ("tomogram") that derived_from / target_tomogram reference.
    FormSection(
        "acquisition", "raw_tomogram", "Raw tomogram", RawTomogram,
        id_namespace="tomogram", immutable_on_load=True,
    ),
    FormSection(
        "acquisition", "post_processed_tomogram", "Post-processed tomograms",
        PostProcessedTomogram, repeatable=True,
        id_namespace="tomogram", immutable_on_load=True,
    ),
    FormSection(
        "acquisition", "annotation", "Annotations", Annotation,
        repeatable=True, immutable_on_load=True,
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
              help="Random seed for the simulation run."),
    FormField("md_run", "md_run", "sample_time", "Sample time", "number",
              help="Total simulated time."),
    FormField("md_run", "md_run", "timestep", "Timestep", "number",
              help="Integration timestep."),
    FormField("md_run", "md_run", "computer", "Computer", "text",
              help="Machine the run executed on."),
    FormField("md_run", "md_run", "reference_contact", "Reference / contact", "text"),
    FormField("md_run", "md_run", "force_field_version", "Force field version", "text"),

    # ---- acquisition [acquisition] — researcher-authored imaging params ----
    FormField(
        "acquisition", "acquisition", "acquisition_id", "Acquisition id", "text",
        required=True, is_id=True,
        help="Acquisition folder name. Sets identity; not written into the file.",
    ),
    FormField("acquisition", "acquisition", "resolution", "Resolution (Å)", "number",
              help="Nominal resolution."),
    FormField("acquisition", "acquisition", "tilt_spacing", "Tilt spacing (°)", "number",
              help="Nominal tilt spacing."),
    FormField("acquisition", "acquisition", "defocus_range", "Defocus range (µm)", "text",
              help="Target defocus range, free text."),
    FormField("acquisition", "acquisition", "energy_filter", "Energy filter", "text"),
    FormField("acquisition", "acquisition", "phase_plate", "Phase plate", "boolean"),
    FormField("acquisition", "acquisition", "microscope", "Microscope", "text"),
    FormField("acquisition", "acquisition", "facility", "Facility", "text",
              help="Imaging facility, e.g. Janelia."),
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
        help="The simulation run this acquisition came from. "
             "Suggested from the sample's runs; free text also accepted.",
    ),
    FormField("acquisition", "md_source", "frame", "Frame", "integer",
              help="Frame / snapshot index within the run."),

    # ---- acquisition [[tilt_series]] — one per tilt series ----------------
    FormField(
        "acquisition", "tilt_series", "tilt_series_id", "Tilt series id", "text",
        required=True, alias="id", help="Folder name under TiltSeries/.",
    ),
    FormField(
        "acquisition", "tilt_series", "derived_from", "Derived from", "select",
        cross_ref="tilt_series",
        help='"Frames" (raw) or another tilt series in this acquisition.',
    ),
    FormField("acquisition", "tilt_series", "is_aligned", "Is aligned", "boolean"),
    FormField("acquisition", "tilt_series", "alignment_software", "Alignment software", "text"),
    FormField("acquisition", "tilt_series", "alignment_method", "Alignment method", "text"),
    *_derived(
        "acquisition", "tilt_series",
        "sample_id", "acquisition_id", "st_path", "zarr_path",
        "alignment_files", "mtime",
    ),

    # ---- acquisition [raw_tomogram] — at most one reconstruction off frames --
    FormField(
        "acquisition", "raw_tomogram", "tomogram_id", "Tomogram id", "text",
        required=True, alias="id", help="Folder name under Tomograms/.",
    ),
    FormField(
        "acquisition", "raw_tomogram", "tilt_series_id", "Tilt series", "select",
        cross_ref="tilt_series",
        help="The tilt series this tomogram was reconstructed from.",
    ),
    FormField("acquisition", "raw_tomogram", "pipeline", "Pipeline", "text"),
    FormField("acquisition", "raw_tomogram", "software", "Software", "text"),
    FormField(
        "acquisition", "raw_tomogram", "derived_from", "Derived from", "multiselect",
        cross_ref="tomogram",
        help="Other tomograms in this acquisition this one was derived from.",
    ),
    *_derived(
        "acquisition", "raw_tomogram",
        "image_size_x", "image_size_y", "image_size_z", "voxel_size",
        "mrc_path", "zarr_path", "zarr_axes", "zarr_scale",
    ),

    # ---- acquisition [[post_processed_tomogram]] — one per processed output --
    FormField(
        "acquisition", "post_processed_tomogram", "tomogram_id", "Tomogram id",
        "text", required=True, alias="id", help="Folder name under Tomograms/.",
    ),
    FormField(
        "acquisition", "post_processed_tomogram", "tilt_series_id", "Tilt series",
        "select", cross_ref="tilt_series",
        help="The tilt series this tomogram was reconstructed from.",
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
        help="Other tomograms in this acquisition this one was derived from.",
    ),
    *_derived(
        "acquisition", "post_processed_tomogram",
        "image_size_x", "image_size_y", "image_size_z", "voxel_size",
        "mrc_path", "zarr_path", "zarr_axes", "zarr_scale", "size_bytes",
    ),

    # ---- acquisition [[annotation]] — one per segmentation -----------------
    FormField(
        "acquisition", "annotation", "annotation_id", "Annotation id", "text",
        required=True, alias="id", help="Folder name under Annotations/.",
    ),
    FormField("acquisition", "annotation", "type", "Type", "text"),
    FormField(
        "acquisition", "annotation", "target_tomogram", "Target tomogram", "select",
        cross_ref="tomogram",
        help="The tomogram in this acquisition this annotation segments.",
    ),
    *_derived("acquisition", "annotation", "files"),
]


# Section identity -> backing Pydantic model. Drives the completeness drift
# test: every field on a section's model must be classified in FORM_FIELDS.
FORMS = {(s.form, s.section): s.model for s in FORM_SECTIONS}
