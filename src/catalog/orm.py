"""SQLAlchemy 2.0 declarative ORM mirroring ``schema.schema``.

Every Pydantic class in :mod:`schema.schema` has a corresponding ORM
class here. The mapping is pinned by ``tests/catalog/test_orm_drift.py``;
adding a Pydantic field requires adding a column here, and vice versa (modulo
the explicit DB-only carve-outs in the drift test).
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from schema.schema import _ID_MAX_LEN, DataSource, DatasetType, LabName, Project


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Sample + per-sample sub-tables
# ---------------------------------------------------------------------------


class SampleORM(Base):
    __tablename__ = "samples"

    sample_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), primary_key=True)
    data_source: Mapped[DataSource] = mapped_column(SAEnum(DataSource), nullable=False)
    project: Mapped[Project] = mapped_column(SAEnum(Project), nullable=False)
    lab_name: Mapped[LabName | None] = mapped_column(SAEnum(LabName), nullable=True)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    cell_type: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Absolute sample-directory path; path-injected by the scanner (mirrors
    # AcquisitionORM.path). Surfaced for the UI's copy-path / open-in-Fileglancer
    # actions so they work even for samples with no acquisitions.
    path: Mapped[str | None] = mapped_column(String, nullable=True)
    # DB-only: soft-delete timestamp
    deleted_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    # DB-only: true on-disk directory size cached by the scanner
    disk_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String, nullable=True)


class ChromatinORM(Base):
    __tablename__ = "chromatin"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    substrate: Mapped[str | None] = mapped_column(String, nullable=True)
    linker_length_bp: Mapped[float | None] = mapped_column(Float, nullable=True)
    linker_pattern: Mapped[list | None] = mapped_column(JSON, nullable=True)
    linker_distribution: Mapped[str | None] = mapped_column(String, nullable=True)
    buffer: Mapped[str | None] = mapped_column(String, nullable=True)
    salt_mM: Mapped[str | None] = mapped_column(String, nullable=True)
    ptm: Mapped[str | None] = mapped_column(String, nullable=True)
    histone_variants: Mapped[str | None] = mapped_column(String, nullable=True)
    transcription_factors: Mapped[str | None] = mapped_column(String, nullable=True)
    nucleosome_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dna_length_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nucleosome_uM: Mapped[float | None] = mapped_column(Float, nullable=True)
    sequence_identity: Mapped[str | None] = mapped_column(String, nullable=True)
    nucleosome_footprint: Mapped[list | None] = mapped_column(JSON, nullable=True)
    linker_length_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)


class LabelORM(Base):
    """Per-sample labels list (one row per ``[[label]]`` block).

    Replaces the old ``aunp`` table — labels share the gold-nanoparticle
    ``aunp_*`` shape but are list-valued so a sample can declare more than one
    label target.
    """

    __tablename__ = "labels"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    label_target: Mapped[str | None] = mapped_column(String, nullable=True)
    aunp_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # Polymorphic ``float | list[float]`` — JSON so both shapes round-trip.
    aunp_size_nm: Mapped[list | float | None] = mapped_column(JSON, nullable=True)
    conjugation: Mapped[str | None] = mapped_column(String, nullable=True)
    conjugation_target: Mapped[str | None] = mapped_column(String, nullable=True)
    fluorophore: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (PrimaryKeyConstraint("sample_id", "ordinal"),)


class FiducialORM(Base):
    """1:1 fiducial block per sample.

    Replaces the old ``synapse`` table slot — synapse-specific labelling moved
    to the list-valued ``labels`` table; ``fiducial`` now carries the vendor /
    catalog metadata for any gold-nanoparticle fiducial used on the sample.
    """

    __tablename__ = "fiducial"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    aunp_size_nm: Mapped[float | None] = mapped_column(Float, nullable=True)
    vendor: Mapped[str | None] = mapped_column(String, nullable=True)
    catalog_number: Mapped[str | None] = mapped_column(String, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String, nullable=True)
    concentration_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    concentration_unit: Mapped[str | None] = mapped_column(String, nullable=True)


class SimulationORM(Base):
    __tablename__ = "simulation"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    dataset_type: Mapped[DatasetType | None] = mapped_column(
        SAEnum(DatasetType), nullable=True
    )


class FreezingORM(Base):
    __tablename__ = "freezing"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    grid_type: Mapped[str | None] = mapped_column(String, nullable=True)
    solution_type: Mapped[str | None] = mapped_column(String, nullable=True)
    cryoprotectant: Mapped[str | None] = mapped_column(String, nullable=True)
    method: Mapped[str | None] = mapped_column(String, nullable=True)
    planchette_size: Mapped[str | None] = mapped_column(String, nullable=True)
    spacer_thickness: Mapped[str | None] = mapped_column(String, nullable=True)


class MillingORM(Base):
    __tablename__ = "milling"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    scheme: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    quality: Mapped[str | None] = mapped_column(String, nullable=True)


class MdRunORM(Base):
    """Per-sample MD-run list (simulation samples only).

    One row per ``[[md_run]]`` block in sample.toml; folder name on disk
    equals ``md_run_id``.
    """

    __tablename__ = "md_runs"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
    )
    md_run_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestep: Mapped[float | None] = mapped_column(Float, nullable=True)
    computer: Mapped[str | None] = mapped_column(String, nullable=True)
    reference_contact: Mapped[str | None] = mapped_column(String, nullable=True)
    force_field_version: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (PrimaryKeyConstraint("sample_id", "md_run_id"),)


# ---------------------------------------------------------------------------
# Acquisition + (raw/post) tomograms + annotations + tilt series + md_source
# ---------------------------------------------------------------------------


class AcquisitionORM(Base):
    __tablename__ = "acquisitions"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
    )
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    resolution: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_spacing: Mapped[float | None] = mapped_column(Float, nullable=True)
    defocus_range: Mapped[str | None] = mapped_column(String, nullable=True)
    energy_filter: Mapped[str | None] = mapped_column(String, nullable=True)
    phase_plate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    microscope: Mapped[str | None] = mapped_column(String, nullable=True)
    facility: Mapped[str | None] = mapped_column(String, nullable=True)
    acquisition_quality: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    pixel_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    dose_per_tilt: Mapped[list | None] = mapped_column(JSON, nullable=True)
    total_dose: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_axis: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_angles: Mapped[list | None] = mapped_column(JSON, nullable=True)
    defocus_per_image: Mapped[list | None] = mapped_column(JSON, nullable=True)
    date_collected: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_filter_slit_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera: Mapped[str | None] = mapped_column(String, nullable=True)
    path: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (PrimaryKeyConstraint("sample_id", "acquisition_id"),)


class MdSourceORM(Base):
    """1:1 simulation provenance per acquisition.

    Composite PK ``(sample_id, acquisition_id)`` mirrors the at-most-one
    ``[md_source]`` block; ``md_run_id`` references ``md_runs.md_run_id``
    within the same sample.
    """

    __tablename__ = "md_source"

    sample_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    md_run_id: Mapped[str | None] = mapped_column(
        String(_ID_MAX_LEN), nullable=True
    )
    frame: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("sample_id", "acquisition_id"),
        ForeignKeyConstraint(
            ["sample_id", "acquisition_id"],
            ["acquisitions.sample_id", "acquisitions.acquisition_id"],
        ),
    )


class RawTomogramORM(Base):
    """At-most-one raw tomogram per acquisition.

    The 1:1-ness is enforced upstream by ``AcquisitionFile.raw_tomogram``
    being ``RawTomogram | None``; the DB PK includes ``tomogram_id`` to
    mirror ``PostProcessedTomogramORM`` and let cross-table queries treat
    both as composite-keyed children of an acquisition.
    """

    __tablename__ = "raw_tomograms"

    sample_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    tomogram_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    tilt_series_id: Mapped[str | None] = mapped_column(
        String(_ID_MAX_LEN), nullable=True
    )
    pipeline: Mapped[str | None] = mapped_column(String, nullable=True)
    software: Mapped[str | None] = mapped_column(String, nullable=True)
    voxel_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    derived_from: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    image_size_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_size_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_size_z: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mrc_path: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_path: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_axes: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_scale: Mapped[list | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("sample_id", "acquisition_id", "tomogram_id"),
        ForeignKeyConstraint(
            ["sample_id", "acquisition_id"],
            ["acquisitions.sample_id", "acquisitions.acquisition_id"],
        ),
    )


class PostProcessedTomogramORM(Base):
    __tablename__ = "post_processed_tomograms"

    sample_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    tomogram_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    tilt_series_id: Mapped[str | None] = mapped_column(
        String(_ID_MAX_LEN), nullable=True
    )
    denoising_software: Mapped[str | None] = mapped_column(String, nullable=True)
    ctf_software: Mapped[str | None] = mapped_column(String, nullable=True)
    missing_wedge_software: Mapped[str | None] = mapped_column(String, nullable=True)
    voxel_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    derived_from: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    image_size_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_size_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_size_z: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mrc_path: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_path: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_axes: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_scale: Mapped[list | None] = mapped_column(JSON, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("sample_id", "acquisition_id", "tomogram_id"),
        ForeignKeyConstraint(
            ["sample_id", "acquisition_id"],
            ["acquisitions.sample_id", "acquisitions.acquisition_id"],
        ),
    )


class AnnotationORM(Base):
    __tablename__ = "annotations"

    sample_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    annotation_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_tomogram: Mapped[str | None] = mapped_column(
        String(_ID_MAX_LEN), nullable=True
    )
    files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (
        PrimaryKeyConstraint("sample_id", "acquisition_id", "annotation_id"),
        ForeignKeyConstraint(
            ["sample_id", "acquisition_id"],
            ["acquisitions.sample_id", "acquisitions.acquisition_id"],
        ),
    )


class TiltSeriesORM(Base):
    """One tilt series per row, FK on the parent acquisition.

    Composite PK ``(sample_id, acquisition_id, tilt_series_id)`` mirrors the
    Pydantic ``TiltSeries`` model. The tilt series is a researcher-authored
    folder under ``TiltSeries/``; alignment is folded in as transformation
    parameters (``is_aligned`` + ``alignment_*``) rather than a separate
    entity. The MDOC-derived tilt geometry lives on ``acquisitions``.
    """

    __tablename__ = "tilt_series"

    sample_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    tilt_series_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    derived_from: Mapped[str | None] = mapped_column(String, nullable=True)
    is_aligned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    alignment_software: Mapped[str | None] = mapped_column(String, nullable=True)
    alignment_method: Mapped[str | None] = mapped_column(String, nullable=True)
    st_path: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_path: Mapped[str | None] = mapped_column(String, nullable=True)
    alignment_files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    mtime: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("sample_id", "acquisition_id", "tilt_series_id"),
        ForeignKeyConstraint(
            ["sample_id", "acquisition_id"],
            ["acquisitions.sample_id", "acquisitions.acquisition_id"],
        ),
    )


# ---------------------------------------------------------------------------
# Housekeeping tables (no Pydantic counterpart)
# ---------------------------------------------------------------------------


class ExtrasORM(Base):
    __tablename__ = "extras"

    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_pk_json: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
        index=True,
    )
    value_json: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("entity_type", "entity_pk_json", "key"),
    )


# ---------------------------------------------------------------------------
# Scan data model — run history (append-only) + current materialized state.
#
# Splits "what did this run find?" (run history: scan_runs, scan_log_lines,
# scan_sample_outcomes, deletion_events) from "what is broken/fresh right
# now?" (current state: issues, sample_scan_status, acquisition_scan_status).
# These tables are catalog-operational and intentionally excluded from the
# Pydantic drift test.
# ---------------------------------------------------------------------------


class ScanRunORM(Base):
    """One row per scan run (append-only run history).

    Records the run's lifecycle (started/ended/status), where it ran, and
    end-of-run count snapshots (outcomes, issue churn, and outstanding-issue
    totals). Replaces the old ``scans`` table.
    """

    __tablename__ = "scan_runs"

    scan_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[float] = mapped_column(Float, nullable=False)
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum("running", "completed", "failed", name="scan_run_status"),
        nullable=False,
    )
    root: Mapped[str] = mapped_column(String, nullable=False)
    n_upserted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_skipped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_failed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_new_issues: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_resolved_issues: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_warning_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_error_active: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ScanLogLineORM(Base):
    """Durable per-run log lines (Priority 3).

    One row per persisted loguru record, bulk-inserted at run end. ``seq``
    gives a deterministic monotonic order within a run; ``sample_id`` carries
    the bound logging context when available. Powers the per-run expandable
    log panel on the run-detail view.
    """

    __tablename__ = "scan_log_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("scan_runs.scan_run_id"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[float] = mapped_column(Float, nullable=False)
    level: Mapped[str] = mapped_column(
        SAEnum("DEBUG", "INFO", "WARNING", "ERROR", name="scan_log_level"),
        nullable=False,
        index=True,
    )
    sample_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    message: Mapped[str] = mapped_column(String, nullable=False)


class ScanSampleOutcomeORM(Base):
    """Per-sample outcome for a scan run (append-only run history).

    Records which samples were upserted, skipped, or failed in each run so the
    run-detail view can list the samples behind each count. No FK on
    ``sample_id`` — a failed sample may never have been persisted to
    ``samples`` (its parse/assemble step is what failed). Replaces the old
    ``scan_samples`` table.
    """

    __tablename__ = "scan_sample_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("scan_runs.scan_run_id"),
        nullable=False,
        index=True,
    )
    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(
        SAEnum("upserted", "skipped", "failed", name="scan_sample_outcome"),
        nullable=False,
    )
    detail: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (UniqueConstraint("scan_run_id", "sample_id"),)


class DeletionEventORM(Base):
    """One row per scan-detected disappearance (append-only audit feed, §08a).

    Records entities dropped by ``_delete_stale_children`` (acquisition,
    md_source, raw/post-processed tomogram, annotation, tilt series) and
    samples soft-deleted by ``soft_delete_missing_samples``. Deliberately has
    no dismiss/resolve — the feed accumulates and is reviewed via
    ``GET /manage/deletions``. Events are naturally one-shot: once a row is
    gone (or a sample leaves the live set), the next scan can't re-detect it,
    so no dedup is needed. ``last_known_path``/``last_known_json`` capture
    enough of the dropped row to identify what was lost.

    ``kind`` (§08c) distinguishes an ordinary deletion from a rename detected
    via the ``renamed_from`` hint — reusing this table rather than a second
    one, since a rename is audit-feed content of the same shape (old id, last
    known state) with a different disposition. Defaults to ``"deletion"``
    client-side (not a DB server-default) since this table is brand new in
    this same epic (08a) with no released rows to backfill; every insert site
    either passes ``kind="rename"`` explicitly or relies on this default.
    For a rename, ``last_known_json`` holds
    ``{"renamed_from": old_id, "renamed_to": new_id}`` instead of a row
    snapshot — there's no dedicated old/new id column.
    """

    __tablename__ = "deletion_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("scan_runs.scan_run_id"),
        nullable=False,
        index=True,
    )
    detected_at: Mapped[float] = mapped_column(Float, nullable=False)
    entity_type: Mapped[str] = mapped_column(
        SAEnum(
            "sample",
            "acquisition",
            "raw_tomogram",
            "post_processed_tomogram",
            "annotation",
            "tilt_series",
            "md_source",
            name="deletion_entity_type",
        ),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        SAEnum("deletion", "rename", name="deletion_event_kind"),
        nullable=False,
        default="deletion",
    )
    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN), nullable=False, index=True
    )
    acquisition_id: Mapped[str | None] = mapped_column(String, nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_known_path: Mapped[str | None] = mapped_column(String, nullable=True)
    last_known_json: Mapped[str | None] = mapped_column(String, nullable=True)


class IssueORM(Base):
    """Current, deduplicated, entity-keyed issue (the heart of Priority 1).

    One row per distinct problem (identified by ``fingerprint``), carrying
    severity, file attribution, and first/last-seen + resolution stamps.
    ``resolved_at IS NULL`` means outstanding. Reconciled on every scan so
    first-seen survives across runs and resolution is detected when a
    re-evaluated entity stops emitting the issue. Replaces ``scan_warnings`` +
    ``scan_run_warnings``.
    """

    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    severity: Mapped[str] = mapped_column(
        SAEnum("error", "warning", name="issue_severity"),
        nullable=False,
        index=True,
    )
    scope: Mapped[str] = mapped_column(
        SAEnum("sample", "acquisition", "run", name="issue_scope"),
        nullable=False,
    )
    sample_id: Mapped[str | None] = mapped_column(
        String(_ID_MAX_LEN), nullable=True, index=True
    )
    acquisition_id: Mapped[str | None] = mapped_column(String, nullable=True)
    md_run_id: Mapped[str | None] = mapped_column(
        String(_ID_MAX_LEN), nullable=True, index=True
    )
    file_kind: Mapped[str] = mapped_column(
        SAEnum(
            "sample_toml",
            "acquisition_toml",
            "md_run_toml",
            "mdoc",
            "mrc_header",
            "zarr_attrs",
            "frames",
            "filesystem",
            "other",
            name="issue_file_kind",
        ),
        nullable=False,
    )
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    first_seen_at: Mapped[float] = mapped_column(Float, nullable=False)
    first_seen_run_id: Mapped[str] = mapped_column(String, nullable=False)
    last_seen_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_seen_run_id: Mapped[str] = mapped_column(String, nullable=False)
    resolved_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_run_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_issues_resolved_severity", "resolved_at", "severity"),
    )


class SampleScanStatusORM(Base):
    """1:1 per-sample freshness rollup (Priority 2 current state).

    Records when a sample was last scanned (upsert OR skip) vs last actually
    changed (upsert only), plus its last outcome and run. Kept as a side table
    so ``SampleORM`` stays a clean Pydantic-schema mirror; joined into the
    ``/samples/{id}`` detail endpoint.
    """

    __tablename__ = "sample_scan_status"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    last_scanned_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_changed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_outcome: Mapped[str] = mapped_column(
        SAEnum("upserted", "skipped", "failed", name="sample_scan_outcome"),
        nullable=False,
    )
    last_scan_run_id: Mapped[str] = mapped_column(String, nullable=False)


class AcquisitionScanStatusORM(Base):
    """1:1 per-acquisition freshness + thumbnail provenance (Priority 2).

    Records per-acquisition freshness (derived from the parent sample's
    outcome) and the thumbnail's real rendered source, generated-at, and
    status. Kept as a side table so ``AcquisitionORM`` stays a clean
    Pydantic-schema mirror; joined into the acquisition detail endpoint.
    """

    __tablename__ = "acquisition_scan_status"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
    )
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN))
    last_scanned_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_changed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_outcome: Mapped[str] = mapped_column(
        SAEnum("upserted", "skipped", "failed", name="acquisition_scan_outcome"),
        nullable=False,
    )
    last_scan_run_id: Mapped[str] = mapped_column(String, nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_source_kind: Mapped[str | None] = mapped_column(
        SAEnum("zarr", "st", "frames", "none", name="thumbnail_source_kind"),
        nullable=True,
    )
    thumbnail_source_path: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_generated_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_status: Mapped[str | None] = mapped_column(
        SAEnum(
            "ok", "missing_source", "render_failed", name="thumbnail_status"
        ),
        nullable=True,
    )

    __table_args__ = (PrimaryKeyConstraint("sample_id", "acquisition_id"),)


class ScanStateORM(Base):
    __tablename__ = "scan_state"

    path: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
        index=True,
    )
    mtime: Mapped[float] = mapped_column(Float, nullable=False)
    last_scanned: Mapped[float] = mapped_column(Float, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class CatalogMetaORM(Base):
    __tablename__ = "catalog_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_root: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (CheckConstraint("id = 1", name="catalog_meta_singleton"),)
