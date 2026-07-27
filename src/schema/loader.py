"""Library for loading and validating a cryoET sample directory.

The pure-library counterpart of ``schema.validate``. Provides
``load_sample_record(sample_dir)`` which:

- parses ``sample.toml`` and validates it as a ``Sample``;
- parses each ``*/acquisition.toml`` and validates each *independently*
  as an ``AcquisitionFile`` so a single bad acquisition doesn't black-hole
  the rest of the sample (per-acquisition isolation, §4.4.1);
- strips ``"<FILL IN>"`` placeholders to ``None`` before validation,
  collecting their dotted paths into ``warnings``;
- assembles a final ``SampleRecord`` from the ``Sample`` plus successfully
  validated acquisitions;
- walks the assembled record for ``model_extra`` keys and emits one
  ``ExtrasEntry`` per top-level unknown key per visited entity.

The result is a ``LoadResult`` consumed both by the validate CLI
(``schema/validate.py``) and by the catalog scanner downstream.
"""

from __future__ import annotations

import tomllib
import warnings as _warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from rapidfuzz import process

from schema import (
    AcquisitionFile,
    DataSource,
    MdRun,
    ReconstructionFile,
    Sample,
    SampleRecord,
)
from schema.layout import (
    ANNOTATION_FILE_EXTENSIONS,
    TOMOGRAM_FILE_EXTENSIONS,
    entity_ids_in_dir,
    infer_arm,
    sample_id_for,
)


_PLACEHOLDER = "<FILL IN>"

_FOLDER_SUGGEST_CUTOFF = 80


@dataclass
class ExtrasEntry:
    """One top-level unknown key on a validated entity.

    ``entity_type`` is the lowercase table-name string (``"sample"``,
    ``"chromatin"``, ``"label"``, ``"acquisition"``, ``"raw_tomogram"``,
    ``"post_processed_tomogram"``, ``"annotation"``, …). ``entity_pk`` is the parent row's PK as a tuple
    of native Python values (e.g. ``("my_sample",)`` for ``chromatin``,
    ``("my_sample", 2)`` for the third label entry, ``("my_sample",
    "Position_86", "my_tomo")`` for a tomogram). ``key`` is the unknown
    top-level TOML key. ``value`` is the raw Python value Pydantic stored
    on ``model_extra`` (may be a nested dict — inner keys are NOT
    flattened).
    """

    entity_type: str
    entity_pk: tuple
    key: str
    value: Any


@dataclass
class LoadResult:
    """Outcome of ``load_sample_record``.

    ``record`` is ``None`` only when ``sample.toml`` itself is missing,
    unparseable, or fails ``Sample`` validation — i.e. the sample is
    unrecoverable. A bad ``acquisition.toml`` produces a non-``None``
    record with that acquisition absent and its error in
    ``acquisition_errors``.
    """

    record: SampleRecord | None
    sample_errors: list[str] = field(default_factory=list)
    acquisition_errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    extras: list[ExtrasEntry] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────────────


def _format_error_loc(loc: tuple) -> str:
    return ".".join(str(x) for x in loc)


def _strip_placeholders(value: Any, path: str, warnings_out: list[str]) -> Any:
    """Recursively replace ``"<FILL IN>"`` strings with ``None``.

    Walks dicts and lists. Records the dotted ``path`` of every
    replacement into ``warnings_out``. Returns the (possibly mutated)
    value — for dicts/lists the same instance is mutated in place and
    returned for convenience.
    """
    if isinstance(value, dict):
        for k, v in list(value.items()):
            child_path = f"{path}.{k}" if path else str(k)
            value[k] = _strip_placeholders(v, child_path, warnings_out)
        return value
    if isinstance(value, list):
        for i, v in enumerate(value):
            value[i] = _strip_placeholders(v, f"{path}[{i}]", warnings_out)
        return value
    if isinstance(value, str) and value == _PLACEHOLDER:
        warnings_out.append(f"{path}: unfilled <FILL IN> placeholder")
        return None
    return value


def _format_validation_errors(prefix: str, exc: ValidationError) -> list[str]:
    out: list[str] = []
    for err in exc.errors():
        loc = _format_error_loc(err["loc"])
        if prefix and loc:
            out.append(f"{prefix}.{loc}: {err['msg']}")
        elif prefix:
            out.append(f"{prefix}: {err['msg']}")
        else:
            out.append(f"{loc}: {err['msg']}")
    return out


