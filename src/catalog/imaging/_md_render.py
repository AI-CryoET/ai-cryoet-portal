"""Render LAMMPS MD dump files to preview PNGs using OVITO's TachyonRenderer.

Function-extracted from ``aicryoet-tools`` (``md_rendering.py``), following the
same §11.6 doctrine as the rest of :mod:`catalog.imaging`: we copy the rendering
logic and own it here — bug fixes won't auto-flow between repos.

Renders coarse-grained chromatin snapshots with ellipsoidal nucleosome cores,
spherical DNA beads, ambient occlusion and per-type coloring. OVITO drags in a
PySide6/Qt stack and is a heavyweight, optional dependency (the ``catalog`` pixi
feature), so:

* the ``ovito`` imports live inside :func:`_render`, never at module top, so
  importing this module (or the scanner) doesn't require OVITO to be installed;
* rendering runs in a **subprocess** so OVITO's Qt initialization, its import
  cost, and any native crash on a malformed dump stay isolated from the
  long-lived scanner/API process, and a per-render timeout can bound a stuck
  render.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Per-render wall-clock cap (seconds). A pathological dump shouldn't be able to
# stall a whole catalog scan.
_RENDER_TIMEOUT = 120


def render_md_dump_preview(
    dump_path: Path,
    output_path: Path,
    *,
    frame: int = -1,
    width: int = 1200,
    height: int = 900,
    wrap_periodic: bool = False,
    dna_bead_scale: float = 1.0,
) -> Path:
    """Render a LAMMPS dump file to a PNG snapshot using OVITO.

    Runs in a subprocess to isolate OVITO's Qt stack from the caller.

    Particles are drawn at their literal coarse-grained size: nucleosome cores
    render as 56x56x40 Å ellipsoid pancakes and DNA beads as small spheres,
    using the per-type ``c_shape`` columns when present (see ``dna_bead_scale``).
    Coloring follows the shared ``PARTICLE_TYPES`` palette (nucleosome blue,
    linker DNA green, wrapped DNA yellow).

    :param dump_path: Path to the LAMMPS dump file.
    :param output_path: Where to save the PNG.
    :param frame: Which frame to render (-1 for last).
    :param width: Image width in pixels.
    :param height: Image height in pixels.
    :param wrap_periodic: Wrap atoms back into the periodic box before
        rendering (needed for ``xu yu zu`` dumps that store unwrapped
        coordinates).
    :param dna_bead_scale: Multiplier applied to the DNA bead radii (types 2 and
        3) only. ``1.0`` (default) renders the literal CG DNA bead size (24 Å
        sphere, 12 Å radius). Values >1 inflate the beads so adjacent ones
        overlap into a smoother continuous backbone (e.g. 1.4 closes the
        ~16–24 Å inter-bead gaps). Nucleosome pancakes (type 1) are always left
        at their true size.
    :return: The output path.
    :raises RuntimeError: if the OVITO subprocess fails or times out.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps({
        "dump_path": str(dump_path),
        "output_path": str(output_path),
        "frame": frame,
        "width": width,
        "height": height,
        "wrap_periodic": wrap_periodic,
        "dna_bead_scale": dna_bead_scale,
    })

    # OVITO renders headless. If OVITO came from a pip wheel its Qt libs live
    # under PySide6/Qt/lib and may need to be on LD_LIBRARY_PATH; the conda
    # build ships its own, so the guard below is a no-op there.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    pyside6_qt_lib = (
        Path(sys.prefix) / f"lib/{pyver}/site-packages/PySide6/Qt/lib"
    ).resolve()
    if pyside6_qt_lib.is_dir():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (
            f"{pyside6_qt_lib}:{existing}" if existing else str(pyside6_qt_lib)
        )

    # Invoke this file by path (not ``-m``) so the subprocess doesn't import the
    # ``catalog`` package — keeps the isolated process minimal.
    script = str(Path(__file__).resolve())
    try:
        result = subprocess.run(
            [sys.executable, script, payload],
            capture_output=True,
            text=True,
            env=env,
            timeout=_RENDER_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"OVITO render timed out after {_RENDER_TIMEOUT}s: {dump_path}"
        ) from exc

    if result.returncode != 0:
        logger.error("OVITO render failed: %s", result.stderr)
        raise RuntimeError(f"OVITO render failed: {result.stderr}")

    logger.debug("rendered %s -> %s", dump_path, output_path)
    return output_path


# ---------------------------------------------------------------------------
# Subprocess entry point (runs in an isolated process that imports OVITO)
# ---------------------------------------------------------------------------

