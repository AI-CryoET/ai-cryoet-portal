"""Tomogram preview + Neuroglancer endpoints (plan §7.4).

URL design uses composite keys (sample_id, acquisition_id,
reconstruction_alignment_id, tomogram_id) to mirror the table's primary
key — self-describing, no server-side hash table to maintain
(decision §11.8). The tomogram id is a file stem, unique only within its
Reconstructions/{group}/ directory, so the group must appear in the URL.

Heavy work (MRC decode, matplotlib render, Neuroglancer launch) runs on
``fastapi.concurrency.run_in_threadpool`` so the event loop stays free.

A viewer leaving the registry (LRU eviction, re-launch of the same key, or
the idle sweep) is torn down via ``teardown_viewer`` so its volume RAM is
actually released — dropping the registry reference alone does not, because
the array is also pinned by the viewer's ``volume_manager`` and the load
cache. Neuroglancer has no per-instance ``.stop()``, so teardown breaks that
still-open browser tab.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.path_validation import validate_under_data_root
from catalog.api.schemas import ViewerLaunchOut

router = APIRouter()

# Janelia's Fileglancer-hosted Neuroglancer app (data-only mrc-server serves no
# UI). Override per deployment; the browser loads only the JS from here and
# fetches precomputed chunks straight from MRCNG_BASE_URL.
DEFAULT_NEUROGLANCER_VIEWER = "https://fileglancer.int.janelia.org/neuroglancer"


def _lookup_tomogram(
    session: Session,
    sample_id: str,
    acquisition_id: str,
    *,
    reconstruction_alignment_id: str,
    tomogram_id: str,
) -> orm.RawTomogramORM | orm.PostProcessedTomogramORM:
    """Return the tomogram row or raise 404 (incl. soft-deleted parent samples).

    Raw and post-processed tomograms share one id namespace within an
    alignment group (the assembler ensures no collision), so at most one of
    the two tables holds a row for any (sample_id, acquisition_id,
    reconstruction_alignment_id, tomogram_id) tuple. Post-processed is
    checked first because preview/Neuroglancer requests target denoised
    tomograms far more often than raw.

    The group and leaf args are keyword-only: four same-typed positionals made
    a transposition a silent 404.
    """
    sample = session.get(orm.SampleORM, sample_id)
    if sample is None or sample.deleted_at is not None:
        raise HTTPException(status_code=404, detail="sample not found")
    pk = (sample_id, acquisition_id, reconstruction_alignment_id, tomogram_id)
    row = session.get(orm.PostProcessedTomogramORM, pk)
    if row is None:
        row = session.get(orm.RawTomogramORM, pk)
    if row is None:
        raise HTTPException(status_code=404, detail="tomogram not found")
    return row


@lru_cache(maxsize=64)
def _cached_preview_png(mrc_path: str, mtime: float) -> bytes:
    """LRU-cached PNG render keyed on ``(mrc_path, mtime)``.

    ``mtime`` is part of the key so re-acquisitions invalidate automatically
    without a manual flush. Max size capped by ``PREVIEW_CACHE_MAX_ENTRIES``
    (default 64) — sized at module import; tuning needs an API restart.
    """
    # Heavy import deferred so the catalog-only environment can still import
    # this module (matplotlib/numpy aren't catalog deps).
    from catalog.imaging._mrc import render_center_xy_slice_png

    return render_center_xy_slice_png(mrc_path, width=1200)


@router.get(
    "/{sample_id}/{acquisition_id}/{reconstruction_alignment_id}"
    "/{tomogram_id}/preview.png"
)
async def tomogram_preview(
    sample_id: str,
    acquisition_id: str,
    reconstruction_alignment_id: str,
    tomogram_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Render the center-XY slice as a PNG (1200px wide, 1–99% percentile).

    Returns 404 for missing row or path-outside-root, 422 for an existing
    row whose ``mrc_path`` is missing on disk.
    """
    row = _lookup_tomogram(
        session,
        sample_id,
        acquisition_id,
        reconstruction_alignment_id=reconstruction_alignment_id,
        tomogram_id=tomogram_id,
    )
    if not row.mrc_path:
        raise HTTPException(status_code=422, detail="tomogram has no mrc_path")

    resolved = validate_under_data_root(request, row.mrc_path)
    if not resolved.is_file():
        raise HTTPException(status_code=422, detail="mrc file missing on disk")
    mtime = resolved.stat().st_mtime

    # ETag = mrc path + mtime — opaque short hash.
    etag_seed = f"{resolved}:{mtime}".encode()
    etag = f'W/"{hashlib.md5(etag_seed).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    png_bytes = await run_in_threadpool(_cached_preview_png, str(resolved), mtime)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=3600",
        },
    )


