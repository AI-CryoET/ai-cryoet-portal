"""Unit tests for ``catalog.parsers.*``.

Each test writes its own per-test fixtures inline using ``tmp_path`` rather
than depending on the shared ``tests/catalog/fixtures/`` tree (which
is being authored in parallel by another agent).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalog.parsers import ParseResult
from catalog.parsers.frame_ext import infer_camera
from catalog.parsers.mdoc import parse_acquisition_mdocs
from catalog.parsers.mrc_header import read_mrc_header
from catalog.parsers.ome_zarr import read_zarr_attrs
from catalog.parsers.toml_files import LoadResult, load_sample_toml


# ── toml_files ──────────────────────────────────────────────────────────────


def _write_minimal_sample_toml(sample_dir: Path) -> None:
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / "sample.toml").write_text(
        """\
[sample]
data_source = "experimental"
project = "synapse"
"""
    )


def test_toml_files_delegates(tmp_path: Path) -> None:
    sample_dir = tmp_path / "my_sample"
    _write_minimal_sample_toml(sample_dir)

    result = load_sample_toml(sample_dir)

    assert isinstance(result, LoadResult)
    assert result.record is not None
    assert result.record.sample.data_source.value == "experimental"
    assert result.record.sample.project.value == "synapse"
    # sample_id is injected from the directory name.
    assert result.record.sample.sample_id == "my_sample"


# ── mdoc ────────────────────────────────────────────────────────────────────


_TYPICAL_MDOC = """\
PixelSpacing = 2.93
Voltage = 300
TiltAxisAngle = 84.5

[ZValue = 0]
TiltAngle = -60.0
ExposureDose = 0.5
DateTime = 24-Aug-25  10:00:00

