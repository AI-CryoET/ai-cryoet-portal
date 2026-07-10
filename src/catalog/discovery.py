"""Pure path-walking discovery for the catalog scanner.

No file *contents* are read here — only directory entries and suffixes. Each
layer yields a frozen dataclass describing what was found on disk; the
orchestrator (scanner.py) drives the parsers from these locations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from schema.schema import DataSource, DatasetType
from schema.layout import (
    ANNOTATION_FILE_EXTENSIONS,
    DATASET_TYPE_BY_DIR,
    TOMOGRAM_FILE_EXTENSIONS,
    TOP_LEVEL_EXPERIMENTAL,
    TOP_LEVEL_MD_SIMULATION,
    entity_id_from_path,
    infer_arm,
    is_zarr_dir,
)

# The reconstruction allowlists, entity_id_from_path and is_zarr_dir all come
# from schema.layout — the single source of truth shared with the validate CLI.
REPRESENTATIVE_FRAME_SUFFIXES = frozenset({".eer", ".tiff", ".tif"})


@dataclass(frozen=True)
class SampleLocation:
    path: Path
    sample_id: str
    sample_toml: Path
    data_source: DataSource
    dataset_type: DatasetType | None


@dataclass(frozen=True)
class MdRunLocation:
    path: Path
    md_run_id: str
    md_run_toml: Path


@dataclass(frozen=True)
class AcquisitionLocation:
    path: Path
    sample_id: str
    acquisition_id: str
    acquisition_toml: Path | None
    frames_dir: Path | None
    tilt_series_dir: Path | None
    reconstructions_dir: Path | None
    # The arm decides Reconstructions nesting depth: experimental nests tomograms
    # /annotations under a {tilt_series_id}/ folder, simulation stays flat.
    data_source: DataSource


@dataclass(frozen=True)
class TomogramLocation:
    path: Path
    tomogram_id: str
    mrc_files: tuple[Path, ...]
    zarr_dirs: tuple[Path, ...]
    # Enclosing Reconstructions/{ts_id}/ folder name (experimental); None on the
    # flat simulation arm.
    tilt_series_id: str | None


@dataclass(frozen=True)
class AnnotationLocation:
    path: Path
    annotation_id: str
    files: tuple[Path, ...]
    tilt_series_id: str | None


@dataclass(frozen=True)
class TiltSeriesLocation:
    path: Path
    tilt_series_id: str
    stack_dir: Path | None
    alignment_dir: Path | None
    st_path: Path | None
    zarr_path: Path | None
    alignment_files: tuple[Path, ...]


def dir_size_bytes(path: Path) -> int:
    """Total logical size (bytes) of everything under ``path``, recursively.

    Mirrors aicryoet-tools' approach: walk with os.scandir, sum st_size of
    regular files, do NOT follow symlinks, and silently skip directories we
    can't read (PermissionError / OSError on NFS). Counts all files on disk —
    frames, MDOCs, raw + post tomograms, OME-Zarr chunks, annotations, gain
    refs — not just cataloged ones.
    """
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += dir_size_bytes(Path(entry.path))
                except OSError:
                    continue  # entry vanished / unreadable mid-walk
    except (PermissionError, FileNotFoundError, NotADirectoryError):
        pass
    return total


def _sample_location(sample_dir: Path) -> SampleLocation | None:
    """Build a SampleLocation for ``sample_dir`` if it holds a ``sample.toml``.

    The arm (data_source / dataset_type) is derived from the directory's
    ancestry via ``infer_arm``; returns ``None`` if there is no sample.toml.
    """
    sample_toml = sample_dir / "sample.toml"
    if not sample_toml.is_file():
        return None
    data_source, dataset_type = infer_arm(sample_dir)
    # infer_arm only returns None for paths outside the two-arm layout; the
    # walkers below only call this with a sample dir under a known arm, so
    # data_source is always set here. Guard defensively all the same.
    if data_source is None:
        return None
    return SampleLocation(
        path=sample_dir,
        sample_id=sample_dir.name,
        sample_toml=sample_toml,
        data_source=data_source,
        dataset_type=dataset_type,
    )


def iter_samples(root: Path) -> Iterator[SampleLocation]:
    """Yield SampleLocation for every sample under the two-arm layout.

    - ``root/Experimental/*/sample.toml``        -> (experimental, None)
    - ``root/MdSimulation/{Bulk,SingleMolecule,Slab}/*/sample.toml``
      -> (simulation, <dataset_type>)

    A missing ``Experimental/`` or ``MdSimulation/`` arm simply yields nothing
    for that arm. Unknown subdirectories directly under ``MdSimulation/`` (not
    one of the four dataset-type dirs) are skipped here — they hold no
    cataloguable sample under a known arm. The scanner surfaces them separately
    as run-level warnings via ``iter_unknown_md_subdirs``; this generator stays
    pure and only yields valid sample locations.
    """
    if not root.is_dir():
        return

    # Experimental arm: direct children of Experimental/ with a sample.toml.
    experimental_root = root / TOP_LEVEL_EXPERIMENTAL
    if experimental_root.is_dir():
        for child in sorted(experimental_root.iterdir()):
            if not child.is_dir():
                continue
            loc = _sample_location(child)
            if loc is not None:
                yield loc

    # MdSimulation arm: root/MdSimulation/<SubDir>/<sample>/sample.toml, where
    # <SubDir> is one of the four known dataset-type dirs. Unknown subdirs skip.
    md_root = root / TOP_LEVEL_MD_SIMULATION
    if md_root.is_dir():
        for sub in sorted(md_root.iterdir()):
            if not sub.is_dir():
                continue
            if sub.name not in DATASET_TYPE_BY_DIR:
                # Unknown MdSimulation subdir — skip (no warning channel here).
                continue
            for child in sorted(sub.iterdir()):
                if not child.is_dir():
                    continue
                loc = _sample_location(child)
                if loc is not None:
                    yield loc


def iter_unknown_md_subdirs(root: Path) -> Iterator[Path]:
    """Yield each directory under ``root/MdSimulation/`` that is NOT one of the
    four known dataset-type dirs (``Bulk`` /
    ``SingleMolecule`` / ``Slab``).

    These are the subdirs ``iter_samples`` skips: a simulation sample dropped
    under, say, ``MdSimulation/Foo/`` never gets a ``dataset_type`` and never
    becomes a SampleLocation. Pure path-walking — the scanner turns each result
    into a run-level ScanWarning so operators see the misplaced data.
    """
    md_root = root / TOP_LEVEL_MD_SIMULATION
    if not md_root.is_dir():
        return
    for sub in sorted(md_root.iterdir()):
        if sub.is_dir() and sub.name not in DATASET_TYPE_BY_DIR:
            yield sub


def iter_misplaced_samples(root: Path) -> Iterator[Path]:
    """Yield each sample dir (holds a ``sample.toml``) that sits under a
    top-level directory other than the two recognized arms.

    The canonical layout puts every sample under a known top-level arm
    (``Experimental/{sample}`` or ``MdSimulation/{SubDir}/{sample}``). A sample
    dropped under any *other* top-level directory
    (``root/{other}/{sample}/sample.toml``) is never reached by
    ``iter_samples`` and would silently vanish from the catalog. This generator
    finds those so the scanner can surface a run-level warning. A ``sample.toml``
    sitting directly in such a top-level dir (``root/{other}/sample.toml``) is
    reported too. Pure path-walking; descends at most one level below each
    non-arm top-level dir.
    """
    if not root.is_dir():
        return
    for top in sorted(root.iterdir()):
        if not top.is_dir():
            continue
        if top.name in (TOP_LEVEL_EXPERIMENTAL, TOP_LEVEL_MD_SIMULATION):
            continue
        # A sample dropped directly under the non-arm dir.
        if (top / "sample.toml").is_file():
            yield top
            continue
        # ... or one level down: root/{other}/{sample}/sample.toml.
        for child in sorted(top.iterdir()):
            if child.is_dir() and (child / "sample.toml").is_file():
                yield child


def iter_md_runs(sample: SampleLocation) -> Iterator[MdRunLocation]:
    """Yield one MdRunLocation per ``{sample}/MdRuns/*/`` holding an md_run.toml.

    The folder name is the ``md_run_id`` (the TOML ``id`` is injected from it
    by the loader). Folders without an ``md_run.toml`` are skipped.
    """
    md_runs_dir = sample.path / "MdRuns"
    if not md_runs_dir.is_dir():
        return
    for child in sorted(md_runs_dir.iterdir()):
        if not child.is_dir():
            continue
        md_run_toml = child / "md_run.toml"
        if md_run_toml.is_file():
            yield MdRunLocation(
                path=child,
                md_run_id=child.name,
                md_run_toml=md_run_toml,
            )


def iter_acquisitions(sample: SampleLocation) -> Iterator[AcquisitionLocation]:
    """Yield AcquisitionLocation for each acquisition under the sample.

    For simulation samples the acquisitions are nested one level deeper, under
    ``{sample}/SyntheticCryoET/{acq}/`` (matching the loader's glob); for
    experimental samples they are direct children of the sample dir. In either
    case an acquisition dir qualifies if it has an ``acquisition.toml`` OR a
    ``Frames/`` subdirectory.
    """
    if sample.data_source == DataSource.simulation:
        acq_root = sample.path / "SyntheticCryoET"
    else:
        acq_root = sample.path
    if not acq_root.is_dir():
        return
    for child in sorted(acq_root.iterdir()):
        if not child.is_dir():
            continue
        acq_toml = child / "acquisition.toml"
        frames = child / "Frames"
        has_toml = acq_toml.is_file()
        has_frames = frames.is_dir()
        if not (has_toml or has_frames):
            continue

        tilt_series = child / "TiltSeries"
        # Reconstructions/ holds tomograms + annotations for both arms; the
        # per-arm nesting depth (experimental {ts_id}/ level vs. flat simulation)
        # is resolved by iter_tomograms / iter_annotations from data_source.
        reconstructions = child / "Reconstructions"

        yield AcquisitionLocation(
            path=child,
            sample_id=sample.sample_id,
            acquisition_id=child.name,
            acquisition_toml=acq_toml if has_toml else None,
            frames_dir=frames if has_frames else None,
            tilt_series_dir=tilt_series if tilt_series.is_dir() else None,
            reconstructions_dir=reconstructions if reconstructions.is_dir() else None,
            data_source=sample.data_source,
        )


def _reconstruction_dirs(
    acq: AcquisitionLocation, leaf: str
) -> Iterator[tuple[Path, str | None]]:
    """Yield ``(dir, tilt_series_id)`` for each Reconstructions ``leaf`` folder.

    ``leaf`` is ``"Tomograms"`` or ``"Annotations"``. The arm decides nesting:

    - experimental: ``Reconstructions/{ts_id}/{leaf}/`` — one per tilt-series
      folder, ``tilt_series_id = {ts_id}``.
    - simulation: ``Reconstructions/{leaf}/`` — flat, ``tilt_series_id = None``.
    """
    recon = acq.reconstructions_dir
    if recon is None or not recon.is_dir():
        return
    if acq.data_source == DataSource.simulation:
        leaf_dir = recon / leaf
        if leaf_dir.is_dir():
            yield leaf_dir, None
        return
    for ts_dir in sorted(recon.iterdir()):
        if not ts_dir.is_dir():
            continue
        leaf_dir = ts_dir / leaf
        if leaf_dir.is_dir():
            yield leaf_dir, ts_dir.name


def iter_tomograms(acq: AcquisitionLocation) -> Iterator[TomogramLocation]:
    """Yield one TomogramLocation per file-stem under the Tomograms folder(s).

    Tomograms are files (not folders): each entity's ``id`` is the filename
    stem, so a ``foo.mrc`` and its matching ``foo.ome.zarr`` collapse to one
    tomogram. Only ``.mrc`` / ``.zarr`` / ``.ome.zarr`` entries are grouped;
    stray files (``.gitkeep``, etc.) are ignored.
    """
    for leaf_dir, tilt_series_id in _reconstruction_dirs(acq, "Tomograms"):
        mrc_by_stem: dict[str, list[Path]] = {}
        zarr_by_stem: dict[str, list[Path]] = {}
        for entry in sorted(leaf_dir.iterdir()):
            if entry.is_file() and entry.suffix.lower() in TOMOGRAM_FILE_EXTENSIONS:
                mrc_by_stem.setdefault(entity_id_from_path(entry), []).append(entry)
            elif entry.is_dir() and is_zarr_dir(entry):
                zarr_by_stem.setdefault(entity_id_from_path(entry), []).append(entry)
        for stem in sorted(mrc_by_stem.keys() | zarr_by_stem.keys()):
            yield TomogramLocation(
                path=leaf_dir,
                tomogram_id=stem,
                mrc_files=tuple(mrc_by_stem.get(stem, ())),
                zarr_dirs=tuple(zarr_by_stem.get(stem, ())),
                tilt_series_id=tilt_series_id,
            )


def iter_annotations(acq: AcquisitionLocation) -> Iterator[AnnotationLocation]:
    """Yield one AnnotationLocation per file-stem under the Annotations folder(s).

    Annotations are files (not folders): each entity's ``id`` is the filename
    stem, so differently-suffixed files sharing a stem (``ann.json`` +
    ``ann.mrc``) collapse to one annotation. File children are filtered by the
    extension allowlist; ``.zarr`` / ``.ome.zarr`` dirs count as a single entry.
    """
    for leaf_dir, tilt_series_id in _reconstruction_dirs(acq, "Annotations"):
        by_stem: dict[str, list[Path]] = {}
        for entry in leaf_dir.iterdir():
            if entry.is_file() and entry.suffix.lower() in ANNOTATION_FILE_EXTENSIONS:
                by_stem.setdefault(entity_id_from_path(entry), []).append(entry)
            elif entry.is_dir() and is_zarr_dir(entry):
                by_stem.setdefault(entity_id_from_path(entry), []).append(entry)
        for stem in sorted(by_stem):
            yield AnnotationLocation(
                path=leaf_dir,
                annotation_id=stem,
                files=tuple(sorted(by_stem[stem], key=lambda p: str(p))),
                tilt_series_id=tilt_series_id,
            )


def iter_tilt_series(acq: AcquisitionLocation) -> Iterator[TiltSeriesLocation]:
    """Yield one TiltSeriesLocation per direct child of ``acq.tilt_series_dir``.

    Each ``TiltSeries/{ts_id}/`` is a researcher-authored tilt-series folder.
    The ``stack/`` and ``alignment/`` subfolders are OPTIONAL — when absent the
    corresponding fields are just ``None``/empty; the tilt series is still
    yielded. ``st_path`` resolves to the first ``*.st`` (then ``*.mrc``) file
    under ``stack/``; ``zarr_path`` to the first ``.zarr`` / ``.ome.zarr`` dir
    there. ``alignment_files`` collects files (and any ``.zarr`` dirs) directly
    under ``alignment/``.
    """
    if acq.tilt_series_dir is None or not acq.tilt_series_dir.is_dir():
        return
    for child in sorted(acq.tilt_series_dir.iterdir()):
        if not child.is_dir():
            continue

        stack = child / "stack"
        stack_dir = stack if stack.is_dir() else None
        st_path: Path | None = None
        zarr_path: Path | None = None
        if stack_dir is not None:
            st_candidates: list[Path] = []
            mrc_candidates: list[Path] = []
            for entry in sorted(stack_dir.iterdir()):
                if entry.is_file() and entry.suffix == ".st":
                    st_candidates.append(entry)
                elif entry.is_file() and entry.suffix.lower() in TOMOGRAM_FILE_EXTENSIONS:
                    mrc_candidates.append(entry)
                elif entry.is_dir() and is_zarr_dir(entry) and zarr_path is None:
                    zarr_path = entry
            if st_candidates:
                st_path = st_candidates[0]
            elif mrc_candidates:
                st_path = mrc_candidates[0]

        alignment = child / "alignment"
        alignment_dir = alignment if alignment.is_dir() else None
        alignment_files: list[Path] = []
        if alignment_dir is not None:
            for entry in alignment_dir.iterdir():
                if entry.is_file():
                    alignment_files.append(entry)
                elif entry.is_dir() and is_zarr_dir(entry):
                    alignment_files.append(entry)

        yield TiltSeriesLocation(
            path=child,
            tilt_series_id=child.name,
            stack_dir=stack_dir,
            alignment_dir=alignment_dir,
            st_path=st_path,
            zarr_path=zarr_path,
            alignment_files=tuple(sorted(alignment_files, key=lambda p: str(p))),
        )


def parse_targets_for_sample(sample: SampleLocation) -> list[Path]:
    """Return every file the parsers will read for this sample.

    The orchestrator (scanner.py) consumes this to drive file-level mtime gating
    (§4.5). The list is deterministic, deduplicated, and sorted by string path.
    """
    targets: set[Path] = set()
    targets.add(sample.sample_toml)

    # MD-run metadata: each MdRuns/*/md_run.toml so mtime gating reacts to edits.
    for md_run in iter_md_runs(sample):
        targets.add(md_run.md_run_toml)

    for acq in iter_acquisitions(sample):
        if acq.acquisition_toml is not None:
            targets.add(acq.acquisition_toml)

        if acq.frames_dir is not None and acq.frames_dir.is_dir():
            # MDOC files (direct children only).
            for mdoc in sorted(acq.frames_dir.glob("*.mdoc")):
                targets.add(mdoc)
            # Representative frame file: first by sorted name whose suffix
            # matches the camera-extension allowlist.
            for entry in sorted(acq.frames_dir.iterdir()):
                if entry.is_file() and entry.suffix.lower() in REPRESENTATIVE_FRAME_SUFFIXES:
                    targets.add(entry)
                    break

        for tomo in iter_tomograms(acq):
            for mrc in tomo.mrc_files:
                targets.add(mrc)
            for zarr_dir in tomo.zarr_dirs:
                zattrs = zarr_dir / ".zattrs"
                if zattrs.is_file():
                    targets.add(zattrs)

    return sorted(targets, key=lambda p: str(p))
