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
import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.path_validation import validate_under_data_root
from catalog.api.routes.tomograms import launch_viewer_in_registry, _lookup_tomogram
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


def _annotation_json_path(files: list[str]) -> str | None:
    """First ``_neuroglancer.json`` artifact in an annotation's file list, or ``None``."""
    return next((f for f in files if f.lower().endswith("_neuroglancer.json")), None)


def _bbox_target_tomogram(
    session: Session,
    sample_id: str,
    acquisition_id: str,
    reconstruction_alignment_id: str,
    derived_from: str | None,
):
    """Tomogram to render a bounding-box overlay over.

    Prefer the author-declared ``derived_from`` tomogram; otherwise fall back to
    any tomogram in the same alignment group (post-processed first). Bbox coords
    live in the group's shared voxel frame, so any group tomogram is a valid
    canvas — ``derived_from`` is optional ``acquisition.toml`` metadata that is
    absent on most (esp. auto-migrated) annotations. Raises 422 if the group has
    no tomogram to draw on.
    """
    if derived_from:
        return _lookup_tomogram(
            session,
            sample_id,
            acquisition_id,
            reconstruction_alignment_id=reconstruction_alignment_id,
            tomogram_id=derived_from,
        )
    for orm_cls in (orm.PostProcessedTomogramORM, orm.RawTomogramORM):
        row = session.execute(
            select(orm_cls)
            .filter_by(
                sample_id=sample_id,
                acquisition_id=acquisition_id,
                reconstruction_alignment_id=reconstruction_alignment_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if row is not None:
            return row
    raise HTTPException(
        status_code=422, detail="no tomogram in alignment group to render bbox over"
    )


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
    """Launch a Neuroglancer viewer over the annotation's ``.mrc`` volume, or a 
    Neuroglancer view + bounding box overlay if ``.json`` files are in the ``annotation_id``
    dir. 

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
    json_path = _annotation_json_path(row.files)

    if json_path:
        tomogram_row = _bbox_target_tomogram(
            session,
            sample_id,
            acquisition_id,
            reconstruction_alignment_id,
            row.derived_from,
        )
        if not tomogram_row.mrc_path:
            raise HTTPException(status_code=422, detail="tomogram has no mrc_path")
        resolved_tomo_mrc = validate_under_data_root(request, tomogram_row.mrc_path)
        if not resolved_tomo_mrc.is_file():
            raise HTTPException(status_code=422, detail="mrc file missing on disk")

        resolved_json = validate_under_data_root(request, json_path)
        if not resolved_json.is_file():
            raise HTTPException(status_code=422, detail="json file missing on disk")

        def launch():
            from catalog.imaging._mrc import read_mrc_volume
            from catalog.imaging._neuroglancer import view_neuroglancer, add_json_layer

            data, voxel_size, axis_order = read_mrc_volume(str(resolved_tomo_mrc))
            json_data = json.loads(resolved_json.read_text())[0] # always only a single bbox
            # image_size_* is nullable; skip the initial position rather than
            # crash on None/2 when a group tomogram has no recorded size.
            sizes = [getattr(tomogram_row, f'image_size_{a}') for a in axis_order]
            init_pos = tuple(s / 2 for s in sizes) if all(s is not None for s in sizes) else None
            viewer = view_neuroglancer(
                data,
                name=Path(resolved_tomo_mrc).stem,
                voxel_size=voxel_size,
                axis_names=axis_order,
                initial_position=init_pos,
            )
            add_json_layer(viewer, annotation_id, json_data)
            return viewer

    else:
        mrc_path = _annotation_mrc_path(row.files)
        if not mrc_path:
            raise HTTPException(status_code=422, detail="annotation has no mrc_path")
        resolved_annot_mrc = validate_under_data_root(request, mrc_path)
        if not resolved_annot_mrc.is_file():
            raise HTTPException(status_code=422, detail="annotation mrc file missing from disk")

        def launch():
            from catalog.imaging._mrc import read_mrc_volume
            from catalog.imaging._neuroglancer import view_neuroglancer

            data, voxel_size, axis_order = read_mrc_volume(str(resolved_annot_mrc))
            return view_neuroglancer(
                data,
                name=Path(resolved_annot_mrc).stem,
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
