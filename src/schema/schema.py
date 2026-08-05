"""Pydantic schema for CryoET + AI sample metadata.

Covers every field in docs/schema.md. Fields are grouped by authoritative source within each class:

- sample.toml / acquisition.toml — researcher-authored; required on ingest only for ``sample.project`` (``sample.data_source`` is directory-derived, not authored).
- MDOC — parsed from ``.mdoc`` files under each acquisition's ``Frames/``.
- MRC header — read from tomogram ``.mrc`` headers.
- OME-Zarr .zattrs — read from multiscale ``.ome.zarr`` arrays.
- frame extension — ``.eer`` / ``.tiff`` implies camera family.
- directory — implicit from sample / acquisition / processing folder names. Entity IDs (``sample_id``, ``acquisition_id``, ``tomogram_id``, ``annotation_id``) carry the folder name. For tomograms and annotations the TOML-authored ``id`` field is accepted as an alias for the same value; for samples and acquisitions the IDs are injected on load from the directory structure.
- derived — computed on ingest from other fields.

All auto-derived fields are optional so the validator can load a TOML-only
sample directory before the ingest pipeline has run. Unknown fields are
preserved (``extra='allow'``) and reported as warnings rather than errors.
"""

from __future__ import annotations

import datetime as _dt
import re as _re
import warnings as _warnings
from enum import Enum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from rapidfuzz import fuzz, process

_TYPO_SCORE_CUTOFF = 80

# Identity fields (sample_id, acquisition_id, tomogram_id, annotation_id) become
# DB primary keys and live inside path strings, URLs, and shell commands, so we
# restrict them to a conservative, cross-platform-safe allowlist.
_ID_MAX_LEN = 128
_ID_PATTERN = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _validate_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("id must be a string")
    if not value:
        raise ValueError("id must not be empty")
    if len(value) > _ID_MAX_LEN:
        raise ValueError(f"id must be at most {_ID_MAX_LEN} characters")
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError(
            "id must start with [A-Za-z0-9] and contain only letters, digits, "
            "'.', '_', or '-' (no spaces, slashes, or other punctuation)"
        )
    if value.endswith((".", "-")):
        raise ValueError("id must not end with '.' or '-'")
    if ".." in value:
        raise ValueError("id must not contain '..'")
    if value.upper() in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"id '{value}' is a reserved name on Windows")
    return value


IdStr = Annotated[str, AfterValidator(_validate_id)]


def _case_insensitive_duplicates(values, label: str) -> list[str]:
    """Return error strings for any case-insensitive collisions among `values`."""
    seen: dict[str, str] = {}
    problems: list[str] = []
    for v in values:
        key = v.casefold()
        if key in seen:
            if seen[key] == v:
                problems.append(f"duplicate {label} '{v}'")
            else:
                problems.append(
                    f"{label} '{v}' collides case-insensitively with '{seen[key]}'"
                )
        else:
            seen[key] = v
    return problems


def _duplicates_per_group(entities, id_attr: str, label: str) -> list[str]:
    """Case-insensitive duplicate ids, checked within each alignment group.

    ``entities`` carry ``reconstruction_alignment_id`` (None for blocks authored
    in acquisition.toml, which the assembler has not yet scoped to a group).
    """
    by_group: dict[str | None, list[str]] = {}
    for e in entities:
        by_group.setdefault(e.reconstruction_alignment_id, []).append(
            getattr(e, id_attr)
        )
    problems: list[str] = []
    for group in sorted(by_group, key=lambda g: g or ""):
        problems.extend(_case_insensitive_duplicates(by_group[group], label))
    return problems


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @model_validator(mode="after")
    def _warn_extra_field_typos(self):
        extras = self.model_extra or {}
        if not extras:
            return self
        known: set[str] = set()
        for fname, finfo in type(self).model_fields.items():
            known.add(fname)
            if finfo.alias:
                known.add(finfo.alias)
        known -= set(extras)
        if not known:
            return self
        for name in extras:
            match = process.extractOne(
                name, known, scorer=fuzz.ratio, score_cutoff=_TYPO_SCORE_CUTOFF
            )
            if match is None:
                continue
            suggestion, score, _ = match
            _warnings.warn(
                f"extra field '{name}' on {type(self).__name__} "
                f"closely matches known field '{suggestion}' "
                f"(similarity {score:.0f}); possible typo",
                UserWarning,
                stacklevel=2,
            )
        return self