[ZValue = 1]
TiltAngle = -57.0
ExposureDose = 0.5
DateTime = 24-Aug-25  10:01:00
"""


def test_parse_acquisition_mdocs_typical(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "ts.mrc.mdoc").write_text(_TYPICAL_MDOC)

    result = parse_acquisition_mdocs(frames_dir)

    assert result.status == "ok"
    f = result.fields
    assert f["pixel_size"] == pytest.approx(2.93)
    assert f["voltage"] == pytest.approx(300.0)
    assert f["frame_count"] == 2
    assert len(f["dose_per_tilt"]) == 2
    assert f["dose_per_tilt"] == [pytest.approx(0.5), pytest.approx(0.5)]
    assert f["total_dose"] == pytest.approx(1.0)
    assert f["tilt_min"] == pytest.approx(-60.0)
    assert f["tilt_max"] == pytest.approx(-57.0)
    assert f["tilt_axis"] == pytest.approx(84.5)
    # Full per-image tilt angle list — preserved in order so the
    # polar-plot endpoint can render without re-parsing.
    assert f["tilt_angles"] == [pytest.approx(-60.0), pytest.approx(-57.0)]
    # DateTime parsing should produce a date.
    import datetime as _dt

    assert f["date_collected"] == _dt.date(2025, 8, 24)


def test_parse_acquisition_mdocs_picks_first_alphabetically(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    # Two mdocs; the lexicographically-first one should win.
    (frames_dir / "b_second.mdoc").write_text(
        "PixelSpacing = 9.99\n[ZValue = 0]\nTiltAngle = 0.0\nExposureDose = 0.1\n"
    )
    (frames_dir / "a_first.mdoc").write_text(
        "PixelSpacing = 1.11\n[ZValue = 0]\nTiltAngle = 0.0\nExposureDose = 0.1\n"
    )

    result = parse_acquisition_mdocs(frames_dir)

    assert result.status == "ok"
    assert result.fields["pixel_size"] == pytest.approx(1.11)


def test_parse_acquisition_mdocs_missing_dir(tmp_path: Path) -> None:
    result = parse_acquisition_mdocs(tmp_path / "nope")
    assert result.status == "missing"


def test_parse_acquisition_mdocs_no_mdocs_in_dir(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "001.eer").write_text("not a mdoc")
    result = parse_acquisition_mdocs(frames_dir)
    assert result.status == "missing"


def test_parse_acquisition_mdocs_malformed_value(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "ts.mdoc").write_text(
        "Voltage = not_a_number\n[ZValue = 0]\nTiltAngle = 0.0\n"
    )
    result = parse_acquisition_mdocs(frames_dir)
    assert result.status == "unreadable"
    assert result.error is not None


def test_parse_acquisition_mdocs_one_space_datetime(tmp_path: Path) -> None:
    """Single-space DateTime should still parse via the fallback format."""
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "ts.mdoc").write_text(
        "PixelSpacing = 2.0\n"
        "[ZValue = 0]\n"
        "TiltAngle = 0.0\n"
        "ExposureDose = 0.1\n"
        "DateTime = 24-Aug-25 10:00:00\n"
    )
    result = parse_acquisition_mdocs(frames_dir)
    assert result.status == "ok"
    import datetime as _dt

    assert result.fields["date_collected"] == _dt.date(2025, 8, 24)


def test_parse_acquisition_mdocs_four_digit_year_datetime(tmp_path: Path) -> None:
    """4-digit-year DateTime (newer SerialEM installs) should still parse."""
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "ts.mdoc").write_text(
        "PixelSpacing = 2.0\n"
        "[ZValue = 0]\n"
        "TiltAngle = 0.0\n"
        "ExposureDose = 0.1\n"
        "DateTime = 27-Jan-2026  19:14:10\n"
    )
    result = parse_acquisition_mdocs(frames_dir)
    assert result.status == "ok"
    import datetime as _dt

    assert result.fields["date_collected"] == _dt.date(2026, 1, 27)


def test_parse_acquisition_mdocs_unparseable_datetime_does_not_fail(
    tmp_path: Path,
) -> None:
    """Unparseable DateTime returns date_collected=None but status=ok."""
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "ts.mdoc").write_text(
        "[ZValue = 0]\n"
        "TiltAngle = 0.0\n"
        "ExposureDose = 0.1\n"
        "DateTime = nonsense-format\n"
    )
    result = parse_acquisition_mdocs(frames_dir)
    assert result.status == "ok"
    assert result.fields["date_collected"] is None


# ── mrc_header ──────────────────────────────────────────────────────────────


def test_read_mrc_header_typical(tmp_path: Path) -> None:
    mrcfile = pytest.importorskip("mrcfile")
    np = pytest.importorskip("numpy")

    mrc_path = tmp_path / "tomo.mrc"
    # mrcfile shape is (z, y, x); a (4, 5, 6) array yields nx=6, ny=5, nz=4.
    data = np.zeros((4, 5, 6), dtype=np.float32)
    with mrcfile.new(str(mrc_path), overwrite=True) as m:
        m.set_data(data)
        m.voxel_size = 11.7197

    result = read_mrc_header(mrc_path)
    assert result.status == "ok"
    f = result.fields
    assert f["image_size_x"] == 6
    assert f["image_size_y"] == 5
    assert f["image_size_z"] == 4
    assert f["voxel_spacing_angstrom"] == pytest.approx(11.7197, rel=1e-4)


def test_read_mrc_header_missing(tmp_path: Path) -> None:
    result = read_mrc_header(tmp_path / "nope.mrc")
    assert result.status == "missing"


def test_read_mrc_header_unreadable(tmp_path: Path) -> None:
    pytest.importorskip("mrcfile")
    # An MRC header is 1024 bytes; a too-short file forces mrcfile to raise
    # even under ``permissive=True``.
    bogus = tmp_path / "bogus.mrc"
    bogus.write_bytes(b"\x00" * 32)
    result = read_mrc_header(bogus)
    assert result.status == "unreadable"
    assert result.error is not None


# ── ome_zarr ────────────────────────────────────────────────────────────────


_TYPICAL_ZATTRS = {
    "multiscales": [
        {
            "axes": [
                {"name": "z", "type": "space", "unit": "angstrom"},
                {"name": "y", "type": "space", "unit": "angstrom"},
                {"name": "x", "type": "space", "unit": "angstrom"},
            ],
            "datasets": [
                {
                    "path": "0",
                    "coordinateTransformations": [
                        {"type": "scale", "scale": [11.72, 11.72, 11.72]}
                    ],
                }
            ],
        }
    ]
}


def test_read_zarr_attrs_typical(tmp_path: Path) -> None:
    zarr_path = tmp_path / "tomo.zarr"
    zarr_path.mkdir()
    (zarr_path / ".zattrs").write_text(json.dumps(_TYPICAL_ZATTRS))

    result = read_zarr_attrs(zarr_path)
    assert result.status == "ok"
    assert result.fields["zarr_axes"] == "zyx"
    assert result.fields["zarr_scale"] == [
        pytest.approx(11.72),
        pytest.approx(11.72),
        pytest.approx(11.72),
    ]


def test_read_zarr_attrs_missing_dir(tmp_path: Path) -> None:
    result = read_zarr_attrs(tmp_path / "nope.zarr")
    assert result.status == "missing"


def test_read_zarr_attrs_dir_without_zattrs(tmp_path: Path) -> None:
    zarr_path = tmp_path / "tomo.zarr"
    zarr_path.mkdir()
    result = read_zarr_attrs(zarr_path)
    assert result.status == "missing"


def test_read_zarr_attrs_malformed_json(tmp_path: Path) -> None:
    zarr_path = tmp_path / "tomo.zarr"
    zarr_path.mkdir()
    (zarr_path / ".zattrs").write_text("{not json}")
    result = read_zarr_attrs(zarr_path)
    assert result.status == "unreadable"
    assert result.error is not None


def test_read_zarr_attrs_missing_keys(tmp_path: Path) -> None:
    zarr_path = tmp_path / "tomo.zarr"
    zarr_path.mkdir()
    (zarr_path / ".zattrs").write_text("{}")
    result = read_zarr_attrs(zarr_path)
    assert result.status == "unreadable"
    assert result.error is not None


# ── frame_ext ───────────────────────────────────────────────────────────────


def test_infer_camera_falcon(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "001.eer").write_bytes(b"")
    result = infer_camera(frames_dir)
    assert result.status == "ok"
    assert result.fields["camera"] == "Falcon"


def test_infer_camera_k3_tiff(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "001.tiff").write_bytes(b"")
    result = infer_camera(frames_dir)
    assert result.status == "ok"
    assert result.fields["camera"] == "K3"


def test_infer_camera_k3_tif(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "001.tif").write_bytes(b"")
    result = infer_camera(frames_dir)
    assert result.status == "ok"
    assert result.fields["camera"] == "K3"


def test_infer_camera_ambiguous(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "001.eer").write_bytes(b"")
    (frames_dir / "002.tiff").write_bytes(b"")
    result = infer_camera(frames_dir)
    assert result.status == "unreadable"
    assert result.error is not None
    assert "ambiguous" in result.error


def test_infer_camera_no_recognized(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "001.unknown").write_bytes(b"")
    result = infer_camera(frames_dir)
    assert result.status == "missing"


def test_infer_camera_missing_dir(tmp_path: Path) -> None:
    result = infer_camera(tmp_path / "nope")
    assert result.status == "missing"


# ── ParseResult sanity ──────────────────────────────────────────────────────


def test_parse_result_defaults() -> None:
    r = ParseResult()
    assert r.fields == {}
    assert r.status == "ok"
    assert r.error is None