@dataclass
class ViewerEntry:
    """A live viewer plus the liveness state the idle sweep tracks.

    ``last_active`` / ``last_gen`` let ``sweep_idle_viewers`` tell an idle
    viewer from an actively-used one: the browser bumps
    ``viewer.config_state.state_generation`` whenever it pushes state
    (pan/zoom/scroll).
    """

    viewer: object
    last_active: float
    last_gen: object


def _viewer_generation(viewer) -> object:
    """Best-effort read of a viewer's client-state generation (None if absent)."""
    try:
        return viewer.config_state.state_generation
    except Exception:  # noqa: BLE001 — fakes/older viewers lack config_state
        return None


async def launch_viewer_in_registry(
    request: Request,
    key: tuple[str, ...],
    launch_fn,
) -> str:
    """Launch a Neuroglancer viewer, recording it in the bounded LRU.

    The lock guards against concurrent launches racing to evict each
    other's entries when at capacity. ``launch_fn`` is run on a threadpool
    because viewer creation blocks for tens of ms on first call.

    Evicted viewers (LRU overflow, or the stale entry when re-launching the
    same key) are torn down off-lock so their volume RAM is actually freed —
    dropping the registry reference alone does not (see ``teardown_viewer``).
    """
    from catalog.imaging._neuroglancer import neuroglancer_url, teardown_viewer

    registry: OrderedDict = request.app.state.active_viewers
    lock = request.app.state.active_viewers_lock
    max_viewers: int = request.app.state.neuroglancer_max_viewers

    viewer = await run_in_threadpool(launch_fn)
    entry = ViewerEntry(viewer, time.monotonic(), _viewer_generation(viewer))

    evicted = []
    async with lock:
        old = registry.pop(key, None)  # replacing a re-launch of the same key
        if old is not None:
            evicted.append(old.viewer)
        registry[key] = entry
        while len(registry) > max_viewers:
            evicted.append(registry.popitem(last=False)[1].viewer)

    for v in evicted:
        await run_in_threadpool(teardown_viewer, v)

    return neuroglancer_url(viewer)


def _memory_usage_ratio() -> float:
    """Anon memory as a fraction of the cgroup v2 limit (0.0 if unreadable).

    Anon is the unreclaimable memory the viewers' arrays + base process hold —
    the right pressure signal here. We deliberately ignore ``memory.current``,
    which also counts reclaimable NFS page cache the kernel drops on its own,
    so page cache alone never looks like pressure. Returns 0.0 off cgroup v2
    (dev/tests) → never reads as under pressure.
    """
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            raw = f.read().strip()
        if raw == "max":  # no limit set
            return 0.0
        limit = int(raw)
        with open("/sys/fs/cgroup/memory.stat") as f:
            anon = next(
                int(line.split()[1]) for line in f if line.startswith("anon ")
            )
        return anon / limit if limit > 0 else 0.0
    except (OSError, ValueError, StopIteration):
        return 0.0


async def sweep_idle_viewers(
    app, interval: float, ttl: float, pressure_ratio: float
) -> None:
    """Reclaim idle viewers, but only while the pod is under memory pressure.

    There is no browser tab-close signal (the viewer tab is served by the
    process-global Neuroglancer server on its own origin), so "closed" is
    inferred from inactivity: an entry whose ``state_generation`` hasn't moved
    for ``ttl``. Freeing that memory is only worth doing when RAM is actually
    tight, so teardown is gated on anon usage reaching ``pressure_ratio`` of the
    cgroup limit. Below that, idle viewers stay resident (fast re-open, RAM to
    spare); the LRU cap remains the hard bound. Runs as a lifespan background
    task. (Phase 2's SSE proxy will replace the timeout with real disconnect
    events, keeping this only as the under-pressure backstop.)

    Liveness is refreshed every pass regardless of pressure so ``last_active``
    stays accurate for when pressure does hit.
    """
    from catalog.imaging._neuroglancer import teardown_viewer

    registry: OrderedDict = app.state.active_viewers
    lock = app.state.active_viewers_lock
    while True:
        await asyncio.sleep(interval)
        now = time.monotonic()
        under_pressure = _memory_usage_ratio() >= pressure_ratio
        stale = []
        async with lock:
            for key, entry in list(registry.items()):
                gen = _viewer_generation(entry.viewer)
                if gen != entry.last_gen:  # client interacted → still alive
                    entry.last_gen = gen
                    entry.last_active = now
                elif under_pressure and now - entry.last_active > ttl:
                    stale.append((key, entry.viewer))
            for key, _v in stale:
                del registry[key]
        for key, v in stale:
            logger.info("Reclaiming idle Neuroglancer viewer under memory pressure: {}", key)
            await run_in_threadpool(teardown_viewer, v)