# Canonical coarse-grained chromatin palette, shared with the dashboard legend
# and the aicryoet-simulation figures. Inlined (not imported from a shared
# constants module) because the subprocess deliberately avoids importing the
# parent package.
_PARTICLE_TYPES: dict[int, tuple[str, tuple[float, float, float]]] = {
    1: ("Histone", (0.12, 0.47, 0.71)),     # nucleosome — blue
    2: ("Linker DNA", (0.17, 0.63, 0.17)),  # linker DNA — green
    3: ("Bound DNA", (0.90, 0.72, 0.00)),   # wrapped DNA — yellow
}
_PARTICLE_RADII: dict[int, float] = {1: 28.0, 2: 12.0, 3: 12.0}

# LAMMPS dump column name → OVITO property mapping. OVITO auto-detects standard
# names (id, type, xu, yu, zu, mol, etc.) but custom compute columns need
# explicit mapping.
_LAMMPS_TO_OVITO = {
    "c_q[1]": "Orientation.W",
    "c_q[2]": "Orientation.X",
    "c_q[3]": "Orientation.Y",
    "c_q[4]": "Orientation.Z",
    "c_shape[1]": "Aspherical Shape.X",
    "c_shape[2]": "Aspherical Shape.Y",
    "c_shape[3]": "Aspherical Shape.Z",
}

_STANDARD_COLUMNS = {
    "id": "Particle Identifier",
    "type": "Particle Type",
    "mol": "Molecule Identifier",
    "x": "Position.X", "y": "Position.Y", "z": "Position.Z",
    "xu": "Position.X", "yu": "Position.Y", "zu": "Position.Z",
    "xs": "Position.X", "ys": "Position.Y", "zs": "Position.Z",
    "xsu": "Position.X", "ysu": "Position.Y", "zsu": "Position.Z",
    "ix": "Periodic Image.X", "iy": "Periodic Image.Y", "iz": "Periodic Image.Z",
    "q": "Charge",
    "fx": "Force.X", "fy": "Force.Y", "fz": "Force.Z",
}


def _read_atoms_header(dump_path: str) -> list[str]:
    """Return the column names from the first ``ITEM: ATOMS`` line."""
    with open(dump_path) as f:
        for line in f:
            if line.startswith("ITEM: ATOMS"):
                return line[len("ITEM: ATOMS"):].split()
    return []


def _build_column_mapping(dump_path: str) -> list[str | None]:
    """Read the ITEM: ATOMS header and return an OVITO column list.

    Maps standard LAMMPS names automatically and applies custom mappings for
    quaternion/shape computes. Unrecognized columns map to ``None`` so OVITO
    ignores them (rather than inventing a user property from the raw header
    name, which can collide with reserved names across OVITO versions).
    """
    return [
        _LAMMPS_TO_OVITO.get(n, _STANDARD_COLUMNS.get(n))
        for n in _read_atoms_header(dump_path)
    ]


def _has_shape(dump_path: str) -> bool:
    """Check if a LAMMPS dump file carries the asphere ``c_shape`` columns."""
    return "c_shape[1]" in _read_atoms_header(dump_path)