def _md_source_ref_warning(
    acq: AcquisitionFile, valid_md_run_ids: set[str]
) -> str | None:
    """Warning string if the acquisition's ``md_source.md_run_id`` is set but
    matches no ``MdRuns/{id}/`` folder under the sample.

    This is the one reference that crosses files (acquisition.toml ->
    MdRuns/{id}/md_run.toml), so it can't live on ``AcquisitionFile`` and isn't
    enforced at ``SampleRecord`` level (which would fail the whole sample). The
    loader checks it during the per-acquisition pass and downgrades a dangling
    ref to a warning (with a stable ``"dangling md_source ref:"`` prefix the
    assembler categorizes) so a data move mid-migration doesn't break the
    acquisition. The acquisition still validates and is kept.
    """
    src = acq.md_source
    if src is None or src.md_run_id is None:
        return None
    if src.md_run_id not in valid_md_run_ids:
        return (
            f"dangling md_source ref: md_source.md_run_id '{src.md_run_id}' "
            f"does not match any MdRuns/{{id}}/md_run.toml"
        )
    return None


def _format_extras_location(entry: ExtrasEntry) -> str:
    """Flatten an ExtrasEntry to a human-readable path.

    Used by the validate CLI for warning printing and by the loader
    itself when emitting per-entry "extra field at" warnings.
    """
    et = entry.entity_type
    pk = entry.entity_pk
    if et == "sample":
        return "sample"
    if et in ("chromatin", "synapse", "simulation", "freezing", "milling"):
        return et
    if et == "label":
        # entity_pk = (sample_id, index)
        return f"label[{pk[1]}]"
    if et == "md_run":
        # entity_pk = (sample_id, md_run_id)
        return f"md_run[{pk[1]}]"
    if et == "acquisition":
        # entity_pk = (sample_id, acq_id)
        return f"acquisitions.{pk[1]}.acquisition"
    if et == "md_source":
        # entity_pk = (sample_id, acq_id)
        return f"acquisitions.{pk[1]}.md_source"
    if et == "raw_tomogram":
        # entity_pk = (sample_id, acq_id, tomogram_id)
        return f"acquisitions.{pk[1]}.raw_tomogram[{pk[2]}]"
    if et == "post_processed_tomogram":
        # entity_pk = (sample_id, acq_id, tomogram_id)
        return f"acquisitions.{pk[1]}.post_processed_tomogram[{pk[2]}]"
    if et == "annotation":
        # entity_pk = (sample_id, acq_id, annotation_id)
        return f"acquisitions.{pk[1]}.annotation[{pk[2]}]"
    if et == "tilt_series":
        # entity_pk = (sample_id, acq_id, tilt_series_id)
        return f"acquisitions.{pk[1]}.tilt_series[{pk[2]}]"
    if et == "reconstruction_alignment":
        # entity_pk = (sample_id, acq_id, reconstruction_alignment_id)
        return f"acquisitions.{pk[1]}.reconstruction_alignment[{pk[2]}]"
    return et


# ── id ↔ disk cross-check ─────────────────────────────────────────────────────


def _reconstruction_ids_on_disk(
    acq_dir: Path, leaf: str, file_extensions: frozenset[str]
) -> set[str]:
    """Return every on-disk entity id under ``Reconstructions/*/{leaf}/``.

    ``leaf`` is ``"Tomograms"`` or ``"Annotations"``. Tomograms and annotations
    are **files** whose id is the stem (:func:`schema.layout.entity_id_from_path`);
    only children matching ``file_extensions`` (or a ``.zarr`` / ``.ome.zarr``
    dir) count. Both arms nest the same way — one ``{reconstruction_alignment_id}/``
    folder per 3D-alignment group — mirroring
    ``catalog.discovery._reconstruction_leaf_dirs`` so the loader and scanner agree.
    """
    recon = acq_dir / "Reconstructions"
    ids: set[str] = set()
    if not recon.is_dir():
        return ids
    for group_dir in sorted(recon.iterdir()):
        if not group_dir.is_dir():
            continue
        ids.update(entity_ids_in_dir(group_dir / leaf, file_extensions))
    return ids


def _tilt_series_ids_on_disk(acq_dir: Path) -> set[str]:
    """Return the tilt-series ids (folder names) under ``acq_dir/TiltSeries/``.

    Tilt series remain folders (``TiltSeries/{ts_id}/``); a missing ``TiltSeries``
    contributes nothing.
    """
    ts_root = acq_dir / "TiltSeries"
    if not ts_root.is_dir():
        return set()
    return {child.name for child in ts_root.iterdir() if child.is_dir()}


def _reconstruction_alignment_ids_on_disk(acq_dir: Path) -> set[str]:
    """Return the 3D-alignment group ids (folder names) under
    ``acq_dir/Reconstructions/``. A missing ``Reconstructions`` contributes
    nothing.
    """
    recon = acq_dir / "Reconstructions"
    if not recon.is_dir():
        return set()
    return {child.name for child in recon.iterdir() if child.is_dir()}