class LabName(str, Enum):
    collepardo = "collepardo"
    gouaux = "gouaux"
    rosen = "rosen"
    villa = "villa"


class DataSource(str, Enum):
    experimental = "experimental"
    simulation = "simulation"


class Project(str, Enum):
    chromatin = "chromatin"
    synapse = "synapse"
    nanogold = "nanogold"


class DatasetType(str, Enum):
    bulk = "bulk"
    single_molecule = "single_molecule"
    slab = "slab"


# Acquistion quality: a constrained 1-5 integer (5 Excellent … 1 Low).
# Characterizes the quality an acquisition (alignability +
# projection-image survival). The 5->1 rubric is documentation-only (template
# comment + docs/schema.md); the schema enforces only the integer range. A
# constrained int (not an IntEnum) so the ORM maps it to Integer (see
# tests/catalog/test_orm_drift.py).
AcquistionQuality = Annotated[int, Field(ge=1, le=5)]


class Sample(_Base):
    # directory (sample folder name, injected on load)
    sample_id: IdStr | None = None
    # sample.toml ([sample]) — scan-time directive, not stored (§08c): names
    # the prior sample_id this directory was renamed from, so the scanner can
    # migrate continuity + suppress the false deletion event instead of
    # reading the rename as delete-old + add-new. Excluded from the ORM
    # mirror — see tests/catalog/test_orm_drift.py's directive_only carve-out.
    renamed_from: str | None = None
    # directory (top-level arm: Experimental/ -> experimental,
    # MdSimulation/<SubDir>/ -> simulation). Derived from the path by the
    # scanner / loader (infer_arm) and no longer authored in sample.toml;
    # Optional so a flat/legacy dir validated outside the arm layout still
    # loads. NOT NULL in the DB (always set on the scan path).
    data_source: DataSource | None = None
    # sample.toml ([sample])
    project: Project
    lab_name: LabName | None = None
    type: str | None = None
    cell_type: str | None = None
    description: str | None = None
    # directory (sample directory; surfaced for the UI's copy-path /
    # open-in-file-browser buttons — works even for samples with no
    # acquisitions)
    path: str | None = None


class Simulation(_Base):
    # Derived from the top-level directory (MdSimulation/<SubDir>/) by the
    # scanner / loader's infer_arm; no longer researcher-authored.
    dataset_type: DatasetType | None = None


class Chromatin(_Base):
    # sample.toml ([chromatin])
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
    # derived (sequence_footprint - 1; computed on ingest)
    linker_length_fraction: float | None = None


class Label(_Base):
    label_target: str | None = None
    aunp_type: str | None = None
    aunp_size_nm: float | list[float] | None = None
    conjugation: str | None = None
    conjugation_target: str | None = None
    fluorophore: str | None = None
    notes: str | None = None


class Fiducial(_Base):
    aunp_size_nm: float | None = None
    vendor: str | None = None
    catalog_number: str | None = None
    product_name: str | None = None
    concentration_value: float | None = None
    concentration_unit: str | None = None


class Freezing(_Base):
    grid_type: str | None = None
    solution_type: str | None = None
    cryoprotectant: str | None = None
    method: str | None = None
    planchette_size: str | None = None
    spacer_thickness: str | None = None


class Milling(_Base):
    scheme: str | None = None
    date: _dt.date | None = None
    quality: str | None = None


class MdRun(_Base):
    # directory (folder name = md_run_id); one md_run.toml per run under
    # {sample_dir}/MdRuns/{id}/md_run.toml. The `id` is injected from the
    # folder name by the loader, not authored in TOML. Simulation data only.
    md_run_id: IdStr = Field(alias="id")
    seed: int | None = None
    sample_time: float | None = None       # total simulated time
    timestep: float | None = None          # integration timestep
    computer: str | None = None
    reference_contact: str | None = None   # "reference or contact"
    force_field_version: str | None = None


