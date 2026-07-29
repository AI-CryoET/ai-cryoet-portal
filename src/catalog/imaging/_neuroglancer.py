"""Neuroglancer viewer launch.

Originally vendored from
``aicryoet-tools/src/aicryoet_tools/visualization.py`` at commit ``083ccec``
(extract of ``view_neuroglancer`` only — the parent file imports
``napari`` at module top which we don't want pulled into the API).

The Neuroglancer server is process-global: ``neuroglancer.Viewer()``
implicitly starts an HTTP listener on first use (bound via
``NEUROGLANCER_BIND_ADDRESS``). The MVP requires uvicorn
``--workers 1 --no-reload`` because of this; multi-worker breaks viewer
launches (plan §11.9).

**Eviction caveat (plan §7.4):** the viewer object has no per-instance
``.stop()``; ``neuroglancer.stop()`` is process-global. The bounded LRU
in ``app.state.active_viewers`` evicts entries by dropping the registry's
reference, but the underlying viewer may linger in process memory until
GC. Restart the API to fully reset Neuroglancer state.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

import numpy as np

# Module-level flag mirroring the closure-style state on the vendored
# ``view_neuroglancer``. ``set_server_bind_address`` is process-global and
# must only be called once before the first Viewer() is created.
_BIND_ADDRESS_SET = False


def _ensure_bind_address() -> None:
    """Call ``neuroglancer.set_server_bind_address`` exactly once per process."""
    global _BIND_ADDRESS_SET
    if _BIND_ADDRESS_SET:
        return
    import neuroglancer

    bind_address = os.environ.get("NEUROGLANCER_BIND_ADDRESS", "0.0.0.0")
    bind_port = int(os.environ.get("NEUROGLANCER_PORT", "8050"))
    neuroglancer.set_server_bind_address(bind_address, bind_port=bind_port)
    _BIND_ADDRESS_SET = True


def view_neuroglancer(
    data: np.ndarray,
    *,
    name: str = "volume",
    voxel_size: tuple[float, float, float] = (1.0, 1.0, 1.0),
    axis_names: tuple[str, str, str] | str = "zyx",
    contrast_percentile: tuple[float, float] | None = (1, 99),
    layout: str | None = None,
    initial_position: tuple[float, ...] | None = None,
):
    """Open a Neuroglancer viewer over ``data`` and return the Viewer object.

    Mirrors X and Y to match IMOD convention (origin at lower-left, +X right,
    +Y up) — Neuroglancer's native convention is the opposite. The mirror is
    applied via the layer's coordinate transform, not by flipping the array,
    so the served volume keeps the memory-map's native layout (see below).
    2D inputs are promoted to 3D with a singleton Z.

    :param data: 2D or 3D numpy array.
    :param name: Layer name in the viewer.
    :param voxel_size: Voxel size in the same axis order as ``data``.
    :param axis_names: Axis names (slowest → fastest). Tuple or string.
    :param contrast_percentile: ``(low, high)`` percentiles for contrast.
        ``None`` lets Neuroglancer auto-scale.
    :param layout: Optional cross-section layout (e.g. ``"xy"``).
    :param initial_position: Optional initial cursor position.
    :return: The ``neuroglancer.Viewer`` instance.
    """
    import neuroglancer

    _ensure_bind_address()

    # Promote 2D → 3D.
    if data.ndim == 2:
        data = data[np.newaxis, ...]
        if isinstance(axis_names, str):
            axis_names = ("z",) + tuple(axis_names)
        else:
            axis_names = ("z",) + tuple(axis_names)

    if isinstance(axis_names, str):
        axis_names = list(axis_names)
    else:
        axis_names = list(axis_names)

    # Contrast from a central subvolume — much faster than scanning the
    # full data on multi-GB tomograms.
    contrast_range = None
    if contrast_percentile is not None:
        center = tuple(s // 2 for s in data.shape)
        radius = max(min(min(data.shape) // 4, 100), 1)
        slices = tuple(
            slice(max(0, c - radius), min(s, c + radius))
            for c, s in zip(center, data.shape)
        )
        subvol = data[slices]
        contrast_range = (
            float(np.percentile(subvol, contrast_percentile[0])),
            float(np.percentile(subvol, contrast_percentile[1])),
        )

    dimensions = neuroglancer.CoordinateSpace(
        names=axis_names,
        scales=voxel_size,
        units="nm",
    )

    # Mirror X and Y for IMOD orientation in the coordinate transform rather
    # than with np.flip on the array. Flipping the array would return a
    # negative-stride view that makes LocalVolume read chunks *backwards*
    # through the memory-map (poor locality over NFS). A -1 on the diagonal 
    # with a +(extent-1) translation reproduces np.flip exactly: 
    # output_index = (N-1) - input.
    n = len(axis_names)
    matrix = [[1.0 if i == j else 0.0 for j in range(n + 1)] for i in range(n)]
    for flip_axis in ("y", "x"):
        if flip_axis in axis_names:
            k = axis_names.index(flip_axis)
            matrix[k][k] = -1.0
            matrix[k][n] = float(data.shape[k] - 1)

    source = neuroglancer.LayerDataSource(
        url=neuroglancer.LocalVolume(data, dimensions=dimensions),
        transform=neuroglancer.CoordinateSpaceTransform(
            input_dimensions=dimensions,
            output_dimensions=dimensions,
            matrix=matrix,
        ),
    )

    viewer = neuroglancer.Viewer()
    with viewer.txn() as s:
        layer = neuroglancer.ImageLayer(source=source)
        if contrast_range is not None:
            layer.shader_controls = {
                "normalized": {"range": list(contrast_range)},
            }
        s.layers[name] = layer
        if layout is not None:
            s.layout = neuroglancer.row_layout([
                neuroglancer.LayerGroupViewer(layers=[name], layout=layout),
            ])
        if initial_position is not None:
            s.position = initial_position
        s.dimensions = dimensions # make the dimension global
    return viewer


def neuroglancer_url(viewer) -> str:
    """Return the viewer URL, applying ``DASHBOARD_HOSTNAME`` override if set."""
    url = str(viewer)
    hostname_override = os.environ.get("DASHBOARD_HOSTNAME")
    if hostname_override:
        parsed = urlparse(url)
        url = urlunparse(
            parsed._replace(netloc=f"{hostname_override}:{parsed.port}")
        )
    return url


def add_json_layer(viewer, name: str, json_data: dict):
    """Add JSON layer to viewer with a dict of ``json_data`` """
    with viewer.txn() as s:
        s.layers.append(name, json_data)


def bare_view_neuroglancer():
    """Blank neuroglancer viewer useful for viewing bboxes """
    import neuroglancer
    _ensure_bind_address()
    return neuroglancer.Viewer()