def _load_reconstruction_files(
    acq_dir: Path, sample_id: str, acq_id: str, warnings_out: list[str]
) -> dict[str, ReconstructionFile]:
    """Parse each ``Reconstructions/{id}/reconstruction.toml`` independently.

    A bad file (parse error or failed validation) warns and is skipped — it
    never sinks the acquisition (per-group isolation, mirroring the
    per-acquisition isolation above). The group id and the composite keys are
    injected from the path and overwrite anything authored: the folder IS the
    group.
    """
    out: dict[str, ReconstructionFile] = {}
    recon_root = acq_dir / "Reconstructions"
    if not recon_root.is_dir():
        return out
    for group_dir in sorted(p for p in recon_root.iterdir() if p.is_dir()):
        toml_path = group_dir / "reconstruction.toml"
        if not toml_path.is_file():
            continue
        try:
            with toml_path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            warnings_out.append(f"{toml_path}: invalid TOML ({exc})")
            continue
        _strip_placeholders(data, str(toml_path), warnings_out)
        # path-inject the group id + composite keys (never authored)
        ra = data.setdefault("reconstruction_alignment", {})
        ra["id"] = group_dir.name
        ra["sample_id"] = sample_id
        ra["acquisition_id"] = acq_id
        try:
            out[group_dir.name] = ReconstructionFile.model_validate(data)
        except ValidationError as exc:
            warnings_out.extend(_format_validation_errors(str(toml_path), exc))
    return out


def _scrub_dangling_refs(
    acq_model: AcquisitionFile,
    dropped_tomo_ids: set[str],
    dropped_ts_ids: set[str],
) -> None:
    """Clear references to dropped entities from the surviving entries.

    Dropping a folderless tomogram/tilt-series (see
    :func:`_check_id_folder_alignment`) can leave a kept entry pointing at an
    id that no longer exists. The cross-ref validator
    (:meth:`AcquisitionFile._check_cross_refs`) would then reject the whole
    acquisition over a dangling pointer we created — so scrub those refs first.
    """
    for raw in acq_model.raw_tomogram:
        if raw.derived_from in dropped_ts_ids:
            raw.derived_from = None
    for tomo in acq_model.post_processed_tomogram:
        if dropped_tomo_ids and tomo.derived_from:
            tomo.derived_from = [
                r for r in tomo.derived_from if r not in dropped_tomo_ids
            ]
    for ts in acq_model.tilt_series:
        if ts.derived_from in dropped_ts_ids:
            ts.derived_from = None


def _tomo_folder_msg(tomogram_id: str, candidates: list[str]) -> str:
    """"no matching folder" message for a tomogram id, with a fuzzy suggestion.

    Shared by the acquisition.toml check (:func:`_check_id_folder_alignment`)
    and the per-group reconstruction.toml check
    (:func:`_check_reconstruction_files`) so the warning text stays identical.
    """
    msg = (
        f"tomogram[{tomogram_id}]: id has no matching folder under "
        "Reconstructions/{reconstruction_alignment_id}/Tomograms/; the id "
        "must equal a reconstruction file's name without its extension"
    )
    match = process.extractOne(
        tomogram_id, candidates, score_cutoff=_FOLDER_SUGGEST_CUTOFF
    )
    if match:
        msg += f" (did you mean '{match[0]}'?)"
    return msg


def _ann_folder_msg(annotation_id: str, candidates: list[str]) -> str:
    """"no matching folder" message for an annotation id, with a fuzzy suggestion."""
    msg = (
        f"annotation[{annotation_id}]: id has no matching folder under "
        "Reconstructions/{reconstruction_alignment_id}/Annotations/; the id "
        "must equal a reconstruction file's name without its extension"
    )
    match = process.extractOne(
        annotation_id, candidates, score_cutoff=_FOLDER_SUGGEST_CUTOFF
    )
    if match:
        msg += f" (did you mean '{match[0]}'?)"
    return msg


