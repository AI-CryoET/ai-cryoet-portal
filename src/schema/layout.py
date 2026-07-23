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

DATASET_TYPE_BY_DIR: dict[str, DatasetType] = {
    "Bulk": DatasetType.bulk,
    "SingleMolecule": DatasetType.single_molecule,
    "Slab": DatasetType.slab,
}


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
    "DATASET_TYPE_BY_DIR",
    "TOP_LEVEL_EXPERIMENTAL",
    "TOP_LEVEL_MD_SIMULATION",
    "infer_arm",
    "sample_id_for",
]
