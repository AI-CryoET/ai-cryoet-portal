"""Pydantic response models for the API.

Separate from schema models — these are flat, JSON-consumer-shaped output
types so the API can evolve its response shape without touching the validation
schema. Frontend ``frontend/src/api/types.ts`` mirrors these field-by-field.
"""
from __future__ import annotations

import datetime as _dt
from typing import Literal

from pydantic import BaseModel


# ── Sample list / summary ────────────────────────────────────────────────


class SampleMatch(BaseModel):
    """Where a browse-page `q` search matched inside a sample. Sample-level
    matches carry ``acquisition_id=None``; descendant matches carry the
    acquisition so the frontend can auto-expand and mark it."""

    acquisition_id: str | None = None
    kind: Literal["sample", "acquisition", "tomogram", "annotation"]
    matched_id: str


class SampleSummary(BaseModel):
    sample_id: str
    project: str
    lab_name: str | None = None
    data_source: str
    type: str | None = None
    cell_type: str | None = None
    description: str | None = None
    path: str | None = None
    experiment_date: _dt.date | None = None
    warning_count: int = 0
    # Total child-row counts intrinsic to the sample — filter-independent.
    # ``n_tomograms`` is summed across raw + post-processed tables.
    n_acquisitions: int = 0
    n_tomograms: int = 0
    n_tilt_series: int = 0
    thumbnail_path: str | None = None
    # Representative OVITO MD-run preview relpath (served by /md-previews) for
    # the sample-list hero on simulation samples; None when no run has a preview.
    md_preview_path: str | None = None
    # Populated only when the list is called with `q`: the IDs (and their
    # acquisition, if any) that matched, so the browse table can auto-expand
    # the matching acquisitions. Empty when there is no `q`.
    matches: list[SampleMatch] = []


# ── Sample detail: typed sub-entities ────────────────────────────────────


class ChromatinOut(BaseModel):
    substrate: str | None = None
    linker_length_bp: float | None = None
    linker_pattern: list[int] | None = None
    linker_distribution: str | None = None
    buffer: str | None = None
    ptm: str | None = None
    histone_variants: str | None = None
    transcription_factors: str | None = None
    nucleosome_count: int | None = None
    dna_length_bp: int | None = None
    nucleosome_uM: float | None = None
    sequence_identity: str | None = None
    nucleosome_footprint: list[int] | None = None
    linker_length_fraction: float | None = None


class LabelOut(BaseModel):
    ordinal: int
    label_target: str | None = None
    aunp_type: str | None = None
    # Polymorphic in the schema (single nanogold size or a list of sizes).
    aunp_size_nm: float | list[float] | None = None
    conjugation: str | None = None
    conjugation_target: str | None = None
    fluorophore: str | None = None
    notes: str | None = None


class FiducialOut(BaseModel):
    aunp_size_nm: float | None = None
    vendor: str | None = None
    catalog_number: str | None = None
    product_name: str | None = None
    concentration_value: float | None = None
    concentration_unit: str | None = None


class SimulationOut(BaseModel):
    dataset_type: str | None = None


class FreezingOut(BaseModel):
    grid_type: str | None = None
    solution_type: str | None = None
    cryoprotectant: str | None = None
    method: str | None = None
    planchette_size: str | None = None
    spacer_thickness: str | None = None


class MillingOut(BaseModel):
    scheme: str | None = None
    date: _dt.date | None = None
    quality: str | None = None


class MdRunOut(BaseModel):
    md_run_id: str
    seed: int | None = None
    computer: str | None = None
    sample_time: float | None = None
    timestep: float | None = None
    reference_contact: str | None = None
    force_field_version: str | None = None
    # Cache-relative path of the OVITO preview PNG (served by /md-previews),
    # or None when no preview was rendered for this run.
    preview_path: str | None = None


class _TomogramOutBase(BaseModel):
    """Fields shared by raw and post-processed tomogram outputs.

    Kept in one base class so the frontend can render both kinds with
    shared cell logic.
    """

    tomogram_id: str
    # the Reconstructions/{group}/ the id lives in — the id alone is only a
    # file stem, so the frontend needs the group to build URLs and to tell
    # same-named tomograms in different groups apart.
    reconstruction_alignment_id: str
    voxel_size: float | None = None                  # angstrom
    # MRC header has no voxel size (cella=0): the viewer would be mis-scaled, so
    # the frontend disables the Neuroglancer launch button. See schema.RawTomogram.
    mrc_voxel_size_missing: bool = False
    image_size_x: int | None = None
    image_size_y: int | None = None
    image_size_z: int | None = None
    mrc_path: str | None = None
    zarr_path: str | None = None
    zarr_axes: str | None = None
    zarr_scale: list[float] | None = None
    # file extensions (e.g. "MRC", "ZARR") derived from mrc_path/zarr_path
    file_formats: list[str] = []


