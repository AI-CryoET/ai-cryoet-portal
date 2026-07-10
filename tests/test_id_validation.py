"""Tests for IdStr / _validate_id (folder-name & id restrictions)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from schema import PostProcessedTomogram, Sample
from schema.schema import AcquisitionFile, _validate_id
from schema.loader import load_sample_record


# ── direct unit tests of _validate_id ────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "Position_86",
        "bp_3dctf_bin4",
        "membrain_seg_v10",
        "gouauxlab_20241211_HippWaffle",
        "a",
        "A1",
        "x.y",
        "foo-bar_baz.v2",
        "a" * 128,
    ],
)
def test_valid_ids(value):
    assert _validate_id(value) == value


@pytest.mark.parametrize(
    "value,reason",
    [
        ("", "empty"),
        ("a" * 129, "too long"),
        # leading characters
        (".hidden", "leading dot"),
        ("-flag", "leading hyphen"),
        ("_underscore", "leading underscore"),
        # trailing characters
        ("trailing.", "trailing dot"),
        ("trailing-", "trailing hyphen"),
        # path / traversal
        ("foo/bar", "forward slash"),
        ("foo\\bar", "backslash"),
        ("..", "double dot"),
        ("foo..bar", "embedded double dot"),
        # whitespace
        ("has space", "space"),
        ("tab\there", "tab"),
        ("new\nline", "newline"),
        # shell metacharacters
        ("star*", "asterisk"),
        ("question?", "question mark"),
        ("bracket[", "bracket"),
        ("brace{", "brace"),
        ("tilde~", "tilde"),
        ("dollar$", "dollar"),
        ("back`tick", "backtick"),
        ("bang!", "exclamation"),
        ("pipe|", "pipe"),
        ("amp&", "ampersand"),
        ("semi;", "semicolon"),
        ("lt<", "less-than"),
        ("gt>", "greater-than"),
        ("paren(", "paren"),
        ("double\"quote", "double quote"),
        ("single'quote", "single quote"),
        # URL-reserved
        ("percent%", "percent"),
        ("hash#", "hash"),
        ("query?x", "question mark"),
        ("plus+1", "plus"),
        ("at@sym", "at sign"),
        ("colon:x", "colon"),
        ("eq=val", "equals"),
        # control characters
        ("ctrl\x00char", "null byte"),
        ("ctrl\x1fchar", "control char"),
        ("del\x7fchar", "DEL"),
        # non-ASCII
        ("café", "non-ASCII letter"),
        ("naïve", "diaeresis"),
        ("zero​width", "zero-width space"),
        # comma, not in allowlist
        ("a,b", "comma"),
    ],
)
def test_invalid_ids(value, reason):
    with pytest.raises(ValueError):
        _validate_id(value)


@pytest.mark.parametrize(
    "value",
    ["CON", "con", "PRN", "aux", "NUL", "COM1", "com9", "LPT1", "lpt9"],
)
def test_windows_reserved_names_rejected(value):
    with pytest.raises(ValueError, match="reserved"):
        _validate_id(value)


def test_non_string_rejected():
    with pytest.raises(ValueError):
        _validate_id(123)  # type: ignore[arg-type]


# ── integration through Pydantic models ──────────────────────────────────────


def test_sample_accepts_valid_sample_id():
    s = Sample(sample_id="good_sample_01", data_source="experimental", project="chromatin")
    assert s.sample_id == "good_sample_01"


def test_sample_rejects_bad_sample_id():
    with pytest.raises(ValidationError):
        Sample(sample_id="bad name", data_source="experimental", project="chromatin")


def test_sample_allows_none_sample_id():
    s = Sample(data_source="experimental", project="chromatin")
    assert s.sample_id is None


def test_tomogram_rejects_bad_id_alias():
    with pytest.raises(ValidationError):
        PostProcessedTomogram.model_validate({"id": "has space"})


def test_tomogram_rejects_bad_derived_from():
    with pytest.raises(ValidationError):
        PostProcessedTomogram.model_validate({"id": "tomo_001", "derived_from": ["also/bad"]})


def test_tomogram_tilt_series_id_must_match_declared_tilt_series():
    """A tomogram's tilt_series_id must reference a [[tilt_series]] in the same acquisition."""
    with pytest.raises(ValidationError, match="does not match any"):
        AcquisitionFile.model_validate(
            {
                "acquisition": {},
                "raw_tomogram": {"id": "tomo_001", "tilt_series_id": "ghost"},
                "tilt_series": [{"id": "ts_raw"}],
            }
        )


