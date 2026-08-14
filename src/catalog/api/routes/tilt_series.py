"""Per-tilt-series preview endpoints.

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

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.path_validation import validate_under_data_root
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


@lru_cache(maxsize=64)
def _cached_tilt_preview_png(kind: str, src: str, mtime: float) -> bytes:
    """LRU-cached median-tilt render keyed on ``(kind, src, mtime)``.

    ``mtime`` is in the key so a re-scan/re-write invalidates the entry (mirrors
    ``tomograms._cached_preview_png``). ``kind`` selects the renderer so the
    three sources never collide on a shared path string.
    """
    if kind == "zarr":
        return render_zarr_median_png(src)
    if kind == "st":
        return render_st_median_png(src)
    return render_frames_median_png(src)


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
        kind, src = "zarr", str(resolved)
    elif row.st_path:
        resolved = validate_under_data_root(request, row.st_path)
        if not resolved.exists():
            raise HTTPException(status_code=422, detail="stack path missing on disk")
        kind, src = "st", str(resolved)
    else:
        frames_dir = _resolve_acq_frames_dir(
            session, request, sample_id, acquisition_id
        )
        if frames_dir is None:
            raise HTTPException(
                status_code=422,
                detail="no stack artifact and no acquisition Frames dir",
            )
        kind, src = "frames", str(frames_dir)

    # ETag = source kind + path + mtime — a cheap stat lets a revalidating
    # browser 304 out *before* we touch the (expensive) renderer.
    mtime = Path(src).stat().st_mtime
    etag = f'W/"{hashlib.md5(f"{kind}:{src}:{mtime}".encode()).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    try:
        png_bytes = await run_in_threadpool(
            _cached_tilt_preview_png, kind, src, mtime
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"ETag": etag, "Cache-Control": "public, max-age=3600"},
    )
