"""Per-tilt-series preview + Neuroglancer endpoints.

Composite-key URLs: ``/tilt-series/{sample_id}/{acquisition_id}/
{tilt_series_id}/...``.

Source-resolution order (decision §5 of the tilt-series/alignment plan): the
tilt series is a researcher-authored ``TiltSeries/{ts_id}/`` folder whose image
data lives under ``Stack/``. Prefer the zarr store (``zarr_path``; lazy, fast);
fall back to the ``.st``/``.mrc`` projection stack (``st_path``); finally fall
back to the **acquisition's** raw ``Frames/`` images when the series has no
stack artifact of its own (the frames are shared by all the acquisition's tilt
series).

The polar plot is no longer per-series — the tilt geometry is a property of the
acquisition. See ``routes/acquisitions.py`` for ``/acquisitions/.../polar.png``.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.path_validation import validate_under_data_root
from catalog.api.routes.tomograms import launch_viewer_in_registry
from catalog.api.schemas import ViewerLaunchOut
from catalog.imaging._tilt_series import (
    render_frames_median_png,
    render_st_median_png,
    render_zarr_median_png,
)

router = APIRouter()


def _lookup_tilt_series(
    session: Session, sample_id: str, acquisition_id: str, tilt_series_id: str
) -> orm.TiltSeriesORM:
    sample = session.get(orm.SampleORM, sample_id)
    if sample is None or sample.deleted_at is not None:
        raise HTTPException(status_code=404, detail="sample not found")
    row = session.get(
        orm.TiltSeriesORM, (sample_id, acquisition_id, tilt_series_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="tilt series not found")
    return row


def _resolve_acq_frames_dir(
    session: Session, request: Request, sample_id: str, acquisition_id: str
) -> Path | None:
    """Resolve the acquisition's ``Frames/`` dir for the raw-frames fallback.

    The MDOC/frames live on the acquisition (shared by all its tilt series),
    so we derive the dir from ``Acquisition.path`` rather than the tilt-series
    row. Returns ``None`` when the acquisition has no path or no ``Frames/``.
    """
    acq = session.get(orm.AcquisitionORM, (sample_id, acquisition_id))
    if acq is None or not acq.path:
        return None
    frames = Path(acq.path) / "Frames"
    resolved = validate_under_data_root(request, str(frames))
    return resolved if resolved.is_dir() else None


# ── Preview ───────────────────────────────────────────────────────────────


@router.get("/{sample_id}/{acquisition_id}/{tilt_series_id}/preview.png")
async def tilt_series_preview(
    sample_id: str,
    acquisition_id: str,
    tilt_series_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Median-tilt image as PNG.

    Prefers the authored ``Stack/`` (zarr, then ``.st``/``.mrc``); falls back
    to the acquisition's raw ``Frames/`` images. 422 if none are reachable.
    """
    row = _lookup_tilt_series(session, sample_id, acquisition_id, tilt_series_id)

    if row.zarr_path:
        resolved = validate_under_data_root(request, row.zarr_path)
        if not resolved.exists():
            raise HTTPException(status_code=422, detail="zarr path missing on disk")
        png_bytes = await run_in_threadpool(render_zarr_median_png, str(resolved))
    elif row.st_path:
        resolved = validate_under_data_root(request, row.st_path)
        if not resolved.exists():
            raise HTTPException(status_code=422, detail="stack path missing on disk")
        png_bytes = await run_in_threadpool(render_st_median_png, str(resolved))
    else:
        frames_dir = _resolve_acq_frames_dir(
            session, request, sample_id, acquisition_id
        )
        if frames_dir is None:
            raise HTTPException(
                status_code=422,
                detail="no stack artifact and no acquisition Frames dir",
            )
        try:
            png_bytes = await run_in_threadpool(
                render_frames_median_png, str(frames_dir)
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── Neuroglancer ──────────────────────────────────────────────────────────


def _load_zarr_stack(zarr_path: str):
    """Load the full zarr tilt stack + median index + tilt angles."""
    import numpy as np
    import zarr

    root = zarr.open_group(zarr_path, mode="r")
    ds = root["tilt_series"]
    tilt_angles = list(root.attrs.get("tilt_angles", list(range(ds.shape[0]))))
    median_angle = float(np.median(tilt_angles))
    median_idx = min(
        range(len(tilt_angles)),
        key=lambda i: abs(tilt_angles[i] - median_angle),
    )
    stack = np.array(ds[:], dtype=np.float32)
    return stack, median_idx, tilt_angles


def _load_st_stack(st_path: str):
    """Load an ``.st``/``.mrc`` tilt stack as a 3D array + median index."""
    from catalog.imaging._mrc import read_mrc_volume

    vol, _spacing, _axes = read_mrc_volume(st_path)
    median_idx = vol.shape[0] // 2
    return vol, median_idx, list(range(vol.shape[0]))


def _load_frames_stack(frames_dir: str):
    """Load TIFF/MRC tilt frames as a 3D stack."""
    import numpy as np

    from catalog.imaging._tilt_image import (
        find_viewable_tilt_images,
        load_tilt_image,
    )

    tilt_images = find_viewable_tilt_images(Path(frames_dir))
    if not tilt_images:
        raise FileNotFoundError("no viewable tilt images")
    angles = [a for a, _ in tilt_images]
    median_angle = float(np.median(angles))
    median_idx = min(range(len(angles)), key=lambda i: abs(angles[i] - median_angle))
    stack = np.stack(
        [load_tilt_image(p, gain=None, preview=True).astype(np.float32) for _, p in tilt_images]
    )
    return stack, median_idx, angles


@router.post(
    "/{sample_id}/{acquisition_id}/{tilt_series_id}/neuroglancer",
    response_model=ViewerLaunchOut,
)
async def tilt_series_neuroglancer(
    sample_id: str,
    acquisition_id: str,
    tilt_series_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Launch a Neuroglancer viewer over the tilt-series stack.

    Prefer the authored ``Stack/`` (zarr, then ``.st``/``.mrc``); fall back to
    the acquisition's raw ``Frames/`` images. 422 if none are reachable.
    """
    row = _lookup_tilt_series(session, sample_id, acquisition_id, tilt_series_id)
    acq = session.get(orm.AcquisitionORM, (sample_id, acquisition_id))
    pixel_spacing = float(acq.pixel_size) if acq and acq.pixel_size else 1.0

    if row.zarr_path:
        resolved = validate_under_data_root(request, row.zarr_path)
        if not resolved.exists():
            raise HTTPException(status_code=422, detail="zarr path missing on disk")
        source = ("zarr", str(resolved))
        layer_name = Path(row.zarr_path).stem
    elif row.st_path:
        resolved = validate_under_data_root(request, row.st_path)
        if not resolved.exists():
            raise HTTPException(status_code=422, detail="stack path missing on disk")
        source = ("st", str(resolved))
        layer_name = Path(row.st_path).stem
    else:
        frames_dir = _resolve_acq_frames_dir(
            session, request, sample_id, acquisition_id
        )
        if frames_dir is None:
            raise HTTPException(
                status_code=422,
                detail="no stack artifact and no acquisition Frames dir",
            )
        source = ("frames", str(frames_dir))
        layer_name = tilt_series_id

    def launch():
        from catalog.imaging._neuroglancer import view_neuroglancer

        kind, path = source
        if kind == "zarr":
            stack, median_idx, _angles = _load_zarr_stack(path)
        elif kind == "st":
            stack, median_idx, _angles = _load_st_stack(path)
        else:
            stack, median_idx, _angles = _load_frames_stack(path)
        return view_neuroglancer(
            stack,
            name=layer_name,
            voxel_size=(1.0, pixel_spacing, pixel_spacing),
            axis_names=("z", "y", "x"),
            layout="xy",
            contrast_percentile=(5, 95),
            initial_position=(median_idx, stack.shape[1] // 2, stack.shape[2] // 2),
        )

    url = await launch_viewer_in_registry(
        request, ("tilt_series", sample_id, acquisition_id, tilt_series_id), launch
    )
    return ViewerLaunchOut(url=url)
