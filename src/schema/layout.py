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

# Reconstruction file allowlists — the single source of truth shared by the
# catalog scanner (``catalog.discovery``) and the validate CLI (``schema.loader``)
# so both agree on which files under Reconstructions/ count as an entity. A stray
# ``notes.txt`` next to the reconstructions is ignored by both.
TOMOGRAM_FILE_EXTENSIONS = frozenset({".mrc"})
ANNOTATION_FILE_EXTENSIONS = frozenset(
    {".star", ".mrc", ".png", ".tiff", ".tif", ".csv", ".json"}
)

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


def is_zarr_dir(path: Path) -> bool:
    """True if ``path`` is a Zarr store dir (``.zarr`` / ``.ome.zarr``)."""
    return any(path.name.endswith(suffix) for suffix in ZARR_DIR_SUFFIXES)


def entity_ids_in_dir(directory: Path, file_extensions: frozenset[str]) -> set[str]:
    """Return entity ids (file stems) directly under ``directory``.

    A child counts when it is a file whose suffix is in ``file_extensions``
    (case-insensitive) or a ``.zarr`` / ``.ome.zarr`` store dir; everything else
    (stray ``notes.txt`` / ``.gitkeep``) is ignored. Mirrors the per-leaf
    grouping in ``catalog.discovery`` so the loader and scanner agree on which
    files map to an entity id. A missing ``directory`` yields the empty set.
    """
    ids: set[str] = set()
    if not directory.is_dir():
        return ids
    for entry in directory.iterdir():
        if entry.is_file() and entry.suffix.lower() in file_extensions:
            ids.add(entity_id_from_path(entry))
        elif entry.is_dir() and is_zarr_dir(entry):
            ids.add(entity_id_from_path(entry))
    return ids


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


def sample_id_for(sample_dir: Path) -> str:
    """Return the catalog ``sample_id`` for a sample directory.

    Simulation samples are namespaced by their dataset-type subdir
    (e.g. ``Slab_12mer_26_0.080``) because the bare folder name is NOT unique
    across ``MdSimulation/{Bulk,SingleMolecule,Slab}`` — two runs with the same
    trajectory name under different subdirs would otherwise collide on one id.
    Experimental samples keep the bare folder name. The simulation prefix
    deliberately matches the OVITO preview-cache filename prefix
    (``{SubDir}_{name}``), so preview lookups resolve off the id directly.
    """
    data_source, _ = infer_arm(sample_dir)
    if data_source is DataSource.simulation:
        return f"{sample_dir.parent.name}_{sample_dir.name}"
    return sample_dir.name


__all__ = [
    "ANNOTATION_FILE_EXTENSIONS",
    "DATASET_TYPE_BY_DIR",
    "TOMOGRAM_FILE_EXTENSIONS",
    "TOP_LEVEL_EXPERIMENTAL",
    "TOP_LEVEL_MD_SIMULATION",
    "ZARR_DIR_SUFFIXES",
    "entity_id_from_path",
    "entity_ids_in_dir",
    "infer_arm",
    "is_zarr_dir",
    "sample_id_for",
]


if __name__ == "__main__":
    import tempfile

    # ponytail: minimal self-check for the stem rule — the one non-trivial bit.
    assert entity_id_from_path(Path("foo.mrc")) == "foo"
    assert entity_id_from_path(Path("foo.zarr")) == "foo"
    assert entity_id_from_path(Path("foo.ome.zarr")) == "foo"
    # .mrc and .ome.zarr for the same tomogram must collapse to one id.
    assert entity_id_from_path(Path("a/b/foo.ome.zarr")) == entity_id_from_path(
        Path("a/b/foo.mrc")
    )
    assert entity_id_from_path(Path("no_ext")) == "no_ext"

    # entity_ids_in_dir: allowlist + zarr grouping, stray files ignored.
    with tempfile.TemporaryDirectory() as d:
        leaf = Path(d)
        (leaf / "a.mrc").touch()
        (leaf / "a.ome.zarr").mkdir()  # same stem -> one id
        (leaf / "b.zarr").mkdir()
        (leaf / "notes.txt").touch()  # ignored
        assert entity_ids_in_dir(leaf, TOMOGRAM_FILE_EXTENSIONS) == {"a", "b"}
    assert entity_ids_in_dir(Path(d), TOMOGRAM_FILE_EXTENSIONS) == set()  # gone
    print("schema.layout self-check OK")
