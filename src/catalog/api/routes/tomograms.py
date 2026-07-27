"""Tomogram preview + Neuroglancer endpoints (plan §7.4).

URL design uses composite keys (sample_id, acquisition_id,
reconstruction_alignment_id, tomogram_id) to mirror the table's primary
key — self-describing, no server-side hash table to maintain
(decision §11.8). The tomogram id is a file stem, unique only within its
Reconstructions/{group}/ directory, so the group must appear in the URL.

Heavy work (MRC decode, matplotlib render, Neuroglancer launch) runs on
``fastapi.concurrency.run_in_threadpool`` so the event loop stays free.

Evicting a viewer means dropping the registry's reference; the underlying
``neuroglancer.Viewer`` has no per-instance ``.stop()`` and may linger in
process memory until GC. Restart the API to fully reset Neuroglancer
state (plan §7.4).
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.path_validation import validate_under_data_root
from catalog.api.schemas import ViewerLaunchOut

router = APIRouter()


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


async def launch_viewer_in_registry(
    request: Request,
    key: tuple[str, ...],
    launch_fn,
) -> str:
    """Launch a Neuroglancer viewer, recording it in the bounded LRU.

    The lock guards against concurrent launches racing to evict each
    other's entries when at capacity. ``launch_fn`` is run on a threadpool
    because viewer creation blocks for tens of ms on first call.
    """
    from catalog.imaging._neuroglancer import neuroglancer_url

    registry: OrderedDict = request.app.state.active_viewers
    lock = request.app.state.active_viewers_lock
    max_viewers: int = request.app.state.neuroglancer_max_viewers

    viewer = await run_in_threadpool(launch_fn)

    async with lock:
        if key in registry:
            registry.move_to_end(key)
            registry[key] = viewer
        else:
            registry[key] = viewer
            while len(registry) > max_viewers:
                registry.popitem(last=False)

    return neuroglancer_url(viewer)


def _load_volume_for_viewer(mrc_path: str):
    """Read the MRC into a numpy array on the threadpool side.

    Returns ``(data, voxel_size, axis_order)`` ready for ``view_neuroglancer``.
    """
    from catalog.imaging._mrc import read_mrc_volume

    return read_mrc_volume(mrc_path)


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
    """Launch a Neuroglancer viewer over the tomogram volume.

    The frontend rewrites the URL hostname to ``window.location.hostname``
    before opening — Neuroglancer reports the API host's FQDN which may
    not be reachable from the browser.
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

    def launch():
        from catalog.imaging._neuroglancer import view_neuroglancer

        data, voxel_size, axis_order = _load_volume_for_viewer(str(resolved))
        return view_neuroglancer(
            data,
            name=Path(resolved).stem,
            voxel_size=voxel_size,
            axis_names=axis_order,
        )

    url = await launch_viewer_in_registry(
        request,
        (
            "tomogram",
            sample_id,
            acquisition_id,
            reconstruction_alignment_id,
            tomogram_id,
        ),
        launch,
    )
    return ViewerLaunchOut(url=url)