class RawTomogramOut(_TomogramOutBase):
    pipeline: str | None = None
    software: str | None = None
    # the tilt_series id (under TiltSeries/) this was reconstructed from
    derived_from: str | None = None


class PostProcessedTomogramOut(_TomogramOutBase):
    denoising_software: str | None = None
    ctf_software: str | None = None
    missing_wedge_software: str | None = None
    size_bytes: int | None = None
    # id(s) of the tomogram(s) this was derived from
    derived_from: list[str] = []


class AnnotationOut(BaseModel):
    annotation_id: str
    # see _TomogramOutBase.reconstruction_alignment_id
    reconstruction_alignment_id: str
    type: str | None = None
    # tomogram_id in this group the annotation was derived from
    derived_from: str | None = None
    # annotation_id (under Annotations/) of the associated bounding box
    bounding_box: str | None = None
    files: list[str] = []
    # file extensions (e.g. "STAR", "PNG") derived from files, deduped
    file_formats: list[str] = []


class TiltSeriesOut(BaseModel):
    tilt_series_id: str
    derived_from: str | None = None
    is_aligned: bool | None = None
    alignment_software: str | None = None
    alignment_method: str | None = None
    st_path: str | None = None
    zarr_path: str | None = None
    alignment_files: list[str] = []
    mtime: float | None = None


class ReconstructionAlignmentOut(BaseModel):
    reconstruction_alignment_id: str
    alignment_software: str | None = None
    alignment_method: str | None = None
    alignment_files: list[str] = []
    mtime: float | None = None


class MdSourceOut(BaseModel):
    md_run_id: str | None = None
    frame: int | None = None


class EntityScanStatus(BaseModel):
    """Per-sample freshness rollup (from ``sample_scan_status``)."""

    last_scanned_at: float
    last_changed_at: float | None = None
    last_outcome: str
    last_scan_run_id: str


class AcquisitionScanStatus(EntityScanStatus):
    """Per-acquisition freshness + thumbnail provenance (from
    ``acquisition_scan_status``). Extends the sample shape with the
    thumbnail's real rendered source, generated-at, and status."""

    thumbnail_path: str | None = None
    thumbnail_source_kind: str | None = None
    thumbnail_source_path: str | None = None
    thumbnail_generated_at: float | None = None
    thumbnail_status: str | None = None


class AcquisitionOut(BaseModel):
    acquisition_id: str
    # acquisition.toml ([acquisition]) — researcher authored
    resolution: float | None = None
    tilt_spacing: float | None = None
    defocus_range: str | None = None
    energy_filter: str | None = None
    phase_plate: bool | None = None
    microscope: str | None = None
    facility: str | None = None
    acquisition_quality: int | None = None
    # MDOC / frame-extension derived
    pixel_size: float | None = None
    dose_per_tilt: list[float] | None = None
    total_dose: float | None = None
    tilt_min: float | None = None
    tilt_max: float | None = None
    tilt_axis: float | None = None
    tilt_angles: list[float] | None = None
    defocus_per_image: list[float] | None = None
    date_collected: _dt.date | None = None
    voltage: float | None = None
    energy_filter_slit_width: float | None = None
    frame_count: int | None = None
    camera: str | None = None
    path: str | None = None
    md_source: MdSourceOut | None = None
    raw_tomograms: list[RawTomogramOut] = []
    post_processed_tomograms: list[PostProcessedTomogramOut] = []
    annotations: list[AnnotationOut] = []
    tilt_series: list[TiltSeriesOut] = []
    reconstruction_alignment: list[ReconstructionAlignmentOut] = []
    scan_status: AcquisitionScanStatus | None = None


class SampleDetail(BaseModel):
    sample_id: str
    project: str
    lab_name: str | None = None
    data_source: str
    type: str | None = None
    cell_type: str | None = None
    description: str | None = None
    path: str | None = None
    experiment_date: _dt.date | None = None
    chromatin: ChromatinOut | None = None
    fiducial: FiducialOut | None = None
    simulation: SimulationOut | None = None
    freezing: FreezingOut | None = None
    milling: MillingOut | None = None
    label: list[LabelOut] = []
    md_run: list[MdRunOut] = []
    acquisitions: list[AcquisitionOut] = []
    # Representative cached-thumbnail relpath ({sample}/{acq}.png): the first
    # acquisition (by id) that produced a thumbnail. Lets the detail-page hero
    # fall back to a cached image even when no acquisition declares a tilt
    # series (the thumbnail is rendered from raw Frames/). None if none exists.
    thumbnail_path: str | None = None
    scan_status: EntityScanStatus | None = None


