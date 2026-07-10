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
    Sample,
    SampleRecord,
)
from schema.layout import (
    ANNOTATION_FILE_EXTENSIONS,
    TOMOGRAM_FILE_EXTENSIONS,
    entity_ids_in_dir,
    infer_arm,
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
        return f"acquisitions.{pk[1]}.raw_tomogram"
    if et == "post_processed_tomogram":
        # entity_pk = (sample_id, acq_id, tomogram_id)
        return f"acquisitions.{pk[1]}.post_processed_tomogram[{pk[2]}]"
    if et == "annotation":
        # entity_pk = (sample_id, acq_id, annotation_id)
        return f"acquisitions.{pk[1]}.annotation[{pk[2]}]"
    if et == "tilt_series":
        # entity_pk = (sample_id, acq_id, tilt_series_id)
        return f"acquisitions.{pk[1]}.tilt_series[{pk[2]}]"
    return et


# ── id ↔ disk cross-check ─────────────────────────────────────────────────────


def _reconstruction_id_map(
    acq_dir: Path,
    leaf: str,
    file_extensions: frozenset[str],
    *,
    simulation: bool,
) -> dict[str, str | None]:
    """Map each on-disk entity id under ``Reconstructions/{leaf}/`` to the
    ``tilt_series_id`` of its enclosing folder (``None`` on the simulation arm).

    ``leaf`` is ``"Tomograms"`` or ``"Annotations"``. Tomograms and annotations
    are **files** whose id is the stem (:func:`schema.layout.entity_id_from_path`);
    only children matching ``file_extensions`` (or a ``.zarr`` / ``.ome.zarr``
    dir) count. The arm decides nesting, mirroring
    ``catalog.discovery._reconstruction_dirs`` so the loader and scanner agree on
    both membership and the derived tilt_series_id:

    - simulation:   ``Reconstructions/{leaf}/`` (flat)          -> ts_id ``None``
    - experimental: ``Reconstructions/{ts_id}/{leaf}/``          -> ts_id = folder

    A stem appearing under two ``{ts_id}`` folders keeps the first (sorted),
    matching the assembler's duplicate handling.
    """
    recon = acq_dir / "Reconstructions"
    mapping: dict[str, str | None] = {}
    if not recon.is_dir():
        return mapping
    if simulation:
        leaf_dirs: list[tuple[Path, str | None]] = [(recon / leaf, None)]
    else:
        leaf_dirs = [
            (ts_dir / leaf, ts_dir.name)
            for ts_dir in sorted(recon.iterdir())
            if ts_dir.is_dir()
        ]
    for leaf_dir, ts_id in leaf_dirs:
        for entity_id in entity_ids_in_dir(leaf_dir, file_extensions):
            mapping.setdefault(entity_id, ts_id)
    return mapping


def _tilt_series_ids_on_disk(acq_dir: Path) -> set[str]:
    """Return the tilt-series ids (folder names) under ``acq_dir/TiltSeries/``.

    Tilt series remain folders (``TiltSeries/{ts_id}/``); a missing ``TiltSeries``
    contributes nothing.
    """
    ts_root = acq_dir / "TiltSeries"
    if not ts_root.is_dir():
        return set()
    return {child.name for child in ts_root.iterdir() if child.is_dir()}


def _inject_tilt_series_ids(
    acq_model: AcquisitionFile,
    tomo_map: dict[str, str | None],
    declared_ts_ids: set[str],
) -> list[str]:
    """Set each surviving tomogram's ``tilt_series_id`` from its disk location.

    Mirrors the scanner gate (``catalog.assembler`` ~590-610): the path-derived
    value wins over any authored one. Experimental tomograms take the enclosing
    ``Reconstructions/{ts_id}/`` folder — but **only when that id is a declared
    ``[[tilt_series]]``**; otherwise the id is left ``None`` and a warning is
    emitted, because ``AcquisitionFile._check_cross_refs`` RAISES on a
    tilt_series_id with no matching ``[[tilt_series]]`` and the loader re-validates
    the assembled record (an unmatched id would fail the whole sample). Simulation
    tomograms (flat layout, ts_id ``None``) always get ``None``.
    """
    warnings: list[str] = []
    tomograms: list = list(acq_model.post_processed_tomogram)
    if acq_model.raw_tomogram is not None:
        tomograms.append(acq_model.raw_tomogram)
    for tomo in tomograms:
        enclosing = tomo_map.get(tomo.tomogram_id)  # ts folder, None if flat
        authored = tomo.tilt_series_id
        if enclosing is None:
            derived: str | None = None
        elif enclosing in declared_ts_ids:
            derived = enclosing
        else:
            derived = None
            warnings.append(
                f"tomogram[{tomo.tomogram_id}]: lives under "
                f"Reconstructions/{enclosing}/ but no [[tilt_series]] with "
                f'id = "{enclosing}" is declared in acquisition.toml; '
                "tilt_series_id left unset"
            )
        tomo.tilt_series_id = derived
        # Warn when an authored value was overridden — the disk is authoritative.
        if authored is not None and authored != derived and enclosing in declared_ts_ids:
            warnings.append(
                f"tomogram[{tomo.tomogram_id}]: authored tilt_series_id "
                f"'{authored}' overridden by path-derived '{derived}'"
            )
        elif authored is not None and enclosing is None:
            warnings.append(
                f"tomogram[{tomo.tomogram_id}]: authored tilt_series_id "
                f"'{authored}' ignored — no enclosing Reconstructions/"
                "{tilt_series_id}/ folder on disk"
            )
    return warnings


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
    tomograms: list = list(acq_model.post_processed_tomogram)
    if acq_model.raw_tomogram is not None:
        tomograms.append(acq_model.raw_tomogram)
    for tomo in tomograms:
        if dropped_tomo_ids and tomo.derived_from:
            tomo.derived_from = [
                r for r in tomo.derived_from if r not in dropped_tomo_ids
            ]
        if tomo.tilt_series_id in dropped_ts_ids:
            tomo.tilt_series_id = None
    for ann in acq_model.annotation:
        if ann.target_tomogram in dropped_tomo_ids:
            ann.target_tomogram = None
    for ts in acq_model.tilt_series:
        if ts.derived_from in dropped_ts_ids:
            ts.derived_from = None


def _check_id_folder_alignment(
    acq_dir: Path, acq_model: AcquisitionFile, *, simulation: bool
) -> list[str]:
    """Reconcile declared tomogram/annotation/tilt-series entries against disk,
    returning one warning message per dropped entry (plus tilt_series_id notes).

    The TOML-authored ``id`` MUST equal the entity's on-disk name — for
    tomograms/annotations the reconstruction file's stem (``foo.mrc`` -> ``foo``),
    for tilt series the ``TiltSeries/{id}/`` folder name. A single mismatch used
    to invalidate the *entire* acquisition.toml, which silently discarded
    unrelated valid declarations in the same file (e.g. a tomogram typo would
    also drop correctly-declared tilt series, disabling their previews). Instead
    we drop only the offending entry — keeping its valid siblings — and surface a
    warning so the typo gets fixed without collateral data loss. References to a
    dropped id from surviving entries are scrubbed (:func:`_scrub_dangling_refs`)
    so the cross-ref re-validation doesn't fail the whole sample. A fuzzy
    suggestion is appended when the closest on-disk name is a plausible target.

    Finally, surviving tomograms get their ``tilt_series_id`` derived from the
    enclosing ``Reconstructions/{ts_id}/`` folder (:func:`_inject_tilt_series_ids`).
    """
    warnings: list[str] = []
    dropped_tomo_ids: set[str] = set()
    dropped_ts_ids: set[str] = set()

    tomo_map = _reconstruction_id_map(
        acq_dir, "Tomograms", TOMOGRAM_FILE_EXTENSIONS, simulation=simulation
    )
    ann_map = _reconstruction_id_map(
        acq_dir, "Annotations", ANNOTATION_FILE_EXTENSIONS, simulation=simulation
    )
    ts_on_disk = _tilt_series_ids_on_disk(acq_dir)
    tomo_candidates = sorted(tomo_map)
    ann_candidates = sorted(ann_map)
    ts_candidates = sorted(ts_on_disk)

    def _tomo_msg(tomogram_id: str) -> str:
        msg = (
            f"tomogram[{tomogram_id}]: id has no matching folder under "
            "Reconstructions/{tilt_series_id}/Tomograms/ "
            "(Reconstructions/Tomograms/ for simulations); the id must equal a "
            "reconstruction file's name without its extension"
        )
        match = process.extractOne(
            tomogram_id, tomo_candidates, score_cutoff=_FOLDER_SUGGEST_CUTOFF
        )
        if match:
            msg += f" (did you mean '{match[0]}'?)"
        return msg

    # Raw and post-processed tomograms share one id namespace within the
    # acquisition; check both against the same on-disk reconstruction files.
    if (
        acq_model.raw_tomogram is not None
        and acq_model.raw_tomogram.tomogram_id not in tomo_map
    ):
        warnings.append(_tomo_msg(acq_model.raw_tomogram.tomogram_id))
        dropped_tomo_ids.add(acq_model.raw_tomogram.tomogram_id)
        acq_model.raw_tomogram = None

    kept_post = []
    for tomo in acq_model.post_processed_tomogram:
        if tomo.tomogram_id in tomo_map:
            kept_post.append(tomo)
            continue
        warnings.append(_tomo_msg(tomo.tomogram_id))
        dropped_tomo_ids.add(tomo.tomogram_id)
    acq_model.post_processed_tomogram = kept_post

    kept_ann = []
    for ann in acq_model.annotation:
        if ann.annotation_id in ann_map:
            kept_ann.append(ann)
            continue
        msg = (
            f"annotation[{ann.annotation_id}]: id has no matching folder under "
            "Reconstructions/{tilt_series_id}/Annotations/ "
            "(Reconstructions/Annotations/ for simulations); the id must equal a "
            "reconstruction file's name without its extension"
        )
        match = process.extractOne(
            ann.annotation_id, ann_candidates, score_cutoff=_FOLDER_SUGGEST_CUTOFF
        )
        if match:
            msg += f" (did you mean '{match[0]}'?)"
        warnings.append(msg)
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

    if dropped_tomo_ids or dropped_ts_ids:
        _scrub_dangling_refs(acq_model, dropped_tomo_ids, dropped_ts_ids)

    # Derive tilt_series_id on the survivors from their on-disk location.
    declared_ts_ids = {
        ts.tilt_series_id
        for ts in acq_model.tilt_series
        if ts.tilt_series_id is not None
    }
    warnings.extend(_inject_tilt_series_ids(acq_model, tomo_map, declared_ts_ids))

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
        if acq_file.raw_tomogram is not None:
            raw = acq_file.raw_tomogram
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

    # Inject sample_id from the directory name (preserve _minimal_sample
    # behaviour from the old script).
    sample_data.setdefault("sample", {})["sample_id"] = sample_dir.name

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
    simulation = (
        effective_ds == DataSource.simulation
        or effective_ds == DataSource.simulation.value
    )
    if simulation:
        acq_glob = "SyntheticCryoET/*/acquisition.toml"
    else:
        acq_glob = "*/acquisition.toml"
    validated_acqs: dict[str, AcquisitionFile] = {}
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
            for lw in _check_id_folder_alignment(
                acq_toml.parent, acq_model, simulation=simulation
            ):
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
