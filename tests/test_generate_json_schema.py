"""Tests for schema.generate_json_schema and the committed schemas."""

from __future__ import annotations

import json
from pathlib import Path

from schema import AcquisitionFile, MdRun, ReconstructionFile, SampleRecord
from schema.generate_json_schema import (
    _ACQUISITION_FILENAME,
    _DEFAULT_OUT,
    _MD_RUN_FILENAME,
    _RECONSTRUCTION_FILENAME,
    main,
    strip_nullable,
)


def test_writes_valid_json_schema_to_given_path(tmp_path, capsys):
    out = tmp_path / "schema.json"
    rc = main([str(out)])
    assert rc == 0
    assert out.is_file()
    loaded = json.loads(out.read_text())
    assert loaded == strip_nullable(SampleRecord.model_json_schema())
    captured = capsys.readouterr().out
    assert "wrote" in captured


def test_writes_acquisition_schema_alongside(tmp_path):
    out = tmp_path / "schema.json"
    rc = main([str(out)])
    assert rc == 0
    acquisition_out = tmp_path / _ACQUISITION_FILENAME
    assert acquisition_out.is_file()
    assert json.loads(acquisition_out.read_text()) == strip_nullable(
        AcquisitionFile.model_json_schema()
    )


def test_writes_md_run_schema_alongside(tmp_path):
    out = tmp_path / "schema.json"
    rc = main([str(out)])
    assert rc == 0
    md_run_out = tmp_path / _MD_RUN_FILENAME
    assert md_run_out.is_file()
    assert json.loads(md_run_out.read_text()) == strip_nullable(
        MdRun.model_json_schema()
    )


def test_md_run_schema_uses_folder_name_id(tmp_path):
    """md_run.toml's `id` comes from the folder name and is the only required
    field (the alias of `md_run_id`); the metadata fields are optional."""
    out = tmp_path / "schema.json"
    main([str(out)])
    schema = json.loads((tmp_path / _MD_RUN_FILENAME).read_text())
    assert schema["required"] == ["id"]
    for field in (
        "seed",
        "sample_time",
        "timestep",
        "computer",
        "reference_contact",
        "force_field_version",
    ):
        assert field in schema["properties"], field


def test_dataset_type_enum_in_sample_schema(tmp_path):
    """The DatasetType enum's snake_case members appear in the SampleRecord
    schema (dataset_type is now a strict enum)."""
    out = tmp_path / "schema.json"
    main([str(out)])
    schema = json.loads(out.read_text())
    dataset_type = schema["$defs"]["DatasetType"]
    assert set(dataset_type["enum"]) == {
        "bulk",
        "single_molecule",
        "slab",
    }


def test_acquisition_quality_range_in_acquisition_schema(tmp_path):
    """acquisition_quality is a constrained int 1-5 in the schema."""
    out = tmp_path / "schema.json"
    main([str(out)])
    schema = json.loads((tmp_path / _ACQUISITION_FILENAME).read_text())
    score = schema["$defs"]["Acquisition"]["properties"]["acquisition_quality"]
    assert score["minimum"] == 1
    assert score["maximum"] == 5
    assert score["type"] == "integer"


def test_creates_parent_directories(tmp_path):
    out = tmp_path / "nested" / "dir" / "schema.json"
    rc = main([str(out)])
    assert rc == 0
    assert out.is_file()
    json.loads(out.read_text())


def test_strip_nullable_collapses_optional_scalar():
    schema = {
        "anyOf": [{"type": "integer"}, {"type": "null"}],
        "default": None,
        "title": "Nucleosome Count",
    }
    assert strip_nullable(schema) == {
        "type": "integer",
        "title": "Nucleosome Count",
    }


def test_strip_nullable_preserves_multi_branch_anyof():
    schema = {
        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
        "default": None,
    }
    assert strip_nullable(schema) == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }


def test_committed_schema_matches_pydantic_models():
    """Guard against drift between schema/schema.json and SampleRecord.

    Regenerate with: `pixi run json-schema`.
    """
    committed = json.loads(Path(_DEFAULT_OUT).read_text())
    expected = strip_nullable(SampleRecord.model_json_schema())
    assert committed == expected, (
        "schema/schema.json is out of sync with SampleRecord. "
        "Run `pixi run json-schema` to regenerate."
    )


def test_committed_acquisition_schema_matches_pydantic_models():
    """Guard against drift between acquisition.schema.json and AcquisitionFile.

    Regenerate with: `pixi run json-schema`.
    """
    committed_path = Path(_DEFAULT_OUT).parent / _ACQUISITION_FILENAME
    committed = json.loads(committed_path.read_text())
    expected = strip_nullable(AcquisitionFile.model_json_schema())
    assert committed == expected, (
        "schema/acquisition.schema.json is out of sync with AcquisitionFile. "
        "Run `pixi run json-schema` to regenerate."
    )


def test_committed_md_run_schema_matches_pydantic_models():
    """Guard against drift between md_run.schema.json and MdRun.

    Regenerate with: `pixi run json-schema`.
    """
    committed_path = Path(_DEFAULT_OUT).parent / _MD_RUN_FILENAME
    committed = json.loads(committed_path.read_text())
    expected = strip_nullable(MdRun.model_json_schema())
    assert committed == expected, (
        "schema/md_run.schema.json is out of sync with MdRun. "
        "Run `pixi run json-schema` to regenerate."
    )


def test_writes_reconstruction_schema_alongside(tmp_path):
    out = tmp_path / "schema.json"
    rc = main([str(out)])
    assert rc == 0
    reconstruction_out = tmp_path / _RECONSTRUCTION_FILENAME
    assert reconstruction_out.is_file()
    assert json.loads(reconstruction_out.read_text()) == strip_nullable(
        ReconstructionFile.model_json_schema()
    )


def test_reconstruction_schema_has_no_required_fields(tmp_path):
    """Every section of reconstruction.toml is optional — the folder name
    supplies the group's identity, so an empty file is valid."""
    out = tmp_path / "schema.json"
    main([str(out)])
    schema = json.loads((tmp_path / _RECONSTRUCTION_FILENAME).read_text())
    assert "required" not in schema
    for section in (
        "reconstruction_alignment",
        "raw_tomogram",
        "post_processed_tomogram",
        "annotation",
    ):
        assert section in schema["properties"], section


def test_committed_reconstruction_schema_matches_pydantic_models():
    """Guard against drift between reconstruction.schema.json and
    ReconstructionFile.

    Regenerate with: `pixi run json-schema`.
    """
    committed_path = Path(_DEFAULT_OUT).parent / _RECONSTRUCTION_FILENAME
    committed = json.loads(committed_path.read_text())
    expected = strip_nullable(ReconstructionFile.model_json_schema())
    assert committed == expected, (
        "schema/reconstruction.schema.json is out of sync with "
        "ReconstructionFile. Run `pixi run json-schema` to regenerate."
    )
