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
    ZARR_DIR_SUFFIXES,
    entity_id_from_path,
    infer_arm,
    is_zarr_dir,
    sample_id_for,
)

# ANNOTATION_FILE_EXTENSIONS / TOMOGRAM_FILE_EXTENSIONS / ZARR_DIR_SUFFIXES /
# entity_id_from_path / is_zarr_dir all come from schema.layout — the single
# source of truth shared with the validate CLI. Re-exported here because the
# scanner and its tests have always imported them from discovery.
REPRESENTATIVE_FRAME_SUFFIXES = frozenset({".eer", ".tiff", ".tif"})


def _first_existing_dir(parent: Path, *names: str) -> Path | None:
    """First child dir matching one of ``names`` (in order), else ``None``.

    Lets a tilt-series subfolder be discovered under its canonical PascalCase
    name (``Stack``/``Alignment``) while still reading legacy lowercase
    (``stack``/``alignment``) layouts already on disk.
    """
    for name in names:
        candidate = parent / name
        if candidate.is_dir():
            return candidate
    return None


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


@dataclass(frozen=True)
class TomogramLocation:
    path: Path
    tomogram_id: str
    mrc_files: tuple[Path, ...]
    zarr_dirs: tuple[Path, ...]
    # Enclosing Reconstructions/{reconstruction_alignment_id}/ folder name.
    reconstruction_alignment_id: str


@dataclass(frozen=True)
class AnnotationLocation:
    path: Path
    annotation_id: str
    files: tuple[Path, ...]
    reconstruction_alignment_id: str


@dataclass(frozen=True)
class TiltSeriesLocation:
    path: Path
    tilt_series_id: str
    stack_dir: Path | None
    alignment_dir: Path | None
    st_path: Path | None
    zarr_path: Path | None
    alignment_files: tuple[Path, ...]


@dataclass(frozen=True)
class ReconstructionAlignmentLocation:
    path: Path
    reconstruction_alignment_id: str
    reconstruction_toml: Path | None
    tomograms_dir: Path | None
    annotations_dir: Path | None
    alignment_dir: Path | None
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
        sample_id=sample_id_for(sample_dir),
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
        # Both arms share one layout: Reconstructions/{group}/{Tomograms,
        # Annotations,Alignment}/. iter_tomograms / iter_annotations /
        # iter_reconstruction_alignments walk it.
        reconstructions = child / "Reconstructions"

        yield AcquisitionLocation(
            path=child,
            sample_id=sample.sample_id,
            acquisition_id=child.name,
            acquisition_toml=acq_toml if has_toml else None,
            frames_dir=frames if has_frames else None,
            tilt_series_dir=tilt_series if tilt_series.is_dir() else None,
            reconstructions_dir=reconstructions if reconstructions.is_dir() else None,
        )


def _reconstruction_leaf_dirs(
    acq: AcquisitionLocation, leaf: str
) -> Iterator[tuple[Path, str]]:
    """Yield ``(dir, reconstruction_alignment_id)`` for each Reconstructions
    ``leaf`` folder.

    ``leaf`` is ``"Tomograms"`` or ``"Annotations"``. Both arms share the same
    nesting: ``Reconstructions/{reconstruction_alignment_id}/{leaf}/`` — one per
    3D-alignment group folder, which does NOT have to match any
    ``tilt_series_id``.
    """
    recon = acq.reconstructions_dir
    if recon is None or not recon.is_dir():
        return
    for group_dir in sorted(recon.iterdir()):
        if not group_dir.is_dir():
            continue
        leaf_dir = group_dir / leaf
        if leaf_dir.is_dir():
            yield leaf_dir, group_dir.name


def iter_tomograms(acq: AcquisitionLocation) -> Iterator[TomogramLocation]:
    """Yield one TomogramLocation per file-stem under the Tomograms folder(s).

    Tomograms are files (not folders): each entity's ``id`` is the filename
    stem, so a ``foo.mrc`` and its matching ``foo.ome.zarr`` collapse to one
    tomogram. Only ``.mrc`` / ``.zarr`` / ``.ome.zarr`` entries are grouped;
    stray files (``.gitkeep``, etc.) are ignored.
    """
    for leaf_dir, group_id in _reconstruction_leaf_dirs(acq, "Tomograms"):
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
                reconstruction_alignment_id=group_id,
            )


