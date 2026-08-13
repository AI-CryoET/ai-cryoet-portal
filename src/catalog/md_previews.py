"""Pre-generate per-MD-run OVITO preview PNGs into a filesystem cache.

One preview per MD run — an OVITO TachyonRenderer snapshot of the run's
representative LAMMPS dump. MD trajectories live under the portal layout at
``{sample}/MdRuns/{md_run_id}/Trajectories/<dump>`` (see aicryoet-simulation's
``portal.infer_sample_and_run``); we render ``dna.dump`` when present, else the
first dump file we find.

Mirrors :mod:`catalog.thumbnails` (the tilt-series equivalent): the scanner
calls :func:`generate_md_previews` with a list of :class:`MdRunRef`, the PNGs
land under ``{preview_root}/{sample_id}/{md_run_id}.png``, and the relpath of
each is stored back on the ``md_runs`` row so the API's ``/md-previews/{relpath}``
route can serve it directly. The cache root is the same dir the API reads via
``CATALOG_MD_PREVIEW_DIR``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from catalog import discovery
from schema.schema import DatasetType

# Preview dimensions — larger than tilt thumbnails (512px) because MD snapshots
# carry fine ellipsoid/backbone detail worth showing on detail pages.
PREVIEW_WIDTH = 1200
PREVIEW_HEIGHT = 900

# Whether to wrap atoms back into the periodic box before rendering, keyed by
# dataset type. Mirrors what aicryoet-tools does upstream (verified against its
# .portal_cache: Bulk/Slab previews are ``*_dna_wrap_preview.png`` — our wrapped
# render is byte-identical — while SingleMolecule ones are un-wrapped). The
# production dumps store *unwrapped* coords (``xu yu zu``): for Bulk/Slab
# condensates, wrapping folds the drifted periodic images into a dense,
# well-framed view; a SingleMolecule fiber would instead fragment across the box
# boundary, so it renders un-wrapped.
_WRAP_DATASET_TYPES = frozenset({DatasetType.bulk, DatasetType.slab})


def wrap_for_dataset_type(dataset_type: DatasetType | None) -> bool:
    """Wrap policy for a sample's dataset type (see ``_WRAP_DATASET_TYPES``)."""
    return dataset_type in _WRAP_DATASET_TYPES

# Some runs write a single ``dna.dump``; others write numbered segments
# (``dna_1.dump``, ``dna_2.dump``, ...) with no plain ``dna.dump`` present.
# The glob below matches both; sorting puts the unnumbered file first when it
# exists (``.`` sorts before ``_``). The renderer special-cases ``cores*.dump``
# (histone cores only) by re-deriving from the matching ``dna*.dump``, so we
# never select a cores dump here as long as a dna dump exists alongside it.
_DNA_DUMP_GLOB = "dna*.dump"
_DUMP_GLOBS = ("*.dump", "*.lammpstrj")


@dataclass(frozen=True)
class MdRunRef:
    """An MD run's representative dump file for previewing.

    ``dump_path`` is the absolute path to the dump OVITO renders; ``None`` when
    the run has no dump file on disk (the run is then skipped).
    """

    md_run_id: str
    dump_path: str | None


def _safe_segment(value: str) -> str:
    if not value or "/" in value or "\\" in value or value in (".", ".."):
        raise ValueError(f"unsafe id segment: {value!r}")
    return value


def relpath(sample_id: str, md_run_id: str) -> str:
    """Cache-relative path a run's preview PNG lives at: ``{sample}/{run}.png``."""
    return "/".join((
        _safe_segment(sample_id),
        _safe_segment(md_run_id) + ".png",
    ))


def _choose_dump(md_run_dir: Path) -> str | None:
    """Pick the representative dump file for an MD-run directory.

    Looks in ``Trajectories/`` (the canonical portal location) first, then the
    run directory itself. Prefers a ``dna*.dump`` file; otherwise the first
    matching dump/lammpstrj file in sorted order.
    """
    for search_dir in (md_run_dir / "Trajectories", md_run_dir):
        if not search_dir.is_dir():
            continue
        dna_matches = sorted(search_dir.glob(_DNA_DUMP_GLOB))
        if dna_matches:
            return str(dna_matches[0])
        matches = sorted(
            p for pattern in _DUMP_GLOBS for p in search_dir.glob(pattern)
        )
        if matches:
            return str(matches[0])
    return None


def refs_from_location(sample_loc) -> list[MdRunRef]:
    """Build :class:`MdRunRef` list from a sample's ``MdRuns/`` on disk.

    Uses :func:`discovery.iter_md_runs` (the same enumeration the scanner and
    persistence use) so a preview is attempted for exactly the runs that get a
    ``md_runs`` row.
    """
    return [
        MdRunRef(loc.md_run_id, _choose_dump(loc.path))
        for loc in discovery.iter_md_runs(sample_loc)
    ]


def _render_one(dump_path: str, dest: Path, *, wrap_periodic: bool = False) -> bool:
    # Imported lazily so OVITO is only required when previews are actually
    # generated (it's an optional, heavyweight dependency).
    from catalog.imaging._md_render import render_md_dump_preview

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Keep a ``.png`` extension on the temp file: OVITO picks the image format
    # from the output filename, so a ``.tmp`` suffix makes render_image fail.
    tmp = dest.with_name(dest.stem + ".tmp.png")
    started = time.perf_counter()
    try:
        render_md_dump_preview(
            Path(dump_path),
            tmp,
            width=PREVIEW_WIDTH,
            height=PREVIEW_HEIGHT,
            wrap_periodic=wrap_periodic,
        )
    except Exception as e:
        logger.warning("md preview render failed for {}: {}", dump_path, e)
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dest)
    logger.debug(
        "    rendered md preview {} in {:.1f}s",
        dest.name,
        time.perf_counter() - started,
    )
    return True


def generate_md_previews(
    sample_id: str,
    refs: list[MdRunRef],
    preview_root: Path,
    *,
    skip_existing: bool = False,
    wrap_periodic: bool = False,
) -> dict[str, str]:
    """Render previews for a sample's MD runs into ``preview_root``.

    :param wrap_periodic: wrap atoms into the periodic box before rendering —
        set per dataset type via :func:`wrap_for_dataset_type` (Bulk/Slab yes,
        SingleMolecule no), matching aicryoet-tools' upstream behaviour.
    :return: ``{md_run_id: relpath}`` for every run that has a preview PNG on
        disk (freshly rendered or, with ``skip_existing``, already present).
        Runs with no dump file or a failed render are omitted.
    """
    generated: dict[str, str] = {}
    for ref in refs:
        if not ref.dump_path:
            continue
        rel = relpath(sample_id, ref.md_run_id)
        dest = preview_root / rel
        ok = (
            True if (skip_existing and dest.is_file())
            else _render_one(ref.dump_path, dest, wrap_periodic=wrap_periodic)
        )
        if ok:
            generated[ref.md_run_id] = rel
    return generated