def _check_reconstruction_files(
    acq_dir: Path,
    acq_model: AcquisitionFile,
    recon_files: dict[str, ReconstructionFile],
) -> list[str]:
    """Reconcile each ``Reconstructions/{group}/reconstruction.toml`` against disk
    and against its acquisition.toml, mutating the passed models in place.

    Two checks, both downgraded to warnings (never an error that sinks the
    group), mirroring :func:`_check_id_folder_alignment`:

    1. Each tomogram/annotation id must equal a file's stem in *its own* group
       folder (``Reconstructions/{group}/{Tomograms,Annotations}/``); an
       unmatched entry is dropped and reported with the existing
       "no matching folder" message.
    2. Cross-file ``derived_from`` refs — which span files and are therefore
       deferred by ``ReconstructionFile`` / ``AcquisitionFile`` validation — are
       resolved after aggregation: ``raw_tomogram.derived_from`` against the
       tilt-series ids in acquisition.toml, ``post_processed_tomogram.derived_from``
       against every tomogram id across all groups of this acquisition. A
       dangling ref warns; the entry is kept.
    """
    warnings: list[str] = []
    recon_root = acq_dir / "Reconstructions"

    ts_ids = {
        ts.tilt_series_id
        for ts in acq_model.tilt_series
        if ts.tilt_series_id is not None
    }
    # Pass 1: drop entries with no matching file on disk, per group. The
    # cross-group tomogram-id universe used below must be built from what
    # *survives* this filtering, not from the raw pre-filter contents —
    # otherwise a derived_from ref to a dropped sibling id would pass silently.
    all_tomo_ids: set[str] = set()
    group_prefixes: dict[str, str] = {}
    for group in sorted(recon_files):
        rf = recon_files[group]
        group_dir = recon_root / group
        tomo_on_disk = entity_ids_in_dir(
            group_dir / "Tomograms", TOMOGRAM_FILE_EXTENSIONS
        )
        ann_on_disk = entity_ids_in_dir(
            group_dir / "Annotations", ANNOTATION_FILE_EXTENSIONS
        )
        tomo_candidates = sorted(tomo_on_disk)
        ann_candidates = sorted(ann_on_disk)
        prefix = f"reconstruction_alignment[{group}]."
        group_prefixes[group] = prefix

        kept_raw = []
        for raw in rf.raw_tomogram:
            if raw.tomogram_id in tomo_on_disk:
                kept_raw.append(raw)
                continue
            warnings.append(
                prefix + _tomo_folder_msg(raw.tomogram_id, tomo_candidates)
            )
        rf.raw_tomogram = kept_raw

        kept_post = []
        for tomo in rf.post_processed_tomogram:
            if tomo.tomogram_id in tomo_on_disk:
                kept_post.append(tomo)
                continue
            warnings.append(
                prefix + _tomo_folder_msg(tomo.tomogram_id, tomo_candidates)
            )
        rf.post_processed_tomogram = kept_post

        kept_ann = []
        for ann in rf.annotation:
            if ann.annotation_id in ann_on_disk:
                kept_ann.append(ann)
                continue
            warnings.append(
                prefix + _ann_folder_msg(ann.annotation_id, ann_candidates)
            )
        rf.annotation = kept_ann

        all_tomo_ids.update(t.tomogram_id for t in (*kept_raw, *kept_post))

    # Pass 2: cross-file derived_from, against the post-filter universe.
    for group in sorted(recon_files):
        rf = recon_files[group]
        prefix = group_prefixes[group]
        for raw in rf.raw_tomogram:
            if raw.derived_from is not None and raw.derived_from not in ts_ids:
                warnings.append(
                    f"{prefix}raw_tomogram[{raw.tomogram_id}]: derived_from "
                    f"'{raw.derived_from}' matches no [[tilt_series]] in "
                    "acquisition.toml"
                )
        for tomo in rf.post_processed_tomogram:
            for ref in tomo.derived_from:
                if ref not in all_tomo_ids:
                    warnings.append(
                        f"{prefix}post_processed_tomogram[{tomo.tomogram_id}]: "
                        f"derived_from references unknown tomogram '{ref}'"
                    )
    return warnings


def _drop_authored_group_ids(acq_data: dict) -> None:
    """Discard any hand-authored ``reconstruction_alignment_id`` on a flat
    acquisition.toml tomogram/annotation block, before validation.

    The ``Reconstructions/{id}/`` folder IS the alignment group — the assembler
    derives the value from the path, and the authoring UI never writes it
    (``form_fields.py`` classifies it ``derived``). An authored value must not
    survive into ``AcquisitionFile``: its id-uniqueness check is per group, so
    two blocks declaring the same id under different authored groups would land
    in different buckets and validate, and the assembler — which keys its lookup
    on the id alone — would then stamp one block's metadata onto both folders.
    Dropping it here keeps such a file rejected, as it was before the check
    became group-scoped. To describe a per-group tomogram, put the block in that
    group's ``reconstruction.toml``.
    """
    for key in ("raw_tomogram", "post_processed_tomogram", "annotation"):
        for block in acq_data.get(key) or ():
            if isinstance(block, dict):
                block.pop("reconstruction_alignment_id", None)


