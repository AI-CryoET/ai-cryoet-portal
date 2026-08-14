"""Tomogram preview + Neuroglancer endpoints (plan §7.4).

URL design uses composite keys (sample_id, acquisition_id,
reconstruction_alignment_id, tomogram_id) to mirror the table's primary
key — self-describing, no server-side hash table to maintain
(decision §11.8). The tomogram id is a file stem, unique only within its
Reconstructions/{group}/ directory, so the group must appear in the URL.

Heavy work (MRC decode, matplotlib render) runs on
``fastapi.concurrency.run_in_threadpool`` so the event loop stays free. The
Neuroglancer launch itself is stateless (``build_precomputed_launch_url``) —
no server, no volume load, nothing to tear down.
"""
from __future__ import annotations

import hashlib
import os
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
    extra_layers: list[dict] | None = None,
) -> str:
    """Build a stateless Neuroglancer viewer URL over a precomputed source.

    Uses neuroglancer's own ``ViewerState`` + ``to_url`` — no server started.
    mrc-server serves canonical x,y,z, so the IMOD X/Y mirror flips x and y
    with an ``(extent-1)`` translation; z stays identity.

    ``extra_layers`` are raw Neuroglancer layer dicts (each with its own
    ``name``) appended after the image layer — e.g. a bbox annotation layer
    whose ``local://annotations`` geometry rides inline in the URL.
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
    for extra in extra_layers or []:
        state.layers.append(name=extra.get("name", "annotation"), layer=extra)
    state.dimensions = dims
    # Center the view on the volume. Unset, Neuroglancer defaults position to
    # [0.5, 0.5, 0.5] (center of the first voxel = volume corner). Position is
    # in voxel units of the x,y,z space, so size/2 is the center regardless of
    # the IMOD mirror (which transforms the source, not the global frame).
    state.position = [size_xyz[0] / 2, size_xyz[1] / 2, size_xyz[2] / 2]
    return ng.to_url(state, prefix=viewer_base)


async def build_precomputed_launch_url(
    request: Request,
    mrc_path: str,
    *,
    extra_layers: list[dict] | None = None,
) -> str:
    """Stateless Neuroglancer viewer URL over an MRC served by mrc-ng-server.

    Shared by the tomogram launch and the annotation/bbox launch: resolves the
    mrc under the data root, points a ``precomputed://`` source at
    ``MRCNG_BASE_URL`` (``row.mrc_path`` is the served relpath 1:1), and bakes
    the IMOD X/Y mirror + a 1-99 contrast window into the state. ``extra_layers``
    (e.g. a bbox annotation layer) are appended inline. No in-process viewer, so
    the frontend opens the URL as-is — no dev-only re-rooting, no :8050 state
    server. 422 for a missing file, 500 for unconfigured ``MRCNG_BASE_URL``.
    """
    resolved = validate_under_data_root(request, mrc_path)
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
    return _build_precomputed_viewer_url(
        source_url=source_url,
        name=Path(resolved).stem,
        viewer_base=viewer_base,
        size_xyz=size_xyz,
        voxel_nm_xyz=voxel_nm,
        contrast=contrast,
        mirror_xy=True,
        extra_layers=extra_layers,
    )


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

    url = await build_precomputed_launch_url(request, row.mrc_path)
    return ViewerLaunchOut(url=url)