class Acquisition(_Base):
    # directory (acquisition folder name, injected on load)
    acquisition_id: IdStr | None = None
    # acquisition.toml ([acquisition]) — scan-time directive, not stored
    # (§08c); see Sample.renamed_from.
    renamed_from: str | None = None
    # acquisition.toml ([acquisition])
    resolution: float | None = None          # angstrom
    tilt_spacing: float | None = None        # degrees
    defocus_range: str | None = None         # micrometres, free-text range
    energy_filter: str | None = None
    phase_plate: bool | None = None
    microscope: str | None = None
    facility: str | None = None              # imaging facility, e.g. "Janelia"
    acquisition_quality: AcquistionQuality | None = None
    # MDOC
    pixel_size: float | None = None          # angstrom
    dose_per_tilt: list[float] | None = None # e/Å² per tilt
    total_dose: float | None = None          # e/Å², summed
    tilt_min: float | None = None            # degrees
    tilt_max: float | None = None            # degrees
    tilt_axis: float | None = None           # degrees
    # full per-image angle list parsed from the Frames/ MDOC; the
    # acquisition-level polar plot reads this (kept whole for fidelity with
    # dose-symmetric / irregular tilt schemes).
    tilt_angles: list[float] | None = None
    defocus_per_image: list[float] | None = None  # micrometres, per tilt
    date_collected: _dt.date | None = None
    voltage: float | None = None             # kV
    energy_filter_slit_width: float | None = None  # eV
    frame_count: int | None = None
    # .eer / .tiff (frame extension)
    camera: str | None = None
    # directory (acquisition directory; surfaced for the UI's copy-path /
    # open-in-file-browser buttons; synthesized acquisitions get the dir
    # the scanner walked)
    path: str | None = None


class RawTomogram(_Base):
    # directory / acquisition.toml [[raw_tomogram]] (file stem = tomogram_id = TOML `id`)
    tomogram_id: IdStr = Field(alias="id")
    # The enclosing Reconstructions/{id}/ folder. Path-injected by the
    # assembler, never authored — the folder the file lives under IS the
    # group. Part of the storage key, so two groups may share a file stem.
    reconstruction_alignment_id: IdStr | None = None
    # scan-time directive, not stored (§08c); see Sample.renamed_from.
    renamed_from: str | None = None
    pipeline: str | None = None
    software: str | None = None
    # id of the [[tilt_series]] (in this acquisition) this reconstruction was
    # built from; validated against the acquisition's tilt-series ids in
    # AcquisitionFile._check_cross_refs. Authored (a raw tomogram derives
    # directly from one tilt series, not from another tomogram).
    derived_from: IdStr | None = None
    # MRC header
    image_size_x: int | None = None
    image_size_y: int | None = None
    image_size_z: int | None = None
    voxel_size: float | None = None                   # angstrom; from MRC header voxel_size.x
    # directory (prescribed layout)
    mrc_path: str | None = None
    zarr_path: str | None = None
    # OME-Zarr .zattrs
    zarr_axes: str | None = None
    zarr_scale: list[float] | None = None


class PostProcessedTomogram(_Base):
    # directory / acquisition.toml [[post_processed_tomogram]] (file stem = tomogram_id = TOML `id`)
    tomogram_id: IdStr = Field(alias="id")
    # The enclosing Reconstructions/{id}/ folder. Path-injected by the
    # assembler, never authored — the folder the file lives under IS the
    # group. Part of the storage key, so two groups may share a file stem.
    reconstruction_alignment_id: IdStr | None = None
    # scan-time directive, not stored (§08c); see Sample.renamed_from.
    renamed_from: str | None = None
    denoising_software: str | None = None
    ctf_software: str | None = None
    missing_wedge_software: str | None = None
    # id(s) of the tomogram(s) (raw or post-processed, in this acquisition)
    # this was derived from; validated in AcquisitionFile._check_cross_refs.
    derived_from: list[IdStr] = Field(default_factory=list)
    # MRC header
    image_size_x: int | None = None
    image_size_y: int | None = None
    image_size_z: int | None = None
    voxel_size: float | None = None                   # angstrom; from MRC header voxel_size.x
    # directory (prescribed layout)
    mrc_path: str | None = None
    zarr_path: str | None = None
    # OME-Zarr .zattrs
    zarr_axes: str | None = None
    zarr_scale: list[float] | None = None
    # filesystem (recorded by scanner via os.stat at parse time; powers
    # home-page size stats and per-card size badges)
    size_bytes: int | None = None


