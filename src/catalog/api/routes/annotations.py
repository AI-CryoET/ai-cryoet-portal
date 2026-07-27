"""Annotation preview endpoint.

Annotations are composite-PK children of an alignment group
(``sample_id, acquisition_id, reconstruction_alignment_id, annotation_id``)
whose artifacts live in the
``files`` JSON list (an ``.mrc`` volume plus, typically, a ``.zarr`` and
sometimes a pre-rendered ``.png``/``.star``). This route renders the center-XY
slice of the annotation's ``.mrc`` as a PNG — the same render path the
tomogram preview uses — so dense segmentation/label volumes get a thumbnail in
the annotations sub-table.

Mirrors ``tomograms.py``: composite-key URL, ``run_in_threadpool`` for the
heavy MRC decode + matplotlib render, ETag keyed on ``(mrc_path, mtime)``.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.path_validation import validate_under_data_root
from catalog.api.routes.tomograms import launch_viewer_in_registry
from catalog.api.schemas import ViewerLaunchOut

router = APIRouter()


def _lookup_annotation(
    session: Session,
    sample_id: str,
    acquisition_id: str,
    *,
    reconstruction_alignment_id: str,
    annotation_id: str,
) -> orm.AnnotationORM:
    """Return the annotation row or raise 404 (incl. soft-deleted parent samples).

    The group and leaf args are keyword-only: four same-typed positionals made
    a transposition a silent 404.
    """
    sample = session.get(orm.SampleORM, sample_id)
    if sample is None or sample.deleted_at is not None:
        raise HTTPException(status_code=404, detail="sample not found")
    row = session.get(
        orm.AnnotationORM,
        (sample_id, acquisition_id, reconstruction_alignment_id, annotation_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="annotation not found")
    return row


def _annotation_mrc_path(files: list[str]) -> str | None:
    """First ``.mrc`` artifact in an annotation's file list, or ``None``."""
    return next((f for f in files if f.lower().endswith(".mrc")), None)


@lru_cache(maxsize=64)
def _cached_preview_png(mrc_path: str, mtime: float) -> bytes:
    """LRU-cached PNG render keyed on ``(mrc_path, mtime)``.

    ``mtime`` is part of the key so a re-scan that rewrites the file
    invalidates the entry automatically. Mirrors ``tomograms._cached_preview_png``.
    """
    # Heavy import deferred so the catalog-only environment can still import
    # this module (matplotlib/numpy aren't catalog deps).
    from catalog.imaging._mrc import render_center_xy_slice_png

    return render_center_xy_slice_png(mrc_path, width=1200)


@router.get(
    "/{sample_id}/{acquisition_id}/{reconstruction_alignment_id}"
    "/{annotation_id}/preview.png"
)
async def annotation_preview(
    sample_id: str,
    acquisition_id: str,
    reconstruction_alignment_id: str,
    annotation_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Render the annotation MRC's center-XY slice as a PNG (1200px, 1–99%).

    Returns 404 for a missing row or path-outside-root, 422 for an annotation
    with no ``.mrc`` artifact.
    """
    row = _lookup_annotation(
        session,
        sample_id,
        acquisition_id,
        reconstruction_alignment_id=reconstruction_alignment_id,
        annotation_id=annotation_id,
    )
    mrc_path = _annotation_mrc_path(row.files)
    if not mrc_path:
        raise HTTPException(status_code=422, detail="annotation has no mrc file")

    resolved = validate_under_data_root(request, mrc_path)
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


@router.post(
    "/{sample_id}/{acquisition_id}/{reconstruction_alignment_id}"
    "/{annotation_id}/neuroglancer",
    response_model=ViewerLaunchOut,
)
async def annotation_neuroglancer(
    sample_id: str,
    acquisition_id: str,
    reconstruction_alignment_id: str,
    annotation_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Launch a Neuroglancer viewer over the annotation's ``.mrc`` volume.

    Mirrors the tomogram launch route — same registry, same dev-side hostname
    rewrite on the frontend. 422 for an annotation with no ``.mrc`` artifact.
    """
    row = _lookup_annotation(
        session,
        sample_id,
        acquisition_id,
        reconstruction_alignment_id=reconstruction_alignment_id,
        annotation_id=annotation_id,
    )
    mrc_path = _annotation_mrc_path(row.files)
    if not mrc_path:
        raise HTTPException(status_code=422, detail="annotation has no mrc file")

    resolved = validate_under_data_root(request, mrc_path)
    if not resolved.is_file():
        raise HTTPException(status_code=422, detail="mrc file missing on disk")

    def launch():
        from catalog.imaging._mrc import read_mrc_volume
        from catalog.imaging._neuroglancer import view_neuroglancer

        data, voxel_size, axis_order = read_mrc_volume(str(resolved))
        return view_neuroglancer(
            data,
            name=Path(resolved).stem,
            voxel_size=voxel_size,
            axis_names=axis_order,
        )

    url = await launch_viewer_in_registry(
        request,
        (
            "annotation",
            sample_id,
            acquisition_id,
            reconstruction_alignment_id,
            annotation_id,
        ),
        launch,
    )
    return ViewerLaunchOut(url=url)
