"""MRC tomogram slice rendering for the preview endpoint.

Originally vendored from
``aicryoet-tools/src/aicryoet_tools/tomogram.py`` and
``aicryoet-tools/src/aicryoet_tools/web_utils.py`` at commit ``083ccec``.

This module exposes ``render_center_xy_slice_png(mrc_path)`` which returns
raw PNG bytes — never a data URI — so the FastAPI route can stream the
image with the right ``Content-Type`` and ETag headers (the dashboard
parent used base64 data URIs which we don't want over HTTP).

No matplotlib ``pyplot`` use — figures are built via the OO API
(``Figure() + FigureCanvasAgg``) so concurrent renders on the threadpool
don't share global state (plan §7.5 / §11.6).
"""
from __future__ import annotations

import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Literal

import mrcfile
import numpy as np
from loguru import logger
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


def _axis_index(mapc: int, mapr: int, maps: int, axis: Literal["x", "y", "z"]) -> int:
    """Return the numpy-array index for a physical axis given MRC mapc/mapr/maps."""
    axis_num = {"x": 1, "y": 2, "z": 3}[axis]
    if maps == axis_num:
        return 0
    if mapr == axis_num:
        return 1
    if mapc == axis_num:
        return 2
    raise ValueError(f"axis {axis!r} not present in MRC axis mapping")


def _center_xy_slice(mrc_path: Path) -> np.ndarray:
    """Read an MRC and return the center XY slice as a 2D float32 array.

    Uses the header's ``mapc/mapr/maps`` axis mapping (1=X, 2=Y, 3=Z) so the
    returned slice is the physical-XY plane regardless of the underlying
    storage order — matching ``Tomogram.center_xy_slice`` in the vendored
    source.
    """
    with mrcfile.open(str(mrc_path), mode="r", permissive=True) as mrc:
        mapc = int(mrc.header.mapc)
        mapr = int(mrc.header.mapr)
        maps = int(mrc.header.maps)
        z_idx = _axis_index(mapc, mapr, maps, "z")
        z_center = mrc.data.shape[z_idx] // 2
        slice_2d = np.take(mrc.data, z_center, axis=z_idx)
    return np.asarray(slice_2d, dtype=np.float32)


def read_mrc_middle_slice(mrc_path: Path | str) -> np.ndarray:
    """Return the middle slice along axis 0 of an MRC stack as a 2D float32 array.

    Memory-maps the file and materializes only that one plane, so peak memory is
    a single 2D image rather than the whole (often multi-GB) stack that
    ``read_mrc_volume`` reads-and-copies. For ``.st``/``.mrc`` tilt stacks axis 0
    is the tilt index, so this is the median-tilt projection — all the thumbnail
    / preview renderers need.
    """
    with mrcfile.mmap(str(mrc_path), mode="r", permissive=True) as mrc:
        median_idx = mrc.data.shape[0] // 2
        # np.array (not asarray) forces a copy so the result outlives the mmap.
        return np.array(mrc.data[median_idx], dtype=np.float32)