def _check_id_folder_alignment(
    acq_dir: Path, acq_model: AcquisitionFile
) -> list[str]:
    """Reconcile declared tomogram/annotation/tilt-series/reconstruction-alignment
    entries against disk, returning one warning message per dropped entry.

    The TOML-authored ``id`` MUST equal the entity's on-disk name — for
    tomograms/annotations the reconstruction file's stem (``foo.mrc`` -> ``foo``),
    for tilt series the ``TiltSeries/{id}/`` folder name, for a 3D-alignment
    group the ``Reconstructions/{id}/`` folder name. A single mismatch used to
    invalidate the *entire* acquisition.toml, which silently discarded unrelated
    valid declarations in the same file (e.g. a tomogram typo would also drop
    correctly-declared tilt series, disabling their previews). Instead we drop
    only the offending entry — keeping its valid siblings — and surface a warning
    so the typo gets fixed without collateral data loss. References to a dropped
    id from surviving entries are scrubbed (:func:`_scrub_dangling_refs`) so the
    cross-ref re-validation doesn't fail the whole sample. A fuzzy suggestion is
    appended when the closest on-disk name is a plausible target.
    """
    warnings: list[str] = []
    dropped_tomo_ids: set[str] = set()
    dropped_ts_ids: set[str] = set()

    tomo_ids_on_disk = _reconstruction_ids_on_disk(
        acq_dir, "Tomograms", TOMOGRAM_FILE_EXTENSIONS
    )
    ann_ids_on_disk = _reconstruction_ids_on_disk(
        acq_dir, "Annotations", ANNOTATION_FILE_EXTENSIONS
    )
    ts_on_disk = _tilt_series_ids_on_disk(acq_dir)
    ra_on_disk = _reconstruction_alignment_ids_on_disk(acq_dir)
    tomo_candidates = sorted(tomo_ids_on_disk)
    ann_candidates = sorted(ann_ids_on_disk)
    ts_candidates = sorted(ts_on_disk)
    ra_candidates = sorted(ra_on_disk)

    # Raw and post-processed tomograms share one id namespace within the
    # acquisition; check both against the same on-disk reconstruction files.
    kept_raw = []
    for raw in acq_model.raw_tomogram:
        if raw.tomogram_id in tomo_ids_on_disk:
            kept_raw.append(raw)
            continue
        warnings.append(_tomo_folder_msg(raw.tomogram_id, tomo_candidates))
        dropped_tomo_ids.add(raw.tomogram_id)
    acq_model.raw_tomogram = kept_raw

    kept_post = []
    for tomo in acq_model.post_processed_tomogram:
        if tomo.tomogram_id in tomo_ids_on_disk:
            kept_post.append(tomo)
            continue
        warnings.append(_tomo_folder_msg(tomo.tomogram_id, tomo_candidates))
        dropped_tomo_ids.add(tomo.tomogram_id)
    acq_model.post_processed_tomogram = kept_post

    kept_ann = []
    for ann in acq_model.annotation:
        if ann.annotation_id in ann_ids_on_disk:
            kept_ann.append(ann)
            continue
        warnings.append(_ann_folder_msg(ann.annotation_id, ann_candidates))
    acq_model.annotation = kept_ann

    kept_ts = []
    for ts in acq_model.tilt_series:
        # tilt_series_id may be None on partial / scanner-pending rows; only
        # the authored folder name is cross-checked against disk.
        if ts.tilt_series_id is None or ts.tilt_series_id in ts_on_disk:
            kept_ts.append(ts)
            continue
        msg = (
            f"tilt_series[{ts.tilt_series_id}]: id has no matching folder under "
            "'TiltSeries'; the id must equal the tilt series' directory name"
        )
        match = process.extractOne(
            ts.tilt_series_id, ts_candidates, score_cutoff=_FOLDER_SUGGEST_CUTOFF
        )
        if match:
            msg += f" (did you mean '{match[0]}'?)"
        warnings.append(msg)
        dropped_ts_ids.add(ts.tilt_series_id)
    acq_model.tilt_series = kept_ts

    kept_ra = []
    for ra in acq_model.reconstruction_alignment:
        if (
            ra.reconstruction_alignment_id is None
            or ra.reconstruction_alignment_id in ra_on_disk
        ):
            kept_ra.append(ra)
            continue
        msg = (
            f"reconstruction_alignment[{ra.reconstruction_alignment_id}]: id has "
            "no matching folder under 'Reconstructions'; the id must equal the "
            "3D-alignment group's directory name"
        )
        match = process.extractOne(
            ra.reconstruction_alignment_id,
            ra_candidates,
            score_cutoff=_FOLDER_SUGGEST_CUTOFF,
        )
        if match:
            msg += f" (did you mean '{match[0]}'?)"
        warnings.append(msg)
    acq_model.reconstruction_alignment = kept_ra

    if dropped_tomo_ids or dropped_ts_ids:
        _scrub_dangling_refs(acq_model, dropped_tomo_ids, dropped_ts_ids)

    return warnings


# ── walker ───────────────────────────────────────────────────────────────────


