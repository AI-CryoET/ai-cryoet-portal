"""Assembler: merges parser outputs for one sample into a validated SampleRecord.

Inputs: a SampleLocation. Outputs: AssemblyResult with the merged record, the
list of structured issues (per Q7), any cross-source conflicts, and the
structured extras list (passed through from schema.loader for
persistence).

The assembler is the sole creator of ScanIssue objects; persistence reconciles
them against the stored outstanding-issue set (issues table) per scan run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from schema import (
    Acquisition,
    AcquisitionFile,
    PostProcessedTomogram,
    RawTomogram,
    SampleRecord,
)
from schema.loader import ExtrasEntry

from catalog.discovery import (
    SampleLocation,
    iter_acquisitions,
    iter_annotations,
    iter_reconstruction_alignments,
    iter_tilt_series,
    iter_tomograms,
)
from catalog.parsers.frame_ext import infer_camera
from catalog.parsers.mdoc import parse_acquisition_mdocs
from catalog.parsers.mrc_header import read_mrc_header
from catalog.parsers.ome_zarr import read_zarr_attrs
from catalog.parsers.tilt_series import parse_acquisition_tilt_angles
from catalog.parsers.toml_files import load_sample_toml


ScanIssueCategory = Literal[
    "extra_field",
    "possible_typo",
    "unfilled_placeholder",
    "missing_acquisition_toml",
    "unparseable_acquisition_toml",
    "unparseable_mdoc",
    "unparseable_mrc_header",
    "mrc_header_missing_voxel_size",
    "unparseable_zarr_attrs",
    "ambiguous_frame_extension",
    "undeclared_tomogram_folder",
    "undeclared_annotation_folder",
    "undeclared_tilt_series_folder",
    "undeclared_reconstruction_alignment_folder",
    "acquisition_without_tilt_series",
    "declared_id_without_folder",
    "tilt_series_alignment_mismatch",
    "deprecated_md_run_block",
    "deprecated_processing_log",
    "dangling_md_source_ref",
    "field_conflict",
    "assembly_failed",
    # Run-level (no owning sample) — emitted by the scanner, not the assembler.
    "unknown_md_simulation_subdir",
    "sample_outside_arm",
]

# Backwards-compatible alias for the old name.
ScanWarningCategory = ScanIssueCategory


@dataclass
class ScanIssue:
    severity: str  # "error" | "warning"
    scope: str  # "sample" | "acquisition" | "run"
    category: str
    location: str  # schema path within the file
    message: str
    sample_id: str | None = None
    acquisition_id: str | None = None
    md_run_id: str | None = None
    file_kind: str = "other"
    file_path: str | None = None


@dataclass
class FieldConflict:
    location: str
    category: str
    values: dict[str, Any]
    severity: str = "warning"  # "warning" | "error"


@dataclass
class AssemblyResult:
    record: SampleRecord | None
    warnings: list[ScanIssue] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    conflicts: list[FieldConflict] = field(default_factory=list)
    extras: list[ExtrasEntry] = field(default_factory=list)


_TYPO_LOC_RE = re.compile(r"on (\w+) closely matches")
_EXTRA_AT_RE = re.compile(r"extra field '[^']+' at '([^']+)' \(not in schema\)")
# location prefix "acquisitions.<acq_id>..." → capture the acquisition id.
_ACQ_LOC_RE = re.compile(r"^acquisitions\.([^.\[]+)")
# "md_run[<run_id>]..." (a warning from inside that run's own md_run.toml) or
# "md_source.<run_id>" (a dangling md_source ref naming that run) → the id.
_MD_RUN_LOC_RE = re.compile(r"^md_run\[([^\]]+)\]")
_MD_SOURCE_LOC_RE = re.compile(r"^md_source\.(.+)$")
# parser categories that already carry a concrete file path in file_path.
_PARSER_FILE_KINDS = {
    "unparseable_mdoc": "mdoc",
    "unparseable_mrc_header": "mrc_header",
    "unparseable_zarr_attrs": "zarr_attrs",
    "ambiguous_frame_extension": "frames",
}


def _resolve_file(
    location: str, sample_loc: SampleLocation
) -> tuple[str, str | None, str | None, str | None]:
    """Resolve (file_kind, file_path, acquisition_id, md_run_id) for an issue
    ``location``.

    Uses the known location-prefix conventions:

    - ``"<root>"`` / ``"<unknown>"`` → the sample's ``sample.toml``.
    - ``"acquisitions.{acq}…"`` → that acquisition's ``acquisition.toml`` and
      the acquisition id.
    - ``"md_source.{id}"`` / ``"md_run…"`` → the sample's ``md_run.toml``; the
      run id is recovered when the location names one (``md_run[{id}]…`` from
      inside that run's own file, or ``md_source.{id}`` from a dangling ref) —
      the legacy-block warning (``<root>``) names no single run, so it's None.

    The concrete offending file for parser categories (mdoc/mrc/zarr/frames) is
    not derivable from ``location`` alone, so callers that know it should pass
    ``file_kind``/``file_path`` explicitly; this helper handles the TOML-shaped
    locations.
    """
    sample_dir = sample_loc.path
    m = _ACQ_LOC_RE.match(location)
    if m:
        acq_id = m.group(1)
        return (
            "acquisition_toml",
            str(sample_dir / acq_id / "acquisition.toml"),
            acq_id,
            None,
        )
    if location.startswith("md_source.") or location.startswith("md_run"):
        run_match = _MD_RUN_LOC_RE.match(location) or _MD_SOURCE_LOC_RE.match(location)
        md_run_id = run_match.group(1) if run_match else None
        return ("md_run_toml", str(sample_dir / "md_run.toml"), None, md_run_id)
    # <root>, <unknown>, model-name, or any bare dotted sample-level path.
    return ("sample_toml", str(sample_dir / "sample.toml"), None, None)


def _categorize_loader_warning(
    s: str, sample_loc: SampleLocation
) -> ScanIssue:
    """Convert a loader warning string into a structured ScanIssue.

    The loader's warning strings have stable prefixes (verified in
    ``schema/loader.py``):

    - ``"extra field 'X' on <Model> closely matches known field 'Y' (similarity N); possible typo"``
      -> category ``possible_typo``; location is the model name (or
      ``"<root>"`` if not parseable).
    - ``"extra field 'X' at 'LOC' (not in schema)"``
      -> category ``extra_field``; location parsed out of the message.
    - ``"<dotted.path>: unfilled <FILL IN> placeholder"``
      -> category ``unfilled_placeholder``; location is the dotted path.
    - ``"acquisitions.<acq>.<kind>[<id>]: id has no matching folder …"``
      -> category ``declared_id_without_folder``; location is the prefix
      before the first ``":"`` (the acquisition-qualified entity ref).

    Anything else falls through to ``extra_field`` with ``<unknown>`` location.
    """
    if s.startswith("[[md_run]] in sample.toml is deprecated"):
        category, location = "deprecated_md_run_block", "<root>"
    elif s.startswith("dangling md_source ref:"):
        # Format includes "md_source.md_run_id '<id>' ..." — surface the id.
        m = re.search(r"md_run_id '([^']+)'", s)
        category = "dangling_md_source_ref"
        location = f"md_source.{m.group(1)}" if m else "<root>"
    elif "possible typo" in s:
        m = _TYPO_LOC_RE.search(s)
        category, location = "possible_typo", (m.group(1) if m else "<root>")
    elif "not in schema" in s:
        m = _EXTRA_AT_RE.search(s)
        category, location = "extra_field", (m.group(1) if m else "<unknown>")
    elif "processing-log blocks in acquisition.toml are deprecated" in s:
        # Format: "acquisitions.<acq>.reconstruction_alignment[<group>]: …"
        head, sep, _ = s.partition(":")
        category, location = "deprecated_processing_log", (
            head if sep else "<root>"
        )
    elif "no matching folder" in s or "derived_from" in s:
        # "…: id has no matching folder …" or a cross-file reconstruction.toml
        # derived_from ref that resolves to no tilt_series/tomogram — both are a
        # declared reference with no backing entity, emitted by the same loader
        # reconciliation pass.
        # Format: "acquisitions.<acq>.<kind>[<id>]…: <detail>"
        head, sep, _ = s.partition(":")
        category, location = "declared_id_without_folder", (
            head if sep else "<unknown>"
        )
    elif "unfilled <FILL IN> placeholder" in s:
        # Format: "<path>: unfilled <FILL IN> placeholder"
        head, sep, _ = s.partition(": unfilled <FILL IN> placeholder")
        category, location = "unfilled_placeholder", (
            head if sep else "<unknown>"
        )
    else:
        category, location = "extra_field", "<unknown>"
    return _make_issue(
        sample_loc, category=category, location=location, message=s
    )


def _make_issue(
    sample_loc: SampleLocation,
    *,
    category: str,
    location: str,
    message: str,
    severity: str = "warning",
    file_kind: str | None = None,
    file_path: str | None = None,
) -> ScanIssue:
    """Build a ScanIssue, resolving scope + file attribution from ``location``.

    Scope is ``acquisition`` when ``location`` is acquisition-qualified, else
    ``sample``. ``file_kind``/``file_path`` may be supplied explicitly (parser
    categories that know their concrete offending file); otherwise they are
    derived from the location via :func:`_resolve_file`.
    """
    res_kind, res_path, acq_id, md_run_id = _resolve_file(location, sample_loc)
    scope = "acquisition" if acq_id is not None else "sample"
    return ScanIssue(
        severity=severity,
        scope=scope,
        category=category,
        location=location,
        message=message,
        sample_id=sample_loc.sample_id,
        acquisition_id=acq_id,
        md_run_id=md_run_id,
        file_kind=file_kind if file_kind is not None else res_kind,
        file_path=file_path if file_path is not None else res_path,
    )


def assemble_sample(sample_loc: SampleLocation) -> AssemblyResult:
    """Assemble one sample's discovery + parser outputs into a SampleRecord.

    Implements the per-sample merge:

    1. Load TOML via the schema loader; bail out (record=None) if the sample
       block is unrecoverable.
    1.5. Synthesize empty AcquisitionFile entries for filesystem acquisitions
       that aren't in record.acquisitions (Frames-only or unparseable
       acquisition.toml). Emit categorized warnings.
    2. Per-acquisition: run MDOC + frame-extension parsers; fill in fields
       on the Acquisition Pydantic model that are still None.
    3. Per-tomogram (raw or post-processed): run MRC header + OME-Zarr
       parsers; fill image_size_*, mrc_path, zarr_path, zarr_axes/scale.
       Only PostProcessedTomogram records ``size_bytes`` (raw has no
       size_bytes field in the schema).
    4. Per-annotation: assign sorted file paths from disk discovery onto
       ``Annotation.files``.
    5. Re-validate the populated record via
       ``SampleRecord.model_validate(record.model_dump(by_alias=True))`` to
       catch anything we just violated. On failure, errors are recorded and
       record is set back to None.
    """
    result = AssemblyResult(record=None)

    # ── Step 1: TOML ─────────────────────────────────────────────────────────
    load = load_sample_toml(
        sample_loc.path,
        data_source=sample_loc.data_source,
        dataset_type=sample_loc.dataset_type,
    )

    for w in load.warnings:
        result.warnings.append(_categorize_loader_warning(w, sample_loc))
    result.extras = list(load.extras)

    if load.sample_errors:
        result.errors.extend(load.sample_errors)
        result.warnings.append(
            _make_issue(
                sample_loc,
                category="assembly_failed",
                location="<root>",
                message="; ".join(load.sample_errors),
                severity="error",
            )
        )
        return result
    if load.record is None:
        msg = "loader returned no record and no sample_errors"
        result.errors.append(msg)
        result.warnings.append(
            _make_issue(
                sample_loc,
                category="assembly_failed",
                location="<root>",
                message=msg,
                severity="error",
            )
        )
        return result

    record = load.record

    # ── Step 1.5: synthesize missing/unparseable acquisitions ────────────────
    fs_acquisitions = list(iter_acquisitions(sample_loc))
    record_acq_ids = set(record.acquisitions.keys())

    new_acquisitions = dict(record.acquisitions)
    for acq_loc in fs_acquisitions:
        if acq_loc.acquisition_id in record_acq_ids:
            continue
        if acq_loc.acquisition_id in load.acquisition_errors:
            category = "unparseable_acquisition_toml"
            message = load.acquisition_errors[acq_loc.acquisition_id]
        else:
            category = "missing_acquisition_toml"
            message = f"no acquisition.toml at {acq_loc.path}/acquisition.toml"
        result.warnings.append(
            _make_issue(
                sample_loc,
                category=category,
                location=f"acquisitions.{acq_loc.acquisition_id}",
                message=message,
            )
        )
        synth = AcquisitionFile(
            acquisition=Acquisition(acquisition_id=acq_loc.acquisition_id),
        )
        new_acquisitions[acq_loc.acquisition_id] = synth

    record = record.model_copy(update={"acquisitions": new_acquisitions})

    # Record the sample directory once so sample-level UI actions (copy path,
    # open in Fileglancer) work even for samples with zero acquisitions.
    # Mirrors the per-acquisition path injection below.
    if record.sample.path is None:
        record.sample.path = str(sample_loc.path)

    # ── Steps 2, 3, 4: walk each acquisition ─────────────────────────────────
    MDOC_FIELDS = (
        "pixel_size",
        "voltage",
        "energy_filter_slit_width",
        "date_collected",
        "frame_count",
        "dose_per_tilt",
        "total_dose",
        "tilt_min",
        "tilt_max",
        "tilt_axis",
        "defocus_per_image",
    )

    for acq_loc in fs_acquisitions:
        acq_file = record.acquisitions[acq_loc.acquisition_id]
        acq = acq_file.acquisition

        # Record the acquisition directory once, regardless of whether the
        # acquisition was synthesized or had an acquisition.toml — powers the
        # UI's copy-path / open-in-file-browser buttons.
        if acq.path is None:
            acq.path = str(acq_loc.path)

        # Step 2: MDOC + frame-ext ------------------------------------------
        if acq_loc.frames_dir is not None:
            mdoc_result = parse_acquisition_mdocs(acq_loc.frames_dir)
            if mdoc_result.status == "unreadable":
                result.warnings.append(
                    _make_issue(
                        sample_loc,
                        category="unparseable_mdoc",
                        location=f"acquisitions.{acq_loc.acquisition_id}.Frames",
                        message=mdoc_result.error or "unparseable mdoc",
                        file_kind="mdoc",
                        file_path=str(acq_loc.frames_dir),
                    )
                )
            elif mdoc_result.status == "ok":
                for fname in MDOC_FIELDS:
                    if fname in mdoc_result.fields and getattr(acq, fname, None) is None:
                        setattr(acq, fname, mdoc_result.fields[fname])

            cam_result = infer_camera(acq_loc.frames_dir)
            if cam_result.status == "unreadable":
                result.warnings.append(
                    _make_issue(
                        sample_loc,
                        category="ambiguous_frame_extension",
                        location=f"acquisitions.{acq_loc.acquisition_id}.Frames",
                        message=cam_result.error or "ambiguous frame extension",
                        file_kind="frames",
                        file_path=str(acq_loc.frames_dir),
                    )
                )
            elif cam_result.status == "ok" and acq.camera is None:
                acq.camera = cam_result.fields.get("camera")

            # Acquisition tilt scheme: the full per-image tilt-angle list is a
            # property of the acquisition (shared by all its tilt series), so
            # extract it from the Frames/ MDOC(s) and set it on the
            # acquisition. Handles both the series-level and per-tilt MDOC
            # layouts; MDOC read failures surface as unparseable_mdoc warnings.
            tilt_angle_result = parse_acquisition_tilt_angles(acq_loc.frames_dir)
            for _mdoc_path_str, err_msg in tilt_angle_result.unreadable:
                result.warnings.append(
                    _make_issue(
                        sample_loc,
                        category="unparseable_mdoc",
                        location=f"acquisitions.{acq_loc.acquisition_id}.Frames",
                        message=err_msg,
                        file_kind="mdoc",
                        file_path=_mdoc_path_str or str(acq_loc.frames_dir),
                    )
                )
            if acq.tilt_angles is None and tilt_angle_result.tilt_angles is not None:
                acq.tilt_angles = tilt_angle_result.tilt_angles

        # Tilt-series enrichment: the researcher-authored TiltSeries/{ts_id}/
        # folders are the canonical tilt-series entities. We do NOT synthesize
        # rows from disk — a folder with no [[tilt_series]] block warns. For
        # declared rows, fill filesystem-derived fields (stack paths, alignment
        # artifacts, mtime) and inject the path-derived PK parts.
        existing_ts = {
            ts.tilt_series_id: ts
            for ts in acq_file.tilt_series
            if ts.tilt_series_id is not None
        }
        for ts_loc in iter_tilt_series(acq_loc):
            ts = existing_ts.get(ts_loc.tilt_series_id)
            if ts is None:
                result.warnings.append(
                    _make_issue(
                        sample_loc,
                        category="undeclared_tilt_series_folder",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".tilt_series[{ts_loc.tilt_series_id}]"
                        ),
                        message=(
                            f"folder '{ts_loc.tilt_series_id}' exists on disk but "
                            "is not declared in acquisition.toml — add a "
                            "[[tilt_series]] block with "
                            f"id = \"{ts_loc.tilt_series_id}\""
                        ),
                    )
                )
                continue

            if ts.st_path is None and ts_loc.st_path is not None:
                ts.st_path = str(ts_loc.st_path)
            if ts.zarr_path is None and ts_loc.zarr_path is not None:
                ts.zarr_path = str(ts_loc.zarr_path)
            if not ts.alignment_files and ts_loc.alignment_files:
                ts.alignment_files = sorted(
                    str(p) for p in ts_loc.alignment_files
                )
            if ts.mtime is None:
                try:
                    ts.mtime = ts_loc.path.stat().st_mtime
                except OSError:
                    pass

            # is_aligned cross-check: warn when the authored flag disagrees
            # with the alignment artifacts found on disk (only checkable for a
            # matched folder).
            has_artifacts = bool(ts_loc.alignment_files)
            if ts.is_aligned is True and not has_artifacts:
                result.warnings.append(
                    _make_issue(
                        sample_loc,
                        category="tilt_series_alignment_mismatch",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".tilt_series[{ts_loc.tilt_series_id}]"
                        ),
                        message=(
                            f"tilt series '{ts_loc.tilt_series_id}' is_aligned=true "
                            "but no alignment artifacts found under Alignment/"
                        ),
                    )
                )
            elif not ts.is_aligned and has_artifacts:
                result.warnings.append(
                    _make_issue(
                        sample_loc,
                        category="tilt_series_alignment_mismatch",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".tilt_series[{ts_loc.tilt_series_id}]"
                        ),
                        message=(
                            f"tilt series '{ts_loc.tilt_series_id}' has alignment "
                            "artifacts under Alignment/ but is_aligned is not true"
                        ),
                    )
                )

        # The scanner is the source of the path-derived PK parts; inject them
        # onto every authored tilt-series row regardless of disk matching.
        for ts in acq_file.tilt_series:
            ts.sample_id = acq_loc.sample_id
            ts.acquisition_id = acq_loc.acquisition_id

        # Per-group reconstruction.toml map (acq -> {group -> ReconstructionFile}).
        # Fetched here so the reconstruction-alignment reconciliation below can
        # see the migrated layout too, and reused by Steps 3/4.
        recon_files = record.reconstructions.get(acq_loc.acquisition_id, {})

        # 3D-alignment-group enrichment: the researcher-authored
        # Reconstructions/{id}/ folders are the canonical groups. We do NOT
        # synthesize rows from disk — a folder with no declaration warns. For
        # declared rows, fill filesystem-derived fields (alignment artifacts,
        # mtime) and inject the path-derived PK parts. Migrated layout: the
        # [reconstruction_alignment] block lives in each group's
        # reconstruction.toml (record.reconstructions), NOT in acquisition.toml
        # — fold those in so the group folders match and the in-place enrichment
        # persists on the ReconstructionFile object.
        existing_ra = {
            ra.reconstruction_alignment_id: ra
            for ra in acq_file.reconstruction_alignment
            if ra.reconstruction_alignment_id is not None
        }
        for group, rf in recon_files.items():
            existing_ra.setdefault(group, rf.reconstruction_alignment)
        for ra_loc in iter_reconstruction_alignments(acq_loc):
            ra = existing_ra.get(ra_loc.reconstruction_alignment_id)
            if ra is None:
                result.warnings.append(
                    _make_issue(
                        sample_loc,
                        category="undeclared_reconstruction_alignment_folder",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".reconstruction_alignment"
                            f"[{ra_loc.reconstruction_alignment_id}]"
                        ),
                        message=(
                            f"folder '{ra_loc.reconstruction_alignment_id}' exists "
                            "on disk but is not declared — add a "
                            "Reconstructions/"
                            f"{ra_loc.reconstruction_alignment_id}/reconstruction.toml "
                            "(or a [[reconstruction_alignment]] block with "
                            f"id = \"{ra_loc.reconstruction_alignment_id}\" in "
                            "acquisition.toml)"
                        ),
                    )
                )
                continue

            if not ra.alignment_files and ra_loc.alignment_files:
                ra.alignment_files = sorted(str(p) for p in ra_loc.alignment_files)
            if ra.mtime is None:
                try:
                    ra.mtime = ra_loc.path.stat().st_mtime
                except OSError:
                    pass

        for ra in acq_file.reconstruction_alignment:
            ra.sample_id = acq_loc.sample_id
            ra.acquisition_id = acq_loc.acquisition_id

        # An acquisition with raw imaging data (Frames/) but no declared tilt
        # series is half-ingested: a thumbnail still renders from Frames/, but
        # the detail pages have no tilt_series_id to key the preview/lightbox
        # on, so the hero image silently disappears (tables, which build the
        # cached-thumbnail URL directly, still show one). Surface it so these
        # (typically SerialEM raw-collection) acquisitions are visible on the
        # /manage view instead of only manifesting as a missing image.
        if acq_loc.frames_dir is not None and not acq_file.tilt_series:
            result.warnings.append(
                _make_issue(
                    sample_loc,
                    category="acquisition_without_tilt_series",
                    location=f"acquisitions.{acq_loc.acquisition_id}",
                    message=(
                        f"acquisition '{acq_loc.acquisition_id}' has a Frames/ "
                        "directory but no declared tilt series — add a "
                        "[[tilt_series]] block to acquisition.toml so its "
                        "tilt-series preview image is available"
                    ),
                )
            )

        # Step 3: tomograms (raw + post share one id namespace) -------------
        # Per-group sourcing: when a Reconstructions/{group}/ carries a
        # reconstruction.toml, its tomogram/annotation metadata lives in
        # record.reconstructions[acq][group] and is matched to files by stem
        # WITHIN that group. Groups with no reconstruction.toml fall back to the
        # legacy flat acquisition.toml blocks, matched by stem globally.
        # (recon_files fetched above, before the reconstruction-alignment loop.)
        existing_tomos: dict[str, RawTomogram | PostProcessedTomogram] = {}
        for t in acq_file.raw_tomogram:
            existing_tomos[t.tomogram_id] = t
        for t in acq_file.post_processed_tomogram:
            existing_tomos[t.tomogram_id] = t

        for tomo_loc in iter_tomograms(acq_loc):
            group = tomo_loc.reconstruction_alignment_id
            rf = recon_files.get(group)
            if rf is not None:
                tomo = next(
                    (
                        t
                        for t in (*rf.raw_tomogram, *rf.post_processed_tomogram)
                        if t.tomogram_id == tomo_loc.tomogram_id
                    ),
                    None,
                )
            else:
                # Legacy acquisition.toml path: one authored block can describe a
                # stem that exists in several groups. Copy per group so the
                # enrichment below cannot write group B's header onto group A's
                # model — they are distinct tomograms sharing a name. The
                # group-less originals are dropped after the loop.
                declared = existing_tomos.get(tomo_loc.tomogram_id)
                tomo = declared.model_copy(deep=True) if declared is not None else None
                if isinstance(tomo, RawTomogram):
                    acq_file.raw_tomogram.append(tomo)
                elif tomo is not None:
                    acq_file.post_processed_tomogram.append(tomo)
            if tomo is None:
                # Tomogram file on disk with no metadata block. v1 does not
                # synthesize tomograms; warn so a forgotten declaration doesn't
                # go unnoticed. Which file the researcher must edit depends on
                # how this group is authored: a group with a reconstruction.toml
                # sources its tomograms only from that file, so telling them to
                # add a flat acquisition.toml block would be wrong — and is
                # actively misleading when they already have one (that block
                # loses to the per-group file and is dropped).
                if rf is not None:
                    message = (
                        f"tomogram '{tomo_loc.tomogram_id}' exists on disk under "
                        f"Reconstructions/{group}/, whose reconstruction.toml does "
                        "not declare it — that file is authoritative for this "
                        "group, so add a [[raw_tomogram]] or "
                        "[[post_processed_tomogram]] block with "
                        f"id = \"{tomo_loc.tomogram_id}\" to "
                        f"Reconstructions/{group}/reconstruction.toml (a flat "
                        "acquisition.toml block for this id is ignored for this "
                        "group — remove it if it is stale)"
                    )
                else:
                    message = (
                        f"tomogram '{tomo_loc.tomogram_id}' exists on disk but is "
                        "not declared in acquisition.toml — add a [[raw_tomogram]] "
                        "or [[post_processed_tomogram]] block with "
                        f"id = \"{tomo_loc.tomogram_id}\""
                    )
                result.warnings.append(
                    _make_issue(
                        sample_loc,
                        category="undeclared_tomogram_folder",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".tomogram[{tomo_loc.tomogram_id}]"
                        ),
                        message=message,
                    )
                )
                continue

            tomo.reconstruction_alignment_id = group

            if tomo_loc.mrc_files:
                mrc_path_str = str(tomo_loc.mrc_files[0])
                # size_bytes only exists on PostProcessedTomogram.
                if (
                    isinstance(tomo, PostProcessedTomogram)
                    and tomo.size_bytes is None
                ):
                    try:
                        tomo.size_bytes = tomo_loc.mrc_files[0].stat().st_size
                    except OSError:
                        pass
                mrc_result = read_mrc_header(tomo_loc.mrc_files[0])
                if mrc_result.status == "unreadable":
                    result.warnings.append(
                        _make_issue(
                            sample_loc,
                            category="unparseable_mrc_header",
                            location=(
                                f"acquisitions.{acq_loc.acquisition_id}"
                                f".tomogram[{tomo_loc.tomogram_id}]"
                            ),
                            message=mrc_result.error or "unparseable mrc",
                            file_kind="mrc_header",
                            file_path=mrc_path_str,
                        )
                    )
                elif mrc_result.status == "ok":
                    if tomo.image_size_x is None:
                        tomo.image_size_x = mrc_result.fields.get("image_size_x")
                    if tomo.image_size_y is None:
                        tomo.image_size_y = mrc_result.fields.get("image_size_y")
                    if tomo.image_size_z is None:
                        tomo.image_size_z = mrc_result.fields.get("image_size_z")
                    # voxel_size is purely header-derived — it is not authored in
                    # any TOML (see refactor 1f3d5ee).
                    header_voxel = mrc_result.fields.get("voxel_spacing_angstrom")
                    tomo.voxel_size = header_voxel
                    # A zero/absent header voxel size (cella=0) is what
                    # mrc-ng-server sees: it then serves a 1 Angstrom default and
                    # the viewer is mis-scaled ~10x. Flag it so the frontend
                    # disables the launch button, and warn the acquisition to
                    # get the header fixed.
                    if not header_voxel:
                        tomo.mrc_voxel_size_missing = True
                        result.warnings.append(
                            _make_issue(
                                sample_loc,
                                category="mrc_header_missing_voxel_size",
                                location=(
                                    f"acquisitions.{acq_loc.acquisition_id}"
                                    f".tomogram[{tomo_loc.tomogram_id}]"
                                ),
                                message=(
                                    f"tomogram '{tomo_loc.tomogram_id}' has no "
                                    "voxel size in its MRC header (cella=0); the "
                                    "Neuroglancer viewer would be mis-scaled and "
                                    "is disabled. Write the voxel size into the "
                                    "MRC header (e.g. re-run the step that emits "
                                    "it, or set it with a header tool) and re-scan."
                                ),
                                file_kind="mrc_header",
                                file_path=mrc_path_str,
                            )
                        )
                if tomo.mrc_path is None:
                    tomo.mrc_path = mrc_path_str

            if tomo_loc.zarr_dirs:
                zarr_path_str = str(tomo_loc.zarr_dirs[0])
                zarr_result = read_zarr_attrs(tomo_loc.zarr_dirs[0])
                if zarr_result.status == "unreadable":
                    result.warnings.append(
                        _make_issue(
                            sample_loc,
                            category="unparseable_zarr_attrs",
                            location=(
                                f"acquisitions.{acq_loc.acquisition_id}"
                                f".tomogram[{tomo_loc.tomogram_id}]"
                            ),
                            message=zarr_result.error or "unparseable zarr",
                            file_kind="zarr_attrs",
                            file_path=zarr_path_str,
                        )
                    )
                elif zarr_result.status == "ok":
                    if tomo.zarr_axes is None:
                        tomo.zarr_axes = zarr_result.fields.get("zarr_axes")
                    if tomo.zarr_scale is None:
                        tomo.zarr_scale = zarr_result.fields.get("zarr_scale")
                if tomo.zarr_path is None:
                    tomo.zarr_path = zarr_path_str

        # The authored blocks were templates for the per-group copies above;
        # only stamped copies should reach storage.
        acq_file.raw_tomogram = [
            t for t in acq_file.raw_tomogram if t.reconstruction_alignment_id
        ]
        acq_file.post_processed_tomogram = [
            t for t in acq_file.post_processed_tomogram
            if t.reconstruction_alignment_id
        ]

        # Step 4: annotation files ------------------------------------------
        # Same per-group sourcing as tomograms.
        existing_anns = {a.annotation_id: a for a in acq_file.annotation}
        for ann_loc in iter_annotations(acq_loc):
            group = ann_loc.reconstruction_alignment_id
            rf = recon_files.get(group)
            if rf is not None:
                ann = next(
                    (
                        a
                        for a in rf.annotation
                        if a.annotation_id == ann_loc.annotation_id
                    ),
                    None,
                )
            else:
                # Legacy path: same per-group copy as tomograms above.
                declared = existing_anns.get(ann_loc.annotation_id)
                ann = declared.model_copy(deep=True) if declared is not None else None
                if ann is not None:
                    acq_file.annotation.append(ann)
            if ann is None:
                # Same per-group vs. flat authoring split as tomograms above.
                if rf is not None:
                    message = (
                        f"annotation '{ann_loc.annotation_id}' exists on disk under "
                        f"Reconstructions/{group}/, whose reconstruction.toml does "
                        "not declare it — that file is authoritative for this "
                        "group, so add an [[annotation]] block with "
                        f"id = \"{ann_loc.annotation_id}\" to "
                        f"Reconstructions/{group}/reconstruction.toml (a flat "
                        "acquisition.toml block for this id is ignored for this "
                        "group — remove it if it is stale)"
                    )
                else:
                    message = (
                        f"annotation '{ann_loc.annotation_id}' exists on disk but is "
                        "not declared in acquisition.toml — add an [[annotation]] "
                        f"block with id = \"{ann_loc.annotation_id}\""
                    )
                result.warnings.append(
                    _make_issue(
                        sample_loc,
                        category="undeclared_annotation_folder",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".annotation[{ann_loc.annotation_id}]"
                        ),
                        message=message,
                    )
                )
                continue

            ann.reconstruction_alignment_id = group
            if not ann.files:
                ann.files = sorted(str(p) for p in ann_loc.files)

        acq_file.annotation = [
            a for a in acq_file.annotation if a.reconstruction_alignment_id
        ]

    # ── Step 5: re-validate ──────────────────────────────────────────────────
    try:
        record = SampleRecord.model_validate(record.model_dump(by_alias=True))
    except Exception as e:  # noqa: BLE001
        msg = f"re-validation failed: {e}"
        result.errors.append(msg)
        result.warnings.append(
            _make_issue(
                sample_loc,
                category="assembly_failed",
                location="<root>",
                message=msg,
                severity="error",
            )
        )
        result.record = None
        return result

    # Fold any cross-source FieldConflicts into structured issues (each carries
    # its own severity); scope/file attribution is resolved from its location.
    for conflict in result.conflicts:
        result.warnings.append(
            _make_issue(
                sample_loc,
                category=conflict.category or "field_conflict",
                location=conflict.location,
                message=f"field conflict: {conflict.values}",
                severity=conflict.severity,
            )
        )

    result.record = record
    return result


__all__ = [
    "AssemblyResult",
    "FieldConflict",
    "ScanIssue",
    "ScanIssueCategory",
    "ScanWarningCategory",  # backwards-compat alias of ScanIssueCategory
    "assemble_sample",
]