# ── Filters / stats / viewers ────────────────────────────────────────────


class RangeOut(BaseModel):
    """Range bounds; ``None`` when no rows exist for the facet."""
    min: float | None = None
    max: float | None = None


class FiltersOptionsOut(BaseModel):
    """Registry-driven filter options: ``categorical`` keyed by each ``text``
    field's key, ``ranges`` keyed by each ``range`` field's key."""
    categorical: dict[str, list[str]] = {}
    ranges: dict[str, RangeOut] = {}


class StatsTotalsOut(BaseModel):
    samples: int = 0
    acquisitions: int = 0
    tilt_series: int = 0
    # Sum across raw + post-processed tomogram tables.
    tomograms: int = 0
    annotations: int = 0
    warnings: int = 0


class ProjectStatRow(BaseModel):
    project: str
    samples: int = 0
    acquisitions: int = 0
    # Sum across raw + post-processed tomogram tables.
    tomograms: int = 0
    # Sum across PostProcessedTomogramORM.size_bytes only — RawTomogram has
    # no size_bytes field in the schema.
    size_bytes: int = 0


class StatsOverviewOut(BaseModel):
    totals: StatsTotalsOut
    by_project: list[ProjectStatRow] = []


class ViewerLaunchOut(BaseModel):
    """Response of a POST .../neuroglancer launch.

    Frontend rewrites the hostname to ``window.location.hostname`` before
    opening.
    """
    url: str


# ── Scan history / warnings / extras ─────────────────────────────────────


class WarningOut(BaseModel):
    id: int
    sample_id: str
    category: str
    location: str
    message: str
    detected_at: float
    scan_run_id: str


# ── Manage page (scan run history + issues) ──────────────────────────────


class LatestScanInfo(BaseModel):
    started_at: float
    ended_at: float | None = None
    status: str
    duration: float | None = None


class OutstandingCounts(BaseModel):
    errors: int = 0
    warnings: int = 0
    infos: int = 0


class ManageSummary(BaseModel):
    """Status/cadence card payload for the Manage page (§3.4)."""

    latest_scan: LatestScanInfo | None = None
    cadence_cron: str
    cadence_tz: str
    outstanding: OutstandingCounts
    # Deletion events recorded in the latest completed run (§08a badge).
    deletions_latest_run: int = 0


class IssueItem(BaseModel):
    category: str
    message: str


class IssueGroup(BaseModel):
    """Outstanding (or recently-resolved) issues grouped by
    (scope, sample_id, acquisition_id, md_run_id, file_kind)."""

    scope: str
    sample_id: str | None = None
    acquisition_id: str | None = None
    md_run_id: str | None = None
    file_kind: str
    file_path: str | None = None
    severity: str
    issues: list[IssueItem] = []
    first_seen_at: float
    last_seen_at: float
    last_seen_run_id: str
    latest_run_id: str | None = None
    latest_scan_at: float | None = None
    resolved_at: float | None = None
    resolved_run_id: str | None = None


class ScanRun(BaseModel):
    scan_run_id: str
    started_at: float
    ended_at: float | None = None
    status: str
    root: str
    n_upserted: int | None = None
    n_skipped: int | None = None
    n_failed: int | None = None
    n_new_issues: int | None = None
    n_resolved_issues: int | None = None
    n_warning_active: int | None = None
    n_error_active: int | None = None
    n_info_active: int | None = None


class ScanLogLine(BaseModel):
    id: int
    seq: int
    ts: float
    level: str
    sample_id: str | None = None
    message: str


class ScanSampleOutcomeOut(BaseModel):
    sample_id: str
    outcome: str
    detail: str | None = None


class DeletionEvent(BaseModel):
    """One row of the append-only deletion audit feed (§08a/§08c)."""

    id: int
    scan_run_id: str
    detected_at: float
    entity_type: str
    kind: str = "deletion"
    sample_id: str
    acquisition_id: str | None = None
    entity_id: str | None = None
    last_known_path: str | None = None
    last_known_json: str | None = None


class ExtrasSummaryRow(BaseModel):
    entity_type: str
    key: str
    count: int
