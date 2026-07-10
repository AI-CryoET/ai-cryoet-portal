"""Drift guards tying the hand-edited artifacts back to schema.py.

These tests fail loudly (with a fix hint) whenever a change to schema.py or
a template is not mirrored into the doc / starter-copy / README. They are the
safety net for the "edit schema.py -> sync -> test" maintenance loop.
"""

from __future__ import annotations

import enum
import typing
from pathlib import Path

from schema import (
    Acquisition,
    Annotation,
    Label,
    Fiducial,
    Chromatin,
    DataSource,
    Freezing,
    MdRun,
    MdSource,
    Milling,
    PostProcessedTomogram,
    Project,
    RawTomogram,
    Sample,
    Simulation,
    TiltSeries,
)
from schema.schema import DatasetType, LabName
from schema.sync_templates import TEMPLATE_PAIRS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_INFO = _REPO_ROOT / "docs" / "schema.md"
_README = _REPO_ROOT / "README.md"

# Leaf entity models whose fields map 1:1 to documented table rows. The
# container models (SampleRecord, AcquisitionFile) are excluded: their field
# names are TOML table names, not documented columns.
_ENTITY_MODELS = [
    Sample,
    Simulation,
    Chromatin,
    Label,
    Fiducial,
    Freezing,
    Milling,
    MdRun,
    Acquisition,
    TiltSeries,
    MdSource,
    RawTomogram,
    PostProcessedTomogram,
    Annotation,
]


def test_starter_templates_in_sync():
    """Each starter-directory copy must equal its canonical template."""
    for canonical, copy in TEMPLATE_PAIRS:
        assert copy.is_file(), f"missing starter copy {copy}"
        assert copy.read_text() == canonical.read_text(), (
            f"{copy.relative_to(_REPO_ROOT)} differs from "
            f"{canonical.relative_to(_REPO_ROOT)}. "
            "Run `pixi run sync-templates` to regenerate."
        )


# The empty-directory layout each starter skeleton ships, relative to its
# sample root. This is the only thing that distinguishes the experimental and
# simulation skeletons (their TOML contents are identical) and mirrors the two
# layouts documented under "Proposed directory structure" in README.md.
_SKELETON_DIRS = {
    "sample_id_experimental": {
        "acquisition_id/Frames",
        "acquisition_id/Gains",
        "acquisition_id/TiltSeries/tilt_series_id/stack",
        "acquisition_id/TiltSeries/tilt_series_id/alignment",
        "acquisition_id/Reconstructions/tilt_series_id/Tomograms",
        "acquisition_id/Reconstructions/tilt_series_id/Annotations",
    },
    "sample_id_simulation": {
        "MdRuns/md_run_id/Trajectories",
        "MdRuns/md_run_id/Snapshots",
        "SyntheticCryoET/acquisition_id/TiltSeries/tilt_series_id/stack",
        "SyntheticCryoET/acquisition_id/TiltSeries/tilt_series_id/alignment",
        "SyntheticCryoET/acquisition_id/Reconstructions/Tomograms",
        "SyntheticCryoET/acquisition_id/Reconstructions/Annotations",
    },
}


def test_starter_skeletons_match_documented_layout():
    """Each starter skeleton must ship exactly the empty directories the
    README documents for its data arm — no missing, extra, or drifted folders.

    Guards the experimental/simulation split: simulation drops the movie-frame
    folders (``Frames``/``Gains``), adds ``MdRuns/``, and wraps
    acquisitions in ``SyntheticCryoET/``.
    """
    templates = _REPO_ROOT / "templates"
    for skeleton, expected in _SKELETON_DIRS.items():
        root = templates / skeleton
        assert root.is_dir(), f"missing starter skeleton {root}"
        # Leaf directories only: a directory with no subdirectories. Comparing
        # leaves keeps the assertion stable against the intermediate dirs
        # (e.g. Reconstructions/) that are implied by their children.
        leaves = {
            str(p.relative_to(root).as_posix())
            for p in root.rglob("*")
            if p.is_dir() and not any(c.is_dir() for c in p.iterdir())
        }
        assert leaves == expected, (
            f"{skeleton}/ directory layout drifted from README. "
            f"Missing: {sorted(expected - leaves)}; "
            f"unexpected: {sorted(leaves - expected)}."
        )


def test_schema_info_documents_every_field():
    """Every field on every entity model must appear in docs/schema.md."""
    doc = _SCHEMA_INFO.read_text()
    missing: list[str] = []
    for model in _ENTITY_MODELS:
        for field_name in model.model_fields:
            if f"`{field_name}`" not in doc:
                missing.append(f"{model.__name__}.{field_name}")
    assert not missing, (
        "fields present in schema.py but undocumented in docs/schema.md: "
        + ", ".join(missing)
    )


def _enum_types_in(annotation) -> set[type]:
    found: set[type] = set()
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        found.add(annotation)
    for arg in typing.get_args(annotation):
        found |= _enum_types_in(arg)
    return found


def test_readme_enums_claim_holds():
    """Guards the documented set of schema enums.

    `data_source`, `project`, and `lab_name` are researcher-authored enums;
    `dataset_type` is a scanner-derived enum (from the `MdSimulation/<SubDir>/`
    directory). `docs/data_organization.md` describes the authored enums — if
    this set drifts, update that doc.
    """
    enums: set[type] = set()
    for model in _ENTITY_MODELS:
        for field in model.model_fields.values():
            enums |= _enum_types_in(field.annotation)
    assert enums == {DataSource, DatasetType, LabName, Project}, (
        "the set of enum types changed; docs/data_organization.md describes "
        "data_source/project/lab_name (authored) and dataset_type (derived) as "
        "the schema enums. Update the docs. "
        f"Found: {sorted(e.__name__ for e in enums)}"
    )


def test_readme_required_fields_claim_holds():
    """Docs state `project` is the only required authored sample field.

    `data_source` is directory-derived (Optional on the model, injected from
    the top-level arm), so it is no longer a required authored field.
    """
    required = {n for n, f in Sample.model_fields.items() if f.is_required()}
    assert required == {"project"}, (
        "Sample's required fields changed; docs/data_organization.md claims "
        "only `project` is a required authored field (`data_source` is "
        "directory-derived). Update the docs. "
        f"Found: {sorted(required)}"
    )