def test_tomogram_tilt_series_id_resolves_to_declared_tilt_series():
    """A tomogram referencing a declared tilt series validates; the id round-trips."""
    acq = AcquisitionFile.model_validate(
        {
            "acquisition": {},
            "raw_tomogram": {"id": "tomo_001", "tilt_series_id": "ts_raw"},
            "post_processed_tomogram": [
                {"id": "tomo_002", "tilt_series_id": "ts_raw"}
            ],
            "tilt_series": [{"id": "ts_raw"}],
        }
    )
    assert acq.raw_tomogram.tilt_series_id == "ts_raw"
    assert acq.post_processed_tomogram[0].tilt_series_id == "ts_raw"


def test_tomogram_tilt_series_id_optional():
    """tilt_series_id is optional — a tomogram without one still validates."""
    acq = AcquisitionFile.model_validate(
        {"acquisition": {}, "raw_tomogram": {"id": "tomo_001"}}
    )
    assert acq.raw_tomogram.tilt_series_id is None


def test_tilt_series_derived_from_frames_sentinel():
    """derived_from accepts the literal "Frames" sentinel."""
    acq = AcquisitionFile.model_validate(
        {"acquisition": {}, "tilt_series": [{"id": "ts_raw", "derived_from": "Frames"}]}
    )
    assert acq.tilt_series[0].derived_from == "Frames"


def test_tilt_series_derived_from_must_match_known_id():
    """derived_from that is neither "Frames" nor a tilt_series id in this acquisition fails."""
    with pytest.raises(ValidationError, match="neither"):
        AcquisitionFile.model_validate(
            {
                "acquisition": {},
                "tilt_series": [{"id": "ts_aligned", "derived_from": "ghost"}],
            }
        )


# ── integration through load_sample_record ──────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip())


def test_bad_sample_folder_name(tmp_path):
    """Bad sample_id (from folder name) is a sample-level failure: record=None."""
    bad = tmp_path / "bad name"
    _write(
        bad / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    result = load_sample_record(bad)
    assert result.record is None
    assert any("sample_id" in e for e in result.sample_errors)


def test_bad_acquisition_folder_name(tmp_path):
    """Bad acquisition_id is a per-acquisition failure under the new isolation rules."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    _write(tmp_path / "Position*86" / "acquisition.toml", "[acquisition]\n")
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "Position*86" in result.acquisition_errors
    assert "acquisition_id" in result.acquisition_errors["Position*86"]
    assert "Position*86" not in result.record.acquisitions


def test_acquisition_case_insensitive_collision(tmp_path):
    """Cross-acquisition collision is detected at SampleRecord level → sample_errors."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    _write(tmp_path / "Position_86" / "acquisition.toml", "[acquisition]\n")
    _write(tmp_path / "position_86" / "acquisition.toml", "[acquisition]\n")
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any(
        "collides case-insensitively" in e and "acquisition" in e
        for e in result.sample_errors
    )


def test_tomogram_case_insensitive_collision(tmp_path):
    """Within-acquisition collision is per-acquisition under the new isolation rules."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[post_processed_tomogram]]
        id = "tomo_001"

        [[post_processed_tomogram]]
        id = "Tomo_001"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" in result.acquisition_errors
    msg = result.acquisition_errors["acq1"]
    assert "collides case-insensitively" in msg and "tomogram id" in msg
    assert "acq1" not in result.record.acquisitions


def test_annotation_case_insensitive_collision(tmp_path):
    """Within-acquisition annotation-id collision → acquisition_errors."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[post_processed_tomogram]]
        id = "tomo_001"

        [[annotation]]
        id = "ann_001"

        [[annotation]]
        id = "ANN_001"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" in result.acquisition_errors
    msg = result.acquisition_errors["acq1"]
    assert "collides case-insensitively" in msg and "annotation" in msg
    assert "acq1" not in result.record.acquisitions


def test_tomogram_and_annotation_sharing_id_is_allowed(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[post_processed_tomogram]]
        id = "shared_id"

        [[annotation]]
        id = "shared_id"
        """,
    )
    recon = tmp_path / "acq1" / "Reconstructions" / "ts_a"
    (recon / "Tomograms").mkdir(parents=True)
    (recon / "Tomograms" / "shared_id.mrc").touch()
    (recon / "Annotations").mkdir(parents=True)
    (recon / "Annotations" / "shared_id.json").touch()
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    assert result.record is not None


def test_bad_tomogram_id_in_toml(tmp_path):
    """Bad post_processed_tomogram id is a per-acquisition failure under the new isolation rules."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[post_processed_tomogram]]
        id = "has space"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" in result.acquisition_errors
    msg = result.acquisition_errors["acq1"]
    assert "post_processed_tomogram" in msg.lower() and "id" in msg.lower()
    assert "acq1" not in result.record.acquisitions