def _downscale_local_mean(arr: np.ndarray, target_width: int) -> np.ndarray:
    """Area-average ``arr`` down to roughly ``target_width`` px wide.

    A raw tilt projection is ~4k px wide but previews render at 512-800 px.
    Nearest-neighbour subsampling at that ratio keeps every surviving pixel's
    full shot noise (the "snow" previews), so instead we average each
    ``factor x factor`` block — cutting noise by ~``sqrt(block area)`` while
    preserving real structure. No-op when the source already fits the target.
    """
    if arr.ndim != 2:
        return arr
    factor = arr.shape[1] // target_width
    if factor <= 1:
        return arr
    h = (arr.shape[0] // factor) * factor
    w = (arr.shape[1] // factor) * factor
    binned = arr[:h, :w].reshape(h // factor, factor, w // factor, factor)
    return binned.mean(axis=(1, 3))


def _array_to_png_bytes(
    arr: np.ndarray,
    *,
    percentile: tuple[float, float] = (1, 99),
    width: int = 1200,
    cmap: str = "gray",
) -> bytes:
    """Render a 2D array as a PNG with percentile contrast clipping.

    The array is first area-averaged down to the output ``width`` (see
    ``_downscale_local_mean``) so large, noisy projections don't render as
    snow; the percentile window is then computed on those displayed pixels.

    Uses the matplotlib OO API (``Figure() + FigureCanvasAgg``); no
    ``pyplot`` global state so concurrent renders on the threadpool are
    safe.
    """
    arr = _downscale_local_mean(arr, width)
    vmin, vmax = np.percentile(arr, percentile)
    aspect = arr.shape[0] / arr.shape[1] if arr.shape[1] else 1.0
    dpi = 100
    fig_w = width / dpi
    fig_h = fig_w * aspect

    fig = Figure(figsize=(fig_w, fig_h), dpi=dpi)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="antialiased")
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    buf = BytesIO()
    canvas.print_png(buf)
    return buf.getvalue()


def render_center_xy_slice_png(mrc_path: Path | str, *, width: int = 1200) -> bytes:
    """Render the center XY slice of an MRC volume as PNG bytes.

    :param mrc_path: Path to the MRC file. Should already be path-validated
        against ``CATALOG_DATA_ROOT`` by the caller (route handler).
    :param width: Output image width in pixels.
    :return: PNG image bytes.
    """
    slice_2d = _center_xy_slice(Path(mrc_path))
    return _array_to_png_bytes(slice_2d, percentile=(1, 99), width=width)


# Volumes at or below this size are read fully into RAM so Neuroglancer serves
# chunks from memory (fast, no per-chunk NFS reads) — this is what keeps
# concurrent viewers from serializing on blocking NFS reads in the single
# in-process server. Larger volumes fall back to mmap: slow to serve, but the
# pod won't OOM. Sized just above the ~1.3 GB production ceiling; a volume that
# trips the fallback is the signal it's time for Phase 2 (multi-process pool).
COPY_MAX_BYTES = int(1.5 * 1024**3)


def _load_mrc_volume(mrc_path: str) -> tuple[np.ndarray, tuple[float, float, float], str]:
    """Load an MRC into ``(data, voxel_size_nm_in_array_order, axis_order)``.

    ``data`` is an in-RAM copy for volumes ≤ ``COPY_MAX_BYTES`` (fast chunk
    serving, no per-chunk NFS), or a read-only ``mmap`` for larger volumes
    (slow serving, but bounded memory so the pod survives).
    """
    size = os.path.getsize(mrc_path)
    use_copy = size <= COPY_MAX_BYTES
    if not use_copy:
        logger.warning(
            "MRC {} is {:.1f} GB (> {:.1f} GB COPY_MAX_BYTES); serving via mmap "
            "(slow per-chunk). Large volumes are the Phase 2 trigger.",
            mrc_path,
            size / 1024**3,
            COPY_MAX_BYTES / 1024**3,
        )

    # Copy path: read into RAM then close. mmap path: keep the handle open —
    # numpy keeps the map alive via data.base, but closing here would unmap it.
    mrc = (mrcfile.open if use_copy else mrcfile.mmap)(
        mrc_path, mode="r", permissive=True
    )
    data = mrc.data.copy() if use_copy else mrc.data
    # MRC headers store spacing in Angstrom; Neuroglancer is told nm.
    vx = float(mrc.voxel_size.x) / 10.0
    vy = float(mrc.voxel_size.y) / 10.0
    vz = float(mrc.voxel_size.z) / 10.0
    mapc = int(mrc.header.mapc)
    mapr = int(mrc.header.mapr)
    maps = int(mrc.header.maps)
    if use_copy:
        mrc.close()

    axis_names = {1: "x", 2: "y", 3: "z"}
    axis_order = f"{axis_names[maps]}{axis_names[mapr]}{axis_names[mapc]}"
    voxel_map = {"x": vx, "y": vy, "z": vz}
    voxel_size = (
        voxel_map[axis_order[0]],
        voxel_map[axis_order[1]],
        voxel_map[axis_order[2]],
    )
    return data, voxel_size, axis_order


# Shared across concurrent viewers: two tabs on the same tomogram share one
# read-only array instead of each copying it — the dominant memory saving when
# people view the same dataset. Keyed on (path, mtime) so a re-scan that rewrites
# the file invalidates automatically. maxsize is aligned with
# NEUROGLANCER_MAX_VIEWERS (12); raising that env var means bumping this too.
@lru_cache(maxsize=12)
def _load_mrc_volume_cached(
    mrc_path: str, mtime: float
) -> tuple[np.ndarray, tuple[float, float, float], str]:
    return _load_mrc_volume(mrc_path)


def read_mrc_volume(
    mrc_path: Path | str,
) -> tuple[np.ndarray, tuple[float, float, float], str]:
    """Load an MRC volume + voxel size (nm, array-axis order) + axis order.

    Returns ``(data, voxel_size, axis_order)``. ``data`` is an in-RAM copy for
    volumes ≤ ``COPY_MAX_BYTES`` (Neuroglancer serves chunks from memory), or a
    read-only ``np.memmap`` for larger volumes (bounded memory, slower serving).

    Voxel size is returned in **nm** (MRC headers are Angstrom): ``view_neuroglancer``
    builds a ``CoordinateSpace(units="nm")``, and Neuroglancer rejects ``"angstrom"``.

    Results are cached process-wide, keyed on ``(path, mtime)`` (see
    ``_load_mrc_volume_cached``), so concurrent viewers of the same unchanged
    file share one array instead of each holding a separate copy.
    """
    p = str(mrc_path)
    return _load_mrc_volume_cached(p, os.path.getmtime(p))