class Annotation(_Base):
    # directory / acquisition.toml [[annotation]] (file stem = annotation_id = TOML `id`)
    annotation_id: IdStr = Field(alias="id")
    # The enclosing Reconstructions/{id}/ folder. Path-injected by the
    # assembler, never authored — the folder the file lives under IS the
    # group. Part of the storage key, so two groups may share a file stem.
    reconstruction_alignment_id: IdStr | None = None
    # scan-time directive, not stored (§08c); see Sample.renamed_from.
    renamed_from: str | None = None
    type: str | None = None
    # Optional per-annotation lineage links. An annotation still belongs to the
    # whole Reconstructions/{reconstruction_alignment_id}/ group (structural, via
    # the folder it lives under), but may additionally name a specific sibling it
    # was derived from / relates to.
    # tomogram_id (in this group) the annotation was derived from.
    derived_from: str | None = None
    # annotation_id (another file under Annotations/) holding the bounding box
    # this annotation is associated with.
    bounding_box: str | None = None
    # directory scan (artifacts discovered in the annotation folder)
    files: list[str] = Field(default_factory=list)


class TiltSeries(_Base):
    """One tilt series within an acquisition (composite-PK child of Acquisition).

    Composite primary key: ``(sample_id, acquisition_id, tilt_series_id)``.
    The tilt series is a researcher-authored folder under ``TiltSeries/`` —
    ``tilt_series_id`` is its directory name (accepted as the TOML ``id``
    alias). A tilt series may be stored raw/unaligned or already geometrically
    transformed (``is_aligned``); alignment is folded in as transformation
    parameters rather than a separate entity. The MDOC-derived tilt geometry
    lives on :class:`Acquisition` (one acquisition tilt scheme, shared by all
    its tilt series). All non-PK fields are optional so a tilt series can be
    ingested before disk enrichment runs.
    """

    # composite PK fields (sample_id/acquisition_id path-injected by the
    # scanner; tilt_series_id authored as folder name / TOML ``id``. Optional
    # in Pydantic so partial loads don't blow up but pinned NOT NULL in the DB)
    sample_id: IdStr | None = None
    acquisition_id: IdStr | None = None
    tilt_series_id: IdStr | None = Field(default=None, alias="id")
    # scan-time directive, not stored (§08c); see Sample.renamed_from.
    renamed_from: str | None = None
    # acquisition.toml [[tilt_series]] — authored
    # "Frames" (raw from frames) OR another tilt_series_id in this acquisition.
    derived_from: str | None = None
    is_aligned: bool | None = None
    alignment_software: str | None = None
    alignment_method: str | None = None
    # filesystem (resolved under {ts_id}/stack/)
    st_path: str | None = None
    zarr_path: str | None = None
    # filesystem (alignment artifacts discovered under {ts_id}/alignment/)
    alignment_files: list[str] = Field(default_factory=list)
    # filesystem mtime gating
    mtime: float | None = None


class ReconstructionAlignment(_Base):
    """One 3D-alignment group within an acquisition (composite-PK child of
    Acquisition).

    Composite primary key: ``(sample_id, acquisition_id, reconstruction_alignment_id)``.
    The group is a researcher-authored folder under ``Reconstructions/`` —
    ``reconstruction_alignment_id`` is its directory name (accepted as the
    TOML ``id`` alias). It does NOT have to match any ``tilt_series_id``: a
    tomogram's tilt-series lineage is recorded separately on
    ``RawTomogram.derived_from``. All non-PK fields are optional so a group
    can be ingested before disk enrichment runs.
    """

    # composite PK fields (sample_id/acquisition_id path-injected by the
    # scanner; reconstruction_alignment_id authored as folder name / TOML
    # ``id``. Optional in Pydantic so partial loads don't blow up but pinned
    # NOT NULL in the DB)
    sample_id: IdStr | None = None
    acquisition_id: IdStr | None = None
    reconstruction_alignment_id: IdStr | None = Field(default=None, alias="id")
    # scan-time directive, not stored (§08c); see Sample.renamed_from.
    renamed_from: str | None = None
    # acquisition.toml [[reconstruction_alignment]] — authored
    alignment_software: str | None = None
    alignment_method: str | None = None
    # filesystem (alignment artifacts discovered under {id}/Alignment/)
    alignment_files: list[str] = Field(default_factory=list)
    # filesystem mtime gating
    mtime: float | None = None


