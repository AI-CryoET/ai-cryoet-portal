"""Filter field registry — single source of truth for the metadata filters.

Mirrored by hand on the frontend in ``frontend/src/utils/filterFields.ts``;
``tests/catalog/test_filter_fields_drift.py`` pins both (a) every non-existence
``table.column`` to a real ORM column and (b) TS↔Python key/kind/table/column
parity. There is no codegen — this repo has no cross-language build step and
``types.ts`` already hand-mirrors ``schemas.py``.

Shapes
------
Each ``Field`` entry:
    key      URL param base (range fields emit ``{key}_min`` / ``{key}_max``)
    label    UI label
    entity   'sample' | 'acquisition'
    group    group id (see GROUPS)
    kind     'text' | 'range' | 'boolean' | 'existence'
    table    ORM ``__tablename__`` for the backend EXISTS
             (sample-direct fields use the ``samples`` table)
    column   ORM column name; for 'existence' it is a predicate id string
             (Phase 1 maps it to the documented correlated EXISTS)
    gating   (optional) True on the two controls that gate which groups apply
             (``data_source``, ``project``) — used by later gating phases.

Group metadata lives at the GROUP level (not per field):
    section        'sample' | 'acquisition'
    id             group id
    title          UI title
    appliesTo      (optional) 'experimental' | 'simulation'
    requiresProject(optional) 'chromatin'
    fields         the group's Field entries
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    entity: str  # 'sample' | 'acquisition'
    group: str
    kind: str  # 'text' | 'range' | 'boolean' | 'existence'
    table: str
    column: str
    gating: bool = False


@dataclass(frozen=True)
class Group:
    section: str  # 'sample' | 'acquisition'
    id: str
    title: str
    fields: list[Field]
    appliesTo: str | None = None  # 'experimental' | 'simulation'
    requiresProject: str | None = None  # 'chromatin'


GROUPS: list[Group] = [
    # ---- Section A — Sample properties ------------------------------------
    Group(
        section="sample",
        id="general",
        title="General",
        fields=[
            Field("lab_name", "Lab", "sample", "general", "text", "samples", "lab_name"),
            # Gating controls: select which groups apply. data_source is hidden
            # on single-arm routes; project gates the chromatin group.
            Field("data_source", "Data source", "sample", "general", "text", "samples", "data_source", gating=True),
            Field("project", "Project", "sample", "general", "text", "samples", "project", gating=True),
            Field("type", "Type", "sample", "general", "text", "samples", "type"),
            Field("cell_type", "Cell type", "sample", "general", "text", "samples", "cell_type"),
        ],
    ),
    Group(
        section="sample",
        id="chromatin",
        title="Chromatin",
        requiresProject="chromatin",
        fields=[
            Field("substrate", "Substrate", "sample", "chromatin", "text", "chromatin", "substrate"),
            Field("linker_length_bp", "Linker length (bp)", "sample", "chromatin", "range", "chromatin", "linker_length_bp"),
            # ponytail: data-derived categorical (stored list[int] stringified, matched IN verbatim).
            # Upgrade to json_each per-element matching only once real data needs it.
            Field("linker_pattern", "Linker pattern", "sample", "chromatin", "text", "chromatin", "linker_pattern"),
            Field("linker_distribution", "Linker distribution", "sample", "chromatin", "text", "chromatin", "linker_distribution"),
            Field("buffer", "Buffer", "sample", "chromatin", "text", "chromatin", "buffer"),
            Field("ptm", "PTM", "sample", "chromatin", "text", "chromatin", "ptm"),
            Field("histone_variants", "Histone variants", "sample", "chromatin", "text", "chromatin", "histone_variants"),
            Field("transcription_factors", "Transcription factors", "sample", "chromatin", "text", "chromatin", "transcription_factors"),
            Field("nucleosome_count", "Nucleosome count", "sample", "chromatin", "range", "chromatin", "nucleosome_count"),
            Field("dna_length_bp", "DNA length (bp)", "sample", "chromatin", "range", "chromatin", "dna_length_bp"),
            Field("nucleosome_uM", "Nucleosome (uM)", "sample", "chromatin", "range", "chromatin", "nucleosome_uM"),
            Field("sequence_identity", "Sequence identity", "sample", "chromatin", "text", "chromatin", "sequence_identity"),
            # ponytail: data-derived categorical (stored list[int] stringified, matched IN verbatim).
            Field("nucleosome_footprint", "Nucleosome footprint", "sample", "chromatin", "text", "chromatin", "nucleosome_footprint"),
            Field("linker_length_fraction", "Linker length fraction", "sample", "chromatin", "range", "chromatin", "linker_length_fraction"),
        ],
    ),
    Group(
        section="sample",
        id="labels",
        title="Labels",
        appliesTo="experimental",
        fields=[
            Field("label_target", "Label target", "sample", "labels", "text", "labels", "label_target"),
            Field("aunp_type", "AuNP type", "sample", "labels", "text", "labels", "aunp_type"),
            # ponytail: data-derived categorical (stored float|list[float], matched IN verbatim — pick-list not range).
            # Swap to a numeric range once real data shows it's wanted.
            Field("label_aunp_size_nm", "AuNP size (nm)", "sample", "labels", "text", "labels", "aunp_size_nm"),
            Field("conjugation", "Conjugation", "sample", "labels", "text", "labels", "conjugation"),
            Field("conjugation_target", "Conjugation target", "sample", "labels", "text", "labels", "conjugation_target"),
            Field("fluorophore", "Fluorophore", "sample", "labels", "text", "labels", "fluorophore"),
        ],
    ),
    Group(
        section="sample",
        id="fiducial",
        title="Fiducial AuNP",
        appliesTo="experimental",
        fields=[
            Field("fiducial_aunp_size_nm", "AuNP size (nm)", "sample", "fiducial", "range", "fiducial", "aunp_size_nm"),
            Field("vendor", "Vendor", "sample", "fiducial", "text", "fiducial", "vendor"),
            Field("catalog_number", "Catalog number", "sample", "fiducial", "text", "fiducial", "catalog_number"),
            Field("product_name", "Product name", "sample", "fiducial", "text", "fiducial", "product_name"),
            Field("concentration_value", "Concentration", "sample", "fiducial", "range", "fiducial", "concentration_value"),
            Field("concentration_unit", "Concentration unit", "sample", "fiducial", "text", "fiducial", "concentration_unit"),
        ],
    ),
    Group(
        section="sample",
        id="freezing",
        title="Freezing",
        appliesTo="experimental",
        fields=[
            Field("grid_type", "Grid type", "sample", "freezing", "text", "freezing", "grid_type"),
            Field("solution_type", "Solution type", "sample", "freezing", "text", "freezing", "solution_type"),
            Field("cryoprotectant", "Cryoprotectant", "sample", "freezing", "text", "freezing", "cryoprotectant"),
            Field("freezing_method", "Method", "sample", "freezing", "text", "freezing", "method"),
            Field("planchette_size", "Planchette size", "sample", "freezing", "text", "freezing", "planchette_size"),
            Field("spacer_thickness", "Spacer thickness", "sample", "freezing", "text", "freezing", "spacer_thickness"),
        ],
    ),
    Group(
        section="sample",
        id="milling",
        title="Milling",
        appliesTo="experimental",
        fields=[
            Field("milling_scheme", "Scheme", "sample", "milling", "text", "milling", "scheme"),
            Field("milling_quality", "Quality", "sample", "milling", "text", "milling", "quality"),
        ],
    ),
    Group(
        section="sample",
        id="simulation",
        title="Simulation",
        appliesTo="simulation",
        fields=[
            Field("dataset_type", "Dataset type", "sample", "simulation", "text", "simulation", "dataset_type"),
        ],
    ),
    # ---- Section B — Acquisition properties -------------------------------
    Group(
        section="acquisition",
        id="general",
        title="General",
        fields=[
            Field("resolution", "Resolution", "acquisition", "general", "range", "acquisitions", "resolution"),
            Field("tilt_spacing", "Tilt spacing", "acquisition", "general", "range", "acquisitions", "tilt_spacing"),
            Field("defocus_range", "Defocus range", "acquisition", "general", "text", "acquisitions", "defocus_range"),
            Field("energy_filter", "Energy filter", "acquisition", "general", "text", "acquisitions", "energy_filter"),
            Field("phase_plate", "Phase plate", "acquisition", "general", "boolean", "acquisitions", "phase_plate"),
            Field("microscope", "Microscope", "acquisition", "general", "text", "acquisitions", "microscope"),
            Field("facility", "Facility", "acquisition", "general", "text", "acquisitions", "facility"),
            Field("acquisition_quality", "Acquisition quality", "acquisition", "general", "text", "acquisitions", "acquisition_quality"),
            Field("pixel_size", "Pixel size", "acquisition", "general", "range", "acquisitions", "pixel_size"),
            Field("total_dose", "Total dose", "acquisition", "general", "range", "acquisitions", "total_dose"),
            Field("tilt_min", "Tilt min", "acquisition", "general", "range", "acquisitions", "tilt_min"),
            Field("tilt_max", "Tilt max", "acquisition", "general", "range", "acquisitions", "tilt_max"),
            Field("tilt_axis", "Tilt axis", "acquisition", "general", "range", "acquisitions", "tilt_axis"),
            Field("voltage", "Voltage", "acquisition", "general", "text", "acquisitions", "voltage"),
            Field("energy_filter_slit_width", "Energy filter slit width", "acquisition", "general", "range", "acquisitions", "energy_filter_slit_width"),
            Field("frame_count", "Frame count", "acquisition", "general", "range", "acquisitions", "frame_count"),
            Field("camera", "Camera", "acquisition", "general", "text", "acquisitions", "camera"),
        ],
    ),
    Group(
        section="acquisition",
        id="tilt_series",
        title="Tilt series",
        fields=[
            # existence: column is a predicate id (Phase 1 maps it to a correlated EXISTS).
            # has_unaligned_tilt_series -> tilt_series WHERE is_aligned IS NOT TRUE
            Field("has_unaligned_tilt_series", "Has unaligned tilt series", "acquisition", "tilt_series", "existence", "tilt_series", "has_unaligned_tilt_series"),
            # has_aligned_tilt_series -> tilt_series WHERE is_aligned IS TRUE
            Field("has_aligned_tilt_series", "Has aligned tilt series", "acquisition", "tilt_series", "existence", "tilt_series", "has_aligned_tilt_series"),
            # has_tilt_series_zarr -> tilt_series WHERE zarr_path IS NOT NULL
            Field("has_tilt_series_zarr", "Has tilt series Zarr", "acquisition", "tilt_series", "existence", "tilt_series", "has_tilt_series_zarr"),
        ],
    ),
    Group(
        section="acquisition",
        id="tomograms",
        title="Tomograms",
        fields=[
            # has_raw_tomogram -> raw_tomograms exists
            Field("has_raw_tomogram", "Has raw tomogram", "acquisition", "tomograms", "existence", "raw_tomograms", "has_raw_tomogram"),
            # has_post_processed_tomogram -> post_processed_tomograms exists
            Field("has_post_processed_tomogram", "Has post-processed tomogram", "acquisition", "tomograms", "existence", "post_processed_tomograms", "has_post_processed_tomogram"),
            # has_tomogram_zarr -> (raw_tomograms UNION post_processed_tomograms) WHERE zarr_path IS NOT NULL.
            # Convention: nominal table = raw_tomograms; Phase 1 ORs the EXISTS over both tomogram tables.
            Field("has_tomogram_zarr", "Has tomogram Zarr", "acquisition", "tomograms", "existence", "raw_tomograms", "has_tomogram_zarr"),
        ],
    ),
    Group(
        section="acquisition",
        id="annotations",
        title="Annotations",
        fields=[
            Field("annotation_type", "Annotation type", "acquisition", "annotations", "text", "annotations", "type"),
        ],
    ),
]


# Flat view of every field, for iteration by later phases.
FIELDS: list[Field] = [f for g in GROUPS for f in g.fields]


# Project -> the only data_source it can have (ADR-0003). synapse data is never
# simulation-derived, so both the authoring forms and the landing-page filter
# panel disable the opposing (simulation) arm when synapse is selected, exactly
# as schema.py rejects the combination at ingest. Mirrored in filterFields.ts.
PROJECT_REQUIRES_DATA_SOURCE: dict[str, str] = {"synapse": "experimental"}