def _render(args: dict) -> None:
    """Actual rendering logic, called in the subprocess."""
    import numpy as np
    from ovito.io import import_file
    from ovito.modifiers import (
        ComputePropertyModifier,
        DeleteSelectedModifier,
        ExpressionSelectionModifier,
    )
    from ovito.vis import ParticlesVis, TachyonRenderer, Viewport

    dump_path = args["dump_path"]
    output_path = args["output_path"]
    frame = args["frame"]
    width = args["width"]
    height = args["height"]
    dna_bead_scale = float(args.get("dna_bead_scale", 1.0))

    pipeline = import_file(dump_path, columns=_build_column_mapping(dump_path))
    loaded_path = dump_path

    if frame < 0:
        frame = pipeline.source.num_frames + frame

    is_cores = "cores" in dump_path

    if is_cores:
        # For a cores dump, load the matching full dna dump from the same
        # directory but delete DNA particles so only histone cores are visible.
        # This keeps the same structure and camera angle as the full view.
        # Numbered segments (dna_1.dump) sort after the plain dna.dump, so this
        # picks the same file _choose_dump would have preferred.
        dna_matches = sorted(Path(dump_path).parent.glob("dna*.dump"))
        if dna_matches:
            dna_path = str(dna_matches[0])
            pipeline = import_file(dna_path, columns=_build_column_mapping(dna_path))
            loaded_path = dna_path
            if frame < 0:
                frame = pipeline.source.num_frames + frame
            # Select and delete non-histone particles (keep only type 1). The
            # per-type styling below colors the survivors blue.
            pipeline.modifiers.append(
                ExpressionSelectionModifier(expression="ParticleType != 1")
            )
            pipeline.modifiers.append(DeleteSelectedModifier())

    if args.get("wrap_periodic"):
        from ovito.modifiers import WrapPeriodicImagesModifier
        pipeline.modifiers.append(WrapPeriodicImagesModifier())

    has_shape = _has_shape(loaded_path)

    # Diameter-vs-radius fix: the LAMMPS dump stores per-particle ``c_shape``
    # columns as **diameters** (56x56x40 for the nucleosome pancake, 24 for the
    # DNA spheres), but OVITO's ``Aspherical Shape`` property is interpreted as
    # **half-extents (radii)** and drives ellipsoidal rendering — so without the
    # /2 every bead renders at 2x its literal CG size. DNA beads (types 2 and 3)
    # are additionally scaled by ``dna_bead_scale`` so consecutive beads
    # (~16–24 Å apart) overlap into a continuous backbone rather than reading as
    # a string of separate dots; nucleosomes (type 1) keep their literal size.
    if has_shape:
        dna_expr = "%g * AsphericalShape.%%s / 2" % dna_bead_scale
        pipeline.modifiers.append(
            ComputePropertyModifier(
                output_property="Aspherical Shape",
                expressions=tuple(
                    f"ParticleType==1 ? AsphericalShape.{c}/2 : {dna_expr % c}"
                    for c in ("X", "Y", "Z")
                ),
            )
        )

    # Per-type color (shared CG palette) and fallback sphere radius. DNA bead
    # radii get the same ``dna_bead_scale`` so dumps lacking ``c_shape`` still
    # render a connected backbone.
    colors = {tid: color for tid, (_, color) in _PARTICLE_TYPES.items()}
    radii = {
        tid: (r * dna_bead_scale if tid in (2, 3) else r)
        for tid, r in _PARTICLE_RADII.items()
    }

    def style_types(frame, data):
        type_property = data.particles_.particle_types_
        for type_obj in type_property.types_:
            if type_obj.id in colors:
                type_obj.color = colors[type_obj.id]
            if type_obj.id in radii:
                type_obj.radius = radii[type_obj.id]

    pipeline.modifiers.append(style_types)

    vis = pipeline.source.data.particles.vis
    if not has_shape:
        # No ellipsoid data — draw plain spheres at the per-type fallback radii.
        vis.shape = ParticlesVis.Shape.Sphere
    vis.radius = max(radii.values())  # fallback for untyped particles

    pipeline.source.data.cell.vis.enabled = False
    pipeline.add_to_scene()

    # Evaluate the pipeline at the actual render frame (zoom_all would otherwise
    # use frame 0, whose bounding box can be wildly different after unwrapped
    # atoms have drifted across the simulation).
    data = pipeline.compute(frame)
    pos = np.asarray(data.particles.positions)
    # Account for particle radii so spheres/ellipsoids aren't clipped at the
    # edges. Prefer the (post-/2) aspherical half-extents when present;
    # otherwise fall back to the largest per-type sphere radius.
    r_max = 0.0
    try:
        shape = np.asarray(data.particles["Aspherical Shape"])
        if shape.size:
            r_max = float(shape.max())
    except (KeyError, IndexError):
        pass
    if r_max == 0.0:
        r_max = max(radii.values())

    lo = pos.min(axis=0) - r_max
    hi = pos.max(axis=0) + r_max
    center = (lo + hi) / 2.0
    # Use the full diagonal as the bounding-sphere diameter so the object fits
    # regardless of viewing angle.
    radius = float(np.linalg.norm(hi - lo) / 2.0)

    # 3/4 orthographic view with z-axis pointing up in screen space. Ortho keeps
    # framing simple: fov = half-height of view in world units.
    cam_dir = np.array([-2.0, -1.0, -1.0])
    cam_dir /= np.linalg.norm(cam_dir)
    # Place the camera outside the bounding sphere (distance doesn't affect
    # projected size in ortho, but must clear the geometry).
    cam_pos = center - cam_dir * (radius * 3.0)

    # For a 4:3 image, fov (half-height) = radius * 1.1 ensures the worst-case
    # diagonal still fits with ~10% margin.
    vp = Viewport(
        type=Viewport.Type.Ortho,
        camera_dir=tuple(cam_dir),
        camera_up=(0, 0, 1),
        camera_pos=tuple(cam_pos),
        fov=radius * 1.1,
    )

    renderer = TachyonRenderer(
        shadows=True,
        ambient_occlusion=True,
        ambient_occlusion_brightness=0.8,
        direct_light_intensity=0.9,
        antialiasing_samples=12,
    )

    vp.render_image(
        size=(width, height),
        filename=output_path,
        background=(1, 1, 1),
        renderer=renderer,
        frame=frame,
    )
    pipeline.remove_from_scene()


if __name__ == "__main__":
    _render(json.loads(sys.argv[1]))