class MdSource(_Base):
    # acquisition.toml ([md_source]) — simulation provenance for this acquisition.
    # md_run_id must match an [[md_run]] id in the sample's sample.toml.
    md_run_id: IdStr | None = None
    frame: int | None = None                          # frame/snapshot index


class AcquisitionFile(_Base):
    """Parsed contents of one acquisition.toml.

    ``tilt_series`` is populated by the scanner (from MDOC parsing) rather
    than authored by researchers; the field is included on the schema so
    downstream consumers (DB upsert, API responses, JSON Schema dumps) have
    a stable shape.
    """

    acquisition: Acquisition
    md_source: MdSource | None = None
    raw_tomogram: list[RawTomogram] = Field(default_factory=list)
    post_processed_tomogram: list[PostProcessedTomogram] = Field(default_factory=list)
    annotation: list[Annotation] = Field(default_factory=list)
    tilt_series: list[TiltSeries] = Field(default_factory=list)
    reconstruction_alignment: list[ReconstructionAlignment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_cross_refs(self) -> "AcquisitionFile":
        # Raw and post-processed tomograms share one id namespace:
        # post_processed_tomogram.derived_from may reference either.
        tomograms: list[RawTomogram | PostProcessedTomogram] = [
            *self.raw_tomogram,
            *self.post_processed_tomogram,
        ]
        tomo_ids = {t.tomogram_id for t in tomograms}
        ts_ids = {
            ts.tilt_series_id
            for ts in self.tilt_series
            if ts.tilt_series_id is not None
        }
        problems: list[str] = []
        # Tomogram/annotation ids are unique within their alignment group, not
        # the whole acquisition: two Reconstructions/{id}/ groups may each hold
        # a "denoised" stem. Authored blocks carry no group (None), so a real
        # duplicate inside one acquisition.toml is still caught.
        problems.extend(_duplicates_per_group(
            tomograms, "tomogram_id", "tomogram id"
        ))
        problems.extend(_duplicates_per_group(
            self.annotation, "annotation_id", "annotation id"
        ))
        problems.extend(_case_insensitive_duplicates(
            (
                ts.tilt_series_id
                for ts in self.tilt_series
                if ts.tilt_series_id is not None
            ),
            "tilt series id",
        ))
        problems.extend(_case_insensitive_duplicates(
            (
                ra.reconstruction_alignment_id
                for ra in self.reconstruction_alignment
                if ra.reconstruction_alignment_id is not None
            ),
            "reconstruction alignment id",
        ))
        # Legacy-only: when the processing log still lives in acquisition.toml,
        # derived_from is checkable here. Under reconstruction.toml these refs
        # span files and are reconciled by the loader after aggregation.
        for t in self.raw_tomogram:
            if t.derived_from is not None and t.derived_from not in ts_ids:
                problems.append(
                    f"tomogram '{t.tomogram_id}' derived_from '{t.derived_from}' "
                    f"does not match any [[tilt_series]] in this acquisition"
                )
        for t in self.post_processed_tomogram:
            for ref in t.derived_from:
                if ref not in tomo_ids:
                    problems.append(
                        f"tomogram '{t.tomogram_id}' derived_from references unknown tomogram '{ref}'"
                    )
        # A tilt series may derive from the literal "Frames" (raw, straight off
        # the frame stack) or from another tilt series in this acquisition.
        for ts in self.tilt_series:
            if ts.derived_from is None or ts.derived_from == "Frames":
                continue
            if ts.derived_from not in ts_ids:
                problems.append(
                    f"tilt_series '{ts.tilt_series_id}' derived_from "
                    f"'{ts.derived_from}' is neither \"Frames\" nor a "
                    f"tilt_series id in this acquisition"
                )
        if problems:
            raise ValueError("; ".join(problems))
        return self


class ReconstructionFile(_Base):
    """Parsed contents of one Reconstructions/{id}/reconstruction.toml.

    ``reconstruction_alignment_id`` is the folder name (path-injected by the
    loader, not authored). Tomogram/annotation ids are the file stems in this
    folder. Cross-file references (raw_tomogram.derived_from -> a tilt_series in
    acquisition.toml; post_processed_tomogram.derived_from -> a tomogram in this
    or another group) are reconciled by the loader after aggregation, not here.
    """

    reconstruction_alignment: ReconstructionAlignment = Field(
        default_factory=ReconstructionAlignment
    )
    raw_tomogram: list[RawTomogram] = Field(default_factory=list)
    post_processed_tomogram: list[PostProcessedTomogram] = Field(default_factory=list)
    annotation: list[Annotation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_local_dupes(self) -> "ReconstructionFile":
        problems: list[str] = []
        problems.extend(_case_insensitive_duplicates(
            (t.tomogram_id for t in (*self.raw_tomogram, *self.post_processed_tomogram)),
            "tomogram id",
        ))
        problems.extend(_case_insensitive_duplicates(
            (a.annotation_id for a in self.annotation), "annotation id"
        ))
        if problems:
            raise ValueError("; ".join(problems))
        return self


class SampleRecord(_Base):
    """Merged sample.toml + every acquisition.toml under the sample directory.

    `acquisitions` is keyed by acquisition directory name (path-injected by the
    validator, not authored in the TOML).
    """

    sample: Sample
    simulation: Simulation | None = None
    chromatin: Chromatin | None = None
    label: list[Label] = Field(default_factory=list)
    fiducial: Fiducial | None = None
    freezing: Freezing | None = None
    milling: Milling | None = None
    md_run: list[MdRun] = Field(default_factory=list)
    acquisitions: dict[str, AcquisitionFile] = Field(default_factory=dict)
    # acquisition id -> reconstruction_alignment_id -> parsed reconstruction.toml
    reconstructions: dict[str, dict[str, ReconstructionFile]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_project_blocks(self) -> "SampleRecord":
        is_synapse = self.sample.project == Project.synapse
        if is_synapse and self.chromatin is not None:
            raise ValueError("sample.project is 'synapse' but a [chromatin] block is present")
        # synapse data is never simulation-derived (ADR-0003): a synapse sample
        # may not declare data_source = simulation, and is held to the same
        # "no simulation-only blocks" rule as an experimental sample.
        if is_synapse and self.sample.data_source == DataSource.simulation:
            raise ValueError(
                "sample.project is 'synapse' but sample.data_source is 'simulation' "
                "(synapse data is never simulation-derived)"
            )
        if self.sample.data_source == DataSource.experimental or is_synapse:
            why = (
                "sample.data_source is 'experimental'"
                if self.sample.data_source == DataSource.experimental
                else "sample.project is 'synapse'"
            )
            if self.simulation is not None:
                raise ValueError(f"{why} but a [simulation] block is present")
            if self.md_run:
                raise ValueError(f"{why} but [[md_run]] block(s) are present")
            acqs_with_md = [
                aid for aid, af in self.acquisitions.items() if af.md_source is not None
            ]
            if acqs_with_md:
                raise ValueError(
                    f"{why} but acquisition(s) {acqs_with_md} have an [md_source] block"
                )
        return self

    @model_validator(mode="after")
    def _check_md_run_id_collisions(self) -> "SampleRecord":
        # Duplicate md_run ids are a sample.toml integrity problem (no single
        # acquisition to blame), so they fail the whole sample, like
        # cross-acquisition name collisions. The acquisition -> md_run
        # *reference* check is a cross-file concern handled per-acquisition in
        # the loader so a dangling ref isolates to that one acquisition.
        problems = _case_insensitive_duplicates(
            (r.md_run_id for r in self.md_run), "md_run id"
        )
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @model_validator(mode="after")
    def _check_acquisition_name_collisions(self) -> "SampleRecord":
        problems = _case_insensitive_duplicates(self.acquisitions.keys(), "acquisition id")
        if problems:
            raise ValueError("; ".join(problems))
        return self
