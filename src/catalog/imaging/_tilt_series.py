"""Median/middle tilt-series image rendering.

Shared by the on-demand preview endpoint (``routes/tilt_series.py``) and the
scan-time thumbnail cache (``catalog.thumbnails``). Source-resolution order
mirrors the tilt-series plan §5: prefer the authored ``Stack/`` zarr store,
then the ``.st``/``.mrc`` projection stack, finally the acquisition's raw
``Frames/`` images (shared by all the acquisition's tilt series).

No matplotlib ``pyplot`` use — rendering goes through ``_array_to_png_bytes``
(``Figure() + FigureCanvasAgg``) so concurrent threadpool renders are safe.
"""
from __future__ import annotations

from pathlib import Path

# Default preview width; the thumbnail cache overrides this with a smaller one.
TILT_PREVIEW_WIDTH = 800


def render_zarr_median_png(zarr_path: str, *, width: int = TILT_PREVIEW_WIDTH) -> bytes:
    """Read the median-tilt frame from a zarr store and render to PNG bytes."""
    import numpy as np
    import zarr

    from catalog.imaging._mrc import _array_to_png_bytes

    root = zarr.open_group(zarr_path, mode="r")
    ds = root["tilt_series"]
    tilt_angles = list(root.attrs.get("tilt_angles", []))
    if tilt_angles:
        median_angle = float(np.median(tilt_angles))
        median_idx = min(
            range(len(tilt_angles)),
            key=lambda i: abs(tilt_angles[i] - median_angle),
        )
    else:
        median_idx = ds.shape[0] // 2
    img = np.array(ds[median_idx], dtype=np.float32)
    return _array_to_png_bytes(img, percentile=(5, 95), width=width)


def render_st_median_png(st_path: str, *, width: int = TILT_PREVIEW_WIDTH) -> bytes:
    """Render the middle projection of an ``.st``/``.mrc`` tilt stack to PNG."""
    from catalog.imaging._mrc import _array_to_png_bytes, read_mrc_middle_slice

    # Memmap + slice: never materializes the full (multi-GB) stack, only the
    # one median-tilt plane we render. See read_mrc_middle_slice.
    img = read_mrc_middle_slice(st_path)
    return _array_to_png_bytes(img, percentile=(2, 98), width=width)


def render_frames_median_png(frames_dir: str, *, width: int = TILT_PREVIEW_WIDTH) -> bytes:
    """Find the median-angle TIFF/MRC tilt in ``frames_dir`` and render it."""
    import numpy as np

    from loguru import logger

    from catalog.imaging._mrc import _array_to_png_bytes
    from catalog.imaging._tilt_image import (
        apply_gain_correction,
        find_eer_tilt_images,
        find_gain_reference,
        find_viewable_tilt_images,
        load_gain_reference,
        load_tilt_image,
    )

    # Prefer fast TIFF/MRC siblings; fall back to EER for EER-only acquisitions.
    tilt_images = find_viewable_tilt_images(Path(frames_dir))
    if not tilt_images:
        tilt_images = find_eer_tilt_images(Path(frames_dir))
    if not tilt_images:
        raise FileNotFoundError("no viewable tilt images")
    angles = [a for a, _ in tilt_images]
    median_angle = float(np.median(angles))
    _, center_path = min(tilt_images, key=lambda x: abs(x[0] - median_angle))

    img = load_tilt_image(center_path, gain=None, preview=True).astype(np.float32)

    # EER frames are raw detector frames, so gain-correct them with the
    # acquisition's sibling Gains/ reference. .st/.mrc/zarr stacks are already
    # corrected upstream and TIFF/MRC frames are left as-is. The preview is
    # cosmetic, so a missing/unreadable/shape-mismatched gain (e.g. an 8K/16K
    # reference against the 4K EER render) must never 500 the endpoint — on any
    # failure we log and fall back to the uncorrected image rather than raising.
    if center_path.suffix.lower() == ".eer":
        try:
            gain_path = find_gain_reference(Path(frames_dir))
            if gain_path is not None:
                gain = load_gain_reference(gain_path)
                img = apply_gain_correction(img, gain).astype(np.float32)
        except Exception as exc:  # noqa: BLE001 — cosmetic preview, degrade gracefully
            logger.warning(
                "EER gain correction failed for {}; rendering preview without gain: {}",
                center_path,
                exc,
            )

    return _array_to_png_bytes(img, percentile=(2, 98), width=width)


def render_tilt_series_median_png_with_source(
    *,
    zarr_path: str | None = None,
    st_path: str | None = None,
    frames_dir: str | None = None,
    width: int = TILT_PREVIEW_WIDTH,
) -> tuple[bytes, str, str | None]:
    """Render the median-tilt image and report which source actually rendered.

    Tries zarr → ``.st``/``.mrc`` → raw frames, in that order. Returns
    ``(png_bytes, source_kind, source_path)`` where ``source_kind`` is one of
    ``"zarr"``/``"st"``/``"frames"`` and ``source_path`` is the concrete path
    the preview was rendered from (post-fallback). Paths are assumed already
    resolved/trusted by the caller (the scan pipeline only passes paths
    discovered under the data root). Raises ``FileNotFoundError`` when no
    source is available.
    """
    if zarr_path:
        return render_zarr_median_png(zarr_path, width=width), "zarr", zarr_path
    if st_path:
        return render_st_median_png(st_path, width=width), "st", st_path
    if frames_dir:
        return (
            render_frames_median_png(frames_dir, width=width),
            "frames",
            frames_dir,
        )
    raise FileNotFoundError("no tilt-series source (zarr/st/frames) available")


def render_tilt_series_median_png(
    *,
    zarr_path: str | None = None,
    st_path: str | None = None,
    frames_dir: str | None = None,
    width: int = TILT_PREVIEW_WIDTH,
) -> bytes:
    """Render the median-tilt image from the first available source (bytes only).

    Thin wrapper over :func:`render_tilt_series_median_png_with_source` that
    drops the source provenance — kept for callers (e.g. the on-demand preview
    endpoint) that only need the PNG bytes.
    """
    png, _kind, _path = render_tilt_series_median_png_with_source(
        zarr_path=zarr_path,
        st_path=st_path,
        frames_dir=frames_dir,
        width=width,
    )
    return png