def _walk_extras(record: SampleRecord) -> list[ExtrasEntry]:
    """Walk ``record`` and emit one ExtrasEntry per top-level unknown key.

    Per-container PK rules per §4.4.1. Reaches into the tomogram /
    ``Annotation.annotation_id`` for the child PK rather than using the
    list index — this is a regression-tested invariant.
    """
    out: list[ExtrasEntry] = []
    sample_id = record.sample.sample_id  # always set by the loader

    # sample
    for k, v in (record.sample.model_extra or {}).items():
        out.append(ExtrasEntry("sample", (sample_id,), k, v))

    # optional 1:1 sub-entities
    for attr in ("chromatin", "simulation", "fiducial", "freezing", "milling"):
        sub = getattr(record, attr)
        if sub is not None:
            for k, v in (sub.model_extra or {}).items():
                out.append(ExtrasEntry(attr, (sample_id,), k, v))

    # label - positional
    for i, label in enumerate(record.label):
        for k, v in (label.model_extra or {}).items():
            out.append(ExtrasEntry("label", (sample_id, i), k, v))

    # md_run - id-keyed (folder name), like tomograms
    for run in record.md_run:
        for k, v in (run.model_extra or {}).items():
            out.append(ExtrasEntry("md_run", (sample_id, run.md_run_id), k, v))

    # acquisitions - dict
    for acq_id, acq_file in record.acquisitions.items():
        # AcquisitionFile.model_extra itself is intentionally NOT walked.
        for k, v in (acq_file.acquisition.model_extra or {}).items():
            out.append(ExtrasEntry("acquisition", (sample_id, acq_id), k, v))
        if acq_file.md_source is not None:
            for k, v in (acq_file.md_source.model_extra or {}).items():
                out.append(
                    ExtrasEntry("md_source", (sample_id, acq_id), k, v)
                )
        for raw in acq_file.raw_tomogram:
            for k, v in (raw.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "raw_tomogram", (sample_id, acq_id, raw.tomogram_id), k, v
                    )
                )
        for tomo in acq_file.post_processed_tomogram:
            for k, v in (tomo.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "post_processed_tomogram",
                        (sample_id, acq_id, tomo.tomogram_id),
                        k,
                        v,
                    )
                )
        for ann in acq_file.annotation:
            for k, v in (ann.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "annotation",
                        (sample_id, acq_id, ann.annotation_id),
                        k,
                        v,
                    )
                )
        for ts in acq_file.tilt_series:
            # ``tilt_series_id`` may legitimately be None on TOML-authored rows
            # (the scanner is the canonical writer); only emit extras when an
            # id is present so the PK tuple is well-formed.
            if ts.tilt_series_id is None:
                continue
            for k, v in (ts.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "tilt_series",
                        (sample_id, acq_id, ts.tilt_series_id),
                        k,
                        v,
                    )
                )
        for ra in acq_file.reconstruction_alignment:
            # same rationale as tilt_series above.
            if ra.reconstruction_alignment_id is None:
                continue
            for k, v in (ra.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "reconstruction_alignment",
                        (sample_id, acq_id, ra.reconstruction_alignment_id),
                        k,
                        v,
                    )
                )
    return out


# ── main entry point ─────────────────────────────────────────────────────────