def iter_annotations(acq: AcquisitionLocation) -> Iterator[AnnotationLocation]:
    """Yield one AnnotationLocation per annotation under the Annotations folder(s).

    An annotation is either a plain subfolder (``Annotations/{id}/`` — id is the
    folder name, ``files`` are the allowlisted files inside it, recursively) or a
    bare file / ``.zarr`` store whose id is the stem (differently-suffixed files
    sharing a stem, ``ann.json`` + ``ann.mrc``, collapse to one). Folders are
    yielded before bare stems; both are sorted. A ``.zarr`` dir is a store, not a
    container, so it is a single-file annotation, not a folder.
    """
    for leaf_dir, group_id in _reconstruction_leaf_dirs(acq, "Annotations"):
        folders: list[Path] = []
        by_stem: dict[str, list[Path]] = {}
        for entry in leaf_dir.iterdir():
            if entry.is_dir() and not is_zarr_dir(entry):
                folders.append(entry)
            elif entry.is_file() and entry.suffix.lower() in ANNOTATION_FILE_EXTENSIONS:
                by_stem.setdefault(entity_id_from_path(entry), []).append(entry)
            elif entry.is_dir() and is_zarr_dir(entry):
                by_stem.setdefault(entity_id_from_path(entry), []).append(entry)
        for folder in sorted(folders, key=lambda p: p.name):
            files = tuple(
                sorted(
                    (
                        p
                        for p in folder.rglob("*")
                        if p.is_file() and p.suffix.lower() in ANNOTATION_FILE_EXTENSIONS
                    ),
                    key=lambda p: str(p),
                )
            )
            yield AnnotationLocation(
                path=folder,
                annotation_id=folder.name,
                files=files,
                reconstruction_alignment_id=group_id,
            )
        for stem in sorted(by_stem):
            yield AnnotationLocation(
                path=leaf_dir,
                annotation_id=stem,
                files=tuple(sorted(by_stem[stem], key=lambda p: str(p))),
                reconstruction_alignment_id=group_id,
            )


def iter_reconstruction_alignments(
    acq: AcquisitionLocation,
) -> Iterator[ReconstructionAlignmentLocation]:
    """Yield one ReconstructionAlignmentLocation per direct child of
    ``Reconstructions/``.

    Each ``Reconstructions/{id}/`` is a researcher-authored 3D-alignment group
    folder owning its own ``reconstruction.toml``. ``Tomograms/`` and
    ``Annotations/`` are handled by :func:`iter_tomograms` /
    :func:`iter_annotations`; this walker collects the group's metadata file and
    its ``Alignment/`` artifacts (mirroring :func:`iter_tilt_series`).
    """
    recon = acq.reconstructions_dir
    if recon is None or not recon.is_dir():
        return
    for child in sorted(recon.iterdir()):
        if not child.is_dir():
            continue

        recon_toml = child / "reconstruction.toml"
        tomograms_dir = child / "Tomograms"
        annotations_dir = child / "Annotations"
        alignment = child / "Alignment"
        alignment_dir = alignment if alignment.is_dir() else None
        alignment_files: list[Path] = []
        if alignment_dir is not None:
            for entry in alignment_dir.iterdir():
                if entry.is_file():
                    alignment_files.append(entry)
                elif entry.is_dir() and is_zarr_dir(entry):
                    alignment_files.append(entry)

        yield ReconstructionAlignmentLocation(
            path=child,
            reconstruction_alignment_id=child.name,
            reconstruction_toml=recon_toml if recon_toml.is_file() else None,
            tomograms_dir=tomograms_dir if tomograms_dir.is_dir() else None,
            annotations_dir=annotations_dir if annotations_dir.is_dir() else None,
            alignment_dir=alignment_dir,
            alignment_files=tuple(sorted(alignment_files, key=lambda p: str(p))),
        )


def iter_tilt_series(acq: AcquisitionLocation) -> Iterator[TiltSeriesLocation]:
    """Yield one TiltSeriesLocation per direct child of ``acq.tilt_series_dir``.

    Each ``TiltSeries/{ts_id}/`` is a researcher-authored tilt-series folder.
    The ``Stack/`` and ``Alignment/`` subfolders are OPTIONAL — when absent the
    corresponding fields are just ``None``/empty; the tilt series is still
    yielded. Legacy lowercase ``stack/`` / ``alignment/`` are still read.
    ``st_path`` resolves to the first ``*.st`` (then ``*.mrc``) file under
    ``Stack/``; ``zarr_path`` to the first ``.zarr`` / ``.ome.zarr`` dir there.
    ``alignment_files`` collects files (and any ``.zarr`` dirs) directly under
    ``Alignment/``.
    """
    if acq.tilt_series_dir is None or not acq.tilt_series_dir.is_dir():
        return
    for child in sorted(acq.tilt_series_dir.iterdir()):
        if not child.is_dir():
            continue

        stack_dir = _first_existing_dir(child, "Stack", "stack")
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

        alignment_dir = _first_existing_dir(child, "Alignment", "alignment")
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

        # Per-group metadata: each Reconstructions/{group}/reconstruction.toml
        # so an edit to one re-triggers the sample's parse.
        for group in iter_reconstruction_alignments(acq):
            if group.reconstruction_toml is not None:
                targets.add(group.reconstruction_toml)

        for tomo in iter_tomograms(acq):
            for mrc in tomo.mrc_files:
                targets.add(mrc)
            for zarr_dir in tomo.zarr_dirs:
                zattrs = zarr_dir / ".zattrs"
                if zattrs.is_file():
                    targets.add(zattrs)

    return sorted(targets, key=lambda p: str(p))
