"""Tests for per-acquisition isolation and <FILL IN> placeholder stripping."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from schema.loader import load_sample_record


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip())


def _minimal_sample(root: Path) -> None:
    _write(
        root / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )


def test_one_bad_acquisition_does_not_block_the_rest(tmp_path):
    _minimal_sample(tmp_path)
    # acq_a is a clean, valid acquisition.
    _write(
        tmp_path / "acq_a" / "acquisition.toml",
        """
        [acquisition]
        resolution = 3.5
        """,
    )
    # acq_b has a dangling post_processed_tomogram.derived_from, so it fails
    # validation.
    _write(
        tmp_path / "acq_b" / "acquisition.toml",
        """
        [acquisition]

        [[post_processed_tomogram]]
        id = "tomo_001"
        derived_from = ["ghost"]
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq_a" in result.record.acquisitions
    assert "acq_b" not in result.record.acquisitions
    assert "acq_b" in result.acquisition_errors
    assert "ghost" in result.acquisition_errors["acq_b"]


def test_bad_sample_toml_still_returns_record_none(tmp_path):
    """Regression: an unrecoverable sample.toml continues to produce record=None."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("project" in e for e in result.sample_errors)


def test_unparseable_acquisition_toml_lands_in_acquisition_errors(tmp_path):
    _minimal_sample(tmp_path)
    (tmp_path / "acq1").mkdir()
    (tmp_path / "acq1" / "acquisition.toml").write_text("not = = valid\n")
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" in result.acquisition_errors
    assert "TOML parse error" in result.acquisition_errors["acq1"]


def test_fill_in_placeholder_in_sample_toml_warns_and_nones_field(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        description = "<FILL IN>"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert result.record.sample.description is None
    assert any(
        "unfilled <FILL IN> placeholder" in w and "description" in w
        for w in result.warnings
    )


def test_loader_reads_reconstruction_toml(tmp_path):
    """A Reconstructions/{id}/reconstruction.toml is parsed and populates
    SampleRecord.reconstructions[acq_id][group_id]."""
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]
        """,
    )
    recon = tmp_path / "acq1" / "Reconstructions" / "grpA"
    (recon / "Tomograms").mkdir(parents=True)
    (recon / "Tomograms" / "ctf.mrc").write_bytes(b"")
    _write(
        recon / "reconstruction.toml",
        """
        [reconstruction_alignment]
        alignment_software = "AreTomo3"

        [[raw_tomogram]]
        id = "ctf"
        pipeline = "bp"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    rf = result.record.reconstructions["acq1"]["grpA"]
    assert rf.reconstruction_alignment.reconstruction_alignment_id == "grpA"
    assert rf.raw_tomogram[0].tomogram_id == "ctf"


def test_bad_acquisition_reconstruction_is_not_recorded(tmp_path):
    """Invariant: reconstructions keys must be a subset of acquisitions keys.
    A Reconstructions/{id}/reconstruction.toml under an acquisition whose
    acquisition.toml fails validation must not leak into
    result.record.reconstructions.
    """
    _minimal_sample(tmp_path)
    # acq_b fails validation (dangling derived_from), same as the isolation test.
    _write(
        tmp_path / "acq_b" / "acquisition.toml",
        """
        [acquisition]

        [[post_processed_tomogram]]
        id = "tomo_001"
        derived_from = ["ghost"]
        """,
    )
    recon = tmp_path / "acq_b" / "Reconstructions" / "grpA"
    (recon / "Tomograms").mkdir(parents=True)
    (recon / "Tomograms" / "ctf.mrc").write_bytes(b"")
    _write(
        recon / "reconstruction.toml",
        """
        [reconstruction_alignment]
        alignment_software = "AreTomo3"

        [[raw_tomogram]]
        id = "ctf"
        pipeline = "bp"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq_b" not in result.record.acquisitions
    assert "acq_b" not in result.record.reconstructions
    assert set(result.record.reconstructions) <= set(result.record.acquisitions)


def test_fill_in_placeholder_in_numeric_field_strips_to_none(tmp_path):
    """A <FILL IN> in a numeric field would otherwise fail type coercion;
    the loader strips it to None *before* validation runs.
    """
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]
        pixel_size = "<FILL IN>"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" in result.record.acquisitions
    assert result.record.acquisitions["acq1"].acquisition.pixel_size is None
    assert any(
        "unfilled <FILL IN> placeholder" in w and "pixel_size" in w
        for w in result.warnings
    )