@lru_cache(maxsize=64)
def _cached_viewer_params(mrc_path: str, mtime: float):
    """LRU-cached ``read_mrc_viewer_params`` keyed on ``(mrc_path, mtime)``.

    Same invalidate-on-reacquisition pattern as ``_cached_preview_png``: a
    re-write changes ``mtime`` and drops the stale entry. Reads a single plane,
    so this is cheap even the first time.
    """
    from catalog.imaging._mrc import read_mrc_viewer_params

    return read_mrc_viewer_params(mrc_path)


def _build_precomputed_viewer_url(
    *,
    source_url: str,
    name: str,
    viewer_base: str,
    size_xyz: tuple[int, int, int],
    voxel_nm_xyz: tuple[float, float, float],
    contrast: tuple[float, float] | None,
    mirror_xy: bool,
) -> str:
    """Build a stateless Neuroglancer viewer URL over a precomputed source.

    Uses neuroglancer's own ``ViewerState`` + ``to_url`` (no server started, so
    none of the registry/teardown apparatus is touched) so the IMOD X/Y mirror
    and the contrast window serialize exactly as the in-process viewer produced
    them. mrc-server serves canonical x,y,z, so the mirror flips x and y with an
    ``(extent-1)`` translation — the same ``-1``-on-the-diagonal matrix the old
    ``LocalVolume`` path used, reordered to x,y,z.
    """
    import neuroglancer as ng

    dims = ng.CoordinateSpace(names=["x", "y", "z"], scales=list(voxel_nm_xyz), units="nm")
    if mirror_xy:
        n = 3
        matrix = [[1.0 if i == j else 0.0 for j in range(n + 1)] for i in range(n)]
        for k in (0, 1):  # x, y
            matrix[k][k] = -1.0
            matrix[k][n] = float(size_xyz[k] - 1)
        source = ng.LayerDataSource(
            url=source_url,
            transform=ng.CoordinateSpaceTransform(
                input_dimensions=dims, output_dimensions=dims, matrix=matrix
            ),
        )
    else:
        source = ng.LayerDataSource(url=source_url)

    layer = ng.ImageLayer(source=source)
    if contrast is not None:
        layer.shader_controls = {"normalized": {"range": list(contrast)}}

    state = ng.ViewerState()
    state.layers[name] = layer
    state.dimensions = dims
    return ng.to_url(state, prefix=viewer_base)


@router.post(
    "/{sample_id}/{acquisition_id}/{reconstruction_alignment_id}"
    "/{tomogram_id}/neuroglancer",
    response_model=ViewerLaunchOut,
)
async def tomogram_neuroglancer(
    sample_id: str,
    acquisition_id: str,
    reconstruction_alignment_id: str,
    tomogram_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Build a stateless Neuroglancer viewer URL for the tomogram.

    No volume load, no in-process viewer: the returned URL points the
    Fileglancer-hosted Neuroglancer app at a ``precomputed://`` source served
    by mrc-server (``MRCNG_BASE_URL`` must resolve to the same data root, so
    ``row.mrc_path`` is the served relpath 1:1). Voxel size rides in mrc-server's
    ``info``; only the IMOD X/Y mirror and a 1-99 contrast window are baked into
    the state here.
    """
    row = _lookup_tomogram(
        session,
        sample_id,
        acquisition_id,
        reconstruction_alignment_id=reconstruction_alignment_id,
        tomogram_id=tomogram_id,
    )
    if not row.mrc_path:
        raise HTTPException(status_code=422, detail="tomogram has no mrc_path")

    resolved = validate_under_data_root(request, row.mrc_path)
    if not resolved.is_file():
        raise HTTPException(status_code=422, detail="mrc file missing on disk")

    base = os.environ.get("MRCNG_BASE_URL")
    if not base:
        raise HTTPException(status_code=500, detail="MRCNG_BASE_URL not configured")
    viewer_base = os.environ.get("NEUROGLANCER_VIEWER_URL", DEFAULT_NEUROGLANCER_VIEWER)

    data_root = request.app.state.data_root_resolved
    relpath = resolved.relative_to(data_root).as_posix()
    source_url = f"precomputed://{base.rstrip('/')}/{relpath}"

    mtime = resolved.stat().st_mtime
    size_xyz, voxel_nm, contrast = await run_in_threadpool(
        _cached_viewer_params, str(resolved), mtime
    )
    url = _build_precomputed_viewer_url(
        source_url=source_url,
        name=Path(resolved).stem,
        viewer_base=viewer_base,
        size_xyz=size_xyz,
        voxel_nm_xyz=voxel_nm,
        contrast=contrast,
        mirror_xy=True,
    )
    return ViewerLaunchOut(url=url)