def load_sample_record(
    sample_dir: Path,
    *,
    data_source: DataSource | None = None,
    dataset_type=None,
) -> LoadResult:
    """Load and validate a sample directory; return a ``LoadResult``.

    ``data_source`` / ``dataset_type`` describe the directory-derived arm
    (``MdSimulation/<SubDir>/`` vs ``Experimental/``). When omitted they are
    derived from ``sample_dir``'s ancestry via ``infer_arm`` so the ``validate``
    CLI — which calls with no kwargs — gets the same arm the scanner assigns.
    The directory is the source of truth: the derived ``data_source`` overrides
    any value authored in ``sample.toml`` (a mismatch surfaces as a warning),
    and the derived ``dataset_type`` is injected into the ``[simulation]`` block.

    Per-acquisition isolation: a bad ``acquisition.toml`` (parse error
    or validation failure) appears in ``acquisition_errors`` and is
    skipped; the rest of the sample still validates and the returned
    ``record.acquisitions`` excludes the bad acquisition.

    ``"<FILL IN>"`` placeholder strings are replaced with ``None``
    before Pydantic validation runs; each replacement emits a warning
    of the form ``"<dotted.path>: unfilled <FILL IN> placeholder"``.
    """
    result = LoadResult(record=None)

    # Derive the arm from the path when not supplied (validate CLI path).
    if data_source is None and dataset_type is None:
        data_source, dataset_type = infer_arm(sample_dir)

    sample_toml = sample_dir / "sample.toml"
    if not sample_toml.is_file():
        result.sample_errors.append(f"missing sample.toml at {sample_toml}")
        return result

    try:
        with sample_toml.open("rb") as f:
            sample_data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        result.sample_errors.append(f"sample.toml: TOML parse error: {e}")
        return result

    # Strip <FILL IN> placeholders from sample.toml before pydantic runs.
    _strip_placeholders(sample_data, "", result.warnings)

    # Inject sample_id from the directory (subdir-namespaced for simulation
    # samples so ids stay unique across MdSimulation/{Bulk,SingleMolecule,Slab};
    # see layout.sample_id_for). Must match discovery's sample_loc.sample_id so
    # the persisted sample row lines up with scan_state/issue rows.
    sample_data.setdefault("sample", {})["sample_id"] = sample_id_for(sample_dir)

    # data_source resolution: the directory is the source of truth and is no
    # longer authored in sample.toml. When the path is under a recognized arm,
    # the directory-derived value is injected; otherwise we fall back to any
    # value still present in a legacy sample.toml (or leave it unset, since the
    # field is now Optional) so out-of-arm `validate` runs still load.
    authored_ds = sample_data["sample"].get("data_source")
    effective_ds = data_source if data_source is not None else authored_ds
    if data_source is not None:
        ds_value = (
            data_source.value
            if isinstance(data_source, DataSource)
            else data_source
        )
        # Directory wins — write it back before validation.
        sample_data["sample"]["data_source"] = ds_value

    # dataset_type injection: the directory (MdSimulation/<SubDir>/) is the
    # source of truth for the simulation dataset_type; researchers no longer
    # author it. Inject before SampleRecord validation.
    if dataset_type is not None:
        sample_data.setdefault("simulation", {})["dataset_type"] = (
            dataset_type.value if hasattr(dataset_type, "value") else dataset_type
        )

    # Validate the sample-level portion. The Sample model only consumes
    # the [sample] table; the rest of sample.toml ([chromatin], [label],
    # etc.) is handled later by SampleRecord.model_validate of the full
    # dict.
    sample_block = sample_data.get("sample", {})
    sample_model: Sample | None = None
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always", UserWarning)
        try:
            sample_model = Sample.model_validate(sample_block)
        except ValidationError as e:
            result.sample_errors.extend(_format_validation_errors("sample", e))
    for w in caught:
        if issubclass(w.category, UserWarning):
            result.warnings.append(str(w.message))

    if sample_model is None:
        return result

    # ── MD runs from MdRuns/{id}/md_run.toml ────────────────────────────────
    # A stale [[md_run]] array in sample.toml is deprecated and ignored; warn
    # so stale TOML doesn't double-count.
    if sample_data.get("md_run"):
        result.warnings.append(
            "[[md_run]] in sample.toml is deprecated and ignored; author "
            "MdRuns/{id}/md_run.toml instead"
        )
    sample_data.pop("md_run", None)

    parsed_md_runs: list[MdRun] = []
    valid_md_run_ids: set[str] = set()
    for md_run_toml in sorted(sample_dir.glob("MdRuns/*/md_run.toml")):
        run_dir = md_run_toml.parent
        run_id = run_dir.name
        # The folder exists, so a ref to it is never dangling — count it even
        # if the md_run.toml itself fails to parse/validate.
        valid_md_run_ids.add(run_id)
        try:
            with md_run_toml.open("rb") as f:
                run_data = tomllib.load(f)
        except tomllib.TOMLDecodeError:
            # A bad md_run.toml records nothing fatal — skip it (its folder
            # still counts toward valid ids above).
            continue
        _strip_placeholders(run_data, f"md_run[{run_id}]", result.warnings)
        run_data["id"] = run_id  # folder = identity
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always", UserWarning)
            try:
                run_model = MdRun.model_validate(run_data)
            except ValidationError:
                run_model = None
        for w in caught:
            if issubclass(w.category, UserWarning):
                result.warnings.append(str(w.message))
        if run_model is not None:
            parsed_md_runs.append(run_model)

    # Per-acquisition: parse, strip placeholders, validate independently.
    # Simulation samples wrap their acquisitions in SyntheticCryoET/, so the
    # acquisition.toml sits one level deeper than the experimental layout.
    if effective_ds == DataSource.simulation or effective_ds == DataSource.simulation.value:
        acq_glob = "SyntheticCryoET/*/acquisition.toml"
    else:
        acq_glob = "*/acquisition.toml"
    validated_acqs: dict[str, AcquisitionFile] = {}
    reconstructions: dict[str, dict[str, ReconstructionFile]] = {}
    for acq_toml in sorted(sample_dir.glob(acq_glob)):
        acq_name = acq_toml.parent.name
        try:
            with acq_toml.open("rb") as f:
                acq_data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            result.acquisition_errors[acq_name] = f"TOML parse error: {e}"
            continue

        _strip_placeholders(
            acq_data, f"acquisitions.{acq_name}", result.warnings
        )
        _drop_authored_group_ids(acq_data)
        acq_data.setdefault("acquisition", {})["acquisition_id"] = acq_name

        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always", UserWarning)
            try:
                acq_model = AcquisitionFile.model_validate(acq_data)
            except ValidationError as e:
                msgs = _format_validation_errors("", e)
                result.acquisition_errors[acq_name] = "; ".join(msgs)
                acq_model = None
        for w in caught:
            if issubclass(w.category, UserWarning):
                result.warnings.append(str(w.message))

        if acq_model is not None:
            # A declared id with no matching folder no longer fails the whole
            # acquisition.toml: the offending entry is dropped (in-place) and
            # reported as a warning, so valid sibling declarations survive.
            # Prefix the acquisition path so the warning's location is
            # unambiguous on the /manage view (one mismatch per acquisition).
            for lw in _check_id_folder_alignment(acq_toml.parent, acq_model):
                result.warnings.append(f"acquisitions.{acq_name}.{lw}")

            # The dangling-md_run-ref check only applies to simulation samples.
            # On experimental samples an md_source block is a category error
            # (no md_runs exist), left for SampleRecord to reject whole-sample
            # with a clear message — don't pre-empt it here with a misleading
            # "no matching md_run" error.
            #
            # A dangling ref (md_run_id with no MdRuns/ folder) is downgraded
            # to a warning so a data move mid-migration doesn't break the
            # acquisition; the acquisition still validates and is kept.
            if sample_model.data_source == DataSource.simulation:
                ref_warning = _md_source_ref_warning(
                    acq_model, valid_md_run_ids
                )
                if ref_warning is not None:
                    result.warnings.append(ref_warning)
            validated_acqs[acq_name] = acq_model

            recon_files = _load_reconstruction_files(
                acq_toml.parent, sample_data["sample"]["sample_id"], acq_name,
                result.warnings,
            )
            # Per-group reconstruction.toml reconciliation: id<->own-folder and
            # cross-file derived_from (both downgraded to warnings).
            for lw in _check_reconstruction_files(
                acq_toml.parent, acq_model, recon_files
            ):
                result.warnings.append(f"acquisitions.{acq_name}.{lw}")
            # Legacy dual-read: a reconstruction group present on disk with no
            # reconstruction.toml, while acquisition.toml still carries the
            # processing-log blocks, is the deprecated layout — warn per group.
            if (
                acq_model.raw_tomogram
                or acq_model.post_processed_tomogram
                or acq_model.annotation
            ):
                for group in sorted(
                    _reconstruction_alignment_ids_on_disk(acq_toml.parent)
                ):
                    if group in recon_files:
                        continue
                    result.warnings.append(
                        f"acquisitions.{acq_name}.reconstruction_alignment"
                        f"[{group}]: processing-log blocks in acquisition.toml "
                        f"are deprecated; move to Reconstructions/{group}/"
                        "reconstruction.toml"
                    )
            if recon_files:
                reconstructions[acq_name] = recon_files

    # Build the full record. Pass already-validated acquisitions through
    # by dumping back to dict (preserves alias round-tripping for the
    # tomogram / annotation `id` alias) and re-validating end-to-end so
    # that SampleRecord-level model validators (project/data_source
    # cross-checks, acquisition-name collisions) run against assembled
    # state.
    merged = {
        **sample_data,
        "acquisitions": {
            acq_id: acq.model_dump(by_alias=True)
            for acq_id, acq in validated_acqs.items()
        },
    }
    merged["sample"] = sample_data["sample"]
    # MD runs now come from MdRuns/{id}/md_run.toml, not sample.toml. Dump the
    # parsed list by_alias so the `id` alias round-trips into SampleRecord.
    merged["md_run"] = [run.model_dump(by_alias=True) for run in parsed_md_runs]

    # Track warnings already captured (sample-block + per-acquisition)
    # so that the final SampleRecord pass — which re-walks the same
    # sub-models — doesn't re-emit duplicates.
    already = set(result.warnings)

    record: SampleRecord | None = None
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always", UserWarning)
        try:
            record = SampleRecord.model_validate(merged)
        except ValidationError as e:
            result.sample_errors.extend(_format_validation_errors("", e))
    for w in caught:
        if not issubclass(w.category, UserWarning):
            continue
        msg = str(w.message)
        if msg in already:
            continue
        result.warnings.append(msg)
        already.add(msg)

    if record is None:
        return result

    record.reconstructions = reconstructions
    result.record = record
    result.extras = _walk_extras(record)

    # Emit a generic "extra field at <loc> (not in schema)" warning for
    # every extras entry that did NOT already produce a typo warning.
    # Matches the post-processing in the old scripts/validate.py
    # (lines 125-130).
    typo_keys = {
        _extract_typo_field(w)
        for w in result.warnings
        if "possible typo" in w
    }
    typo_keys.discard(None)
    for entry in result.extras:
        if entry.key in typo_keys:
            continue
        loc = _format_extras_location(entry)
        result.warnings.append(
            f"extra field '{entry.key}' at '{loc}' (not in schema)"
        )

    return result


def _extract_typo_field(message: str) -> str | None:
    """Pull the unknown field name out of a typo-warning message.

    Messages are formatted as: ``"extra field 'X' on Y closely matches
    known field 'Z' (similarity N); possible typo"``.
    """
    marker = "extra field '"
    if not message.startswith(marker):
        return None
    rest = message[len(marker):]
    end = rest.find("'")
    if end < 0:
        return None
    return rest[:end]
