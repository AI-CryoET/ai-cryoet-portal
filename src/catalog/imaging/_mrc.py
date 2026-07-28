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

from io import BytesIO
from pathlib import Path
from typing import Literal

import mrcfile
import numpy as np
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


def read_mrc_volume(mrc_path: Path | str) -> tuple[np.ndarray, tuple[float, float, float], str]:
    """Memory-map the full MRC volume + voxel size + axis order for Neuroglancer.

    Returns ``(data, voxel_size_in_array_order, axis_order_string)`` where
    ``data`` is a **read-only memory-map** (``mrcfile.mmap``), *not* a heap
    copy. Neuroglancer's ``LocalVolume`` wraps it lazily and serves chunks
    straight from the map, so a launch pages in only the voxels the browser
    actually views instead of reading the whole (often multi-GB) volume into
    the API process. That eager ``.copy()`` was the dominant cause of OOM
    kills under concurrent viewers — mmap makes retained viewers cost shared,
    reclaimable page cache rather than pinned heap.

    The map safely outlives the ``MrcFile`` handle: numpy keeps the underlying
    ``mmap`` alive through ``data.base`` independently of the ``MrcFile``
    object, so callers can hold just the returned array.

    Voxel size is reordered to match the array axes (slowest → fastest), so
    callers can feed it directly into ``view_neuroglancer``.

    Voxel size is returned in **nm**, unlike the rest of the codebase which
    carries MRC spacings in Angstrom (``voxel_spacing_angstrom``,
    ``schema.py`` ``voxel_size``). Don't "fix" this back for consistency:
    ``view_neuroglancer`` builds a ``CoordinateSpace(units="nm")``, and
    Neuroglancer only accepts an SI base unit with a standard prefix —
    ``"angstrom"`` and ``"Å"`` both raise. nm is the nearest unit that can
    express an MRC spacing at all.
    """
    # Not a `with` block: closing the MrcFile would unmap the memory the
    # returned array (and the eventual LocalVolume) reads from.
    mrc = mrcfile.mmap(str(mrc_path), mode="r", permissive=True)
    data = mrc.data

    # MRC headers store spacing in Angstrom; Neuroglancer is told nm.
    vx = float(mrc.voxel_size.x) / 10.0
    vy = float(mrc.voxel_size.y) / 10.0
    vz = float(mrc.voxel_size.z) / 10.0
    mapc = int(mrc.header.mapc)
    mapr = int(mrc.header.mapr)
    maps = int(mrc.header.maps)
    axis_names = {1: "x", 2: "y", 3: "z"}
    axis_order = f"{axis_names[maps]}{axis_names[mapr]}{axis_names[mapc]}"
    voxel_map = {"x": vx, "y": vy, "z": vz}
    voxel_size = (voxel_map[axis_order[0]], voxel_map[axis_order[1]], voxel_map[axis_order[2]])
    return data, voxel_size, axis_order
