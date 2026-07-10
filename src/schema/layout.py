"""Shared on-disk layout helper for the two-arm data root.

The canonical data root has two top-level arms::

    {data_root}/
      Experimental/{sample_id}/ ...                 -> data_source = experimental
      MdSimulation/{SubDir}/{sample_id}/ ...         -> data_source = simulation

where ``SubDir`` is one of the four dataset-type directories
(``Bulk`` / ``SingleMolecule`` / ``Slab``).

``infer_arm`` is the single place that knows the directory -> enum mapping.
The catalog scanner uses it during discovery; the ``validate`` CLI uses it so
a researcher running ``pixi run validate {sample_dir}`` inside the reorganized
tree gets the same ``dataset_type`` / ``data_source`` the scanner will assign.

Lives in ``schema/`` (rather than ``catalog/``) so both the pure validator and
the catalog scanner can import it; ``catalog`` already depends on ``schema``.
"""

from __future__ import annotations

from pathlib import Path

from schema.schema import DataSource, DatasetType

TOP_LEVEL_EXPERIMENTAL = "Experimental"
TOP_LEVEL_MD_SIMULATION = "MdSimulation"

# Multi-suffix Zarr extensions. ``entity_id_from_path`` strips the longest match
# first so ``.ome.zarr`` wins over ``.zarr`` (Path.stem would leave ``foo.ome``).
ZARR_DIR_SUFFIXES = (".zarr", ".ome.zarr")

DATASET_TYPE_BY_DIR: dict[str, DatasetType] = {
    "Bulk": DatasetType.bulk,
    "SingleMolecule": DatasetType.single_molecule,
    "Slab": DatasetType.slab,
}


def entity_id_from_path(path: Path) -> str:
    """Return an entity id (tomogram/annotation) from a file/dir ``path``.

    The id is the filename with its extension stripped. A multi-suffix Zarr
    extension (``.zarr`` / ``.ome.zarr``, per :data:`ZARR_DIR_SUFFIXES`) is
    stripped as a whole — ``Path.stem`` would turn ``foo.ome.zarr`` into
    ``foo.ome`` and split it from its ``foo.mrc`` sibling. Otherwise only the
    single final suffix is stripped::

        foo.mrc       -> foo
        foo.zarr      -> foo
        foo.ome.zarr  -> foo

    So a tomogram's ``.mrc`` and matching ``.ome.zarr`` collapse to one id.
    """
    name = path.name
    # Longest Zarr suffix first so ``.ome.zarr`` wins over ``.zarr``.
    for suffix in sorted(ZARR_DIR_SUFFIXES, key=len, reverse=True):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def infer_arm(
    sample_dir: Path,
) -> tuple[DataSource | None, DatasetType | None]:
    """Infer ``(data_source, dataset_type)`` from a sample dir's ancestry.

    - ``.../Experimental/{sample}``           -> ``(experimental, None)``
    - ``.../MdSimulation/{SubDir}/{sample}``   -> ``(simulation, DATASET_TYPE_BY_DIR[SubDir])``

    Returns ``(None, None)`` when the path doesn't match either layout (flat /
    legacy dir) so callers can fall back to the TOML-authored value.
    """
    parents = sample_dir.parents
    # Experimental: parent dir is named "Experimental".
    if len(parents) >= 1 and parents[0].name == TOP_LEVEL_EXPERIMENTAL:
        return DataSource.experimental, None
    # MdSimulation: grandparent is "MdSimulation", parent is the <SubDir>.
    if len(parents) >= 2 and parents[1].name == TOP_LEVEL_MD_SIMULATION:
        sub_dir = parents[0].name
        dataset_type = DATASET_TYPE_BY_DIR.get(sub_dir)
        if dataset_type is not None:
            return DataSource.simulation, dataset_type
    return None, None


__all__ = [
    "DATASET_TYPE_BY_DIR",
    "TOP_LEVEL_EXPERIMENTAL",
    "TOP_LEVEL_MD_SIMULATION",
    "ZARR_DIR_SUFFIXES",
    "entity_id_from_path",
    "infer_arm",
]


if __name__ == "__main__":
    # ponytail: minimal self-check for the stem rule — the one non-trivial bit.
    assert entity_id_from_path(Path("foo.mrc")) == "foo"
    assert entity_id_from_path(Path("foo.zarr")) == "foo"
    assert entity_id_from_path(Path("foo.ome.zarr")) == "foo"
    # .mrc and .ome.zarr for the same tomogram must collapse to one id.
    assert entity_id_from_path(Path("a/b/foo.ome.zarr")) == entity_id_from_path(
        Path("a/b/foo.mrc")
    )
    assert entity_id_from_path(Path("no_ext")) == "no_ext"
    print("schema.layout self-check OK")
