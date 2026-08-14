"""Tilt-series preview + acquisition polar endpoints (plan §7.5).

Coverage:
    - GET preview.png — zarr path (synthetic ome.zarr) returns PNG
    - GET preview.png — st_path (.st/.mrc stack) returns PNG
    - GET preview.png — acquisition Frames/ fallback returns PNG when the
      series has no stack artifact of its own
    - GET preview.png — 422 when the series has no stack artifact AND the
      acquisition has no resolvable Frames dir
    - GET preview.png — 422 when the Frames dir has no viewable images
    - GET preview.png — 404 for unknown tilt_series id / soft-deleted parent
    - GET /acquisitions/{s}/{a}/polar.png — 200 + PNG when tilt_angles cached
    - GET /acquisitions/{s}/{a}/polar.png — 422 when tilt_angles missing
    - GET /acquisitions/{s}/{a}/polar.png — cache returns identical bytes
    - GET /acquisitions/{s}/{a}/polar.png — 404 for unknown acquisition
"""
from __future__ import annotations

import time
from pathlib import Path

import mrcfile
import numpy as np
import pytest
import zarr
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from catalog import db, orm
from catalog.api.deps import get_session
from catalog.api.main import create_app
from schema.schema import DataSource, Project


def _write_zarr_tilt_stack(zarr_path: Path, n: int = 5) -> None:
    """Create an ome.zarr-style store with a ``tilt_series`` dataset + angles attr."""
    root = zarr.open_group(str(zarr_path), mode="w")
    data = np.linspace(0, 100, n * 8 * 8, dtype=np.float32).reshape(n, 8, 8)
    ds = root.create_array("tilt_series", shape=data.shape, dtype=data.dtype, chunks=(1, 8, 8))
    ds[:] = data
    root.update_attributes({"tilt_angles": [-30.0, -15.0, 0.0, 15.0, 30.0][:n]})


def _write_st_stack(path: Path, n: int = 5) -> None:
    """Write an ``.st``/``.mrc`` projection stack (3D)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.linspace(0, 100, n * 8 * 8, dtype=np.float32).reshape(n, 8, 8)
    with mrcfile.new(path, overwrite=True) as mrc:
        mrc.set_data(data)


def _write_frame_tiffs(frames_dir: Path) -> None:
    """Write TIFF frames named so ``extract_tilt_angle_from_filename`` recovers angles."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    import tifffile

    for name in ("scan_001_-30.0.tif", "scan_002_0.0.tif", "scan_003_30.0.tif"):
        tifffile.imwrite(
            frames_dir / name,
            np.linspace(0, 200, 16 * 16, dtype=np.float32).reshape(16, 16),
        )


@pytest.fixture
def client(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()

    # acq1: has zarr/st tilt series + a Frames/ dir with viewable images so the
    # frames-fallback series (ts_frames) can resolve.
    acq1_dir = data_root / "sample_a" / "acq1"
    acq1_dir.mkdir(parents=True)

    zarr_path = acq1_dir / "TiltSeries" / "ts_zarr" / "stack" / "ts1.zarr"
    _write_zarr_tilt_stack(zarr_path)

    st_path = acq1_dir / "TiltSeries" / "ts_st" / "stack" / "ts1.st"
    _write_st_stack(st_path)

    _write_frame_tiffs(acq1_dir / "Frames")

    # acq_noframes: a tilt series with no stack artifact and an acquisition
    # with no path at all → _resolve_acq_frames_dir returns None → 422.

    # acq_emptyframes: Frames/ exists but holds no viewable images → 422.
    acq_emptyframes_dir = data_root / "sample_a" / "acq_emptyframes"
    (acq_emptyframes_dir / "Frames").mkdir(parents=True)
    (acq_emptyframes_dir / "Frames" / "notes.txt").write_text("nothing here\n")

    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    app = create_app()
    app.state.engine = engine
    app.state.data_root_resolved = data_root.resolve()

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    s = Session()
    try:
        s.add(orm.SampleORM(
            sample_id="sample_a", data_source=DataSource.experimental, project=Project.chromatin,
        ))
        s.add(orm.AcquisitionORM(
            sample_id="sample_a", acquisition_id="acq1",
            path=str(acq1_dir), pixel_size=10.0,
            tilt_angles=[-30.0, -15.0, 0.0, 15.0, 30.0],
        ))
        s.add(orm.AcquisitionORM(
            sample_id="sample_a", acquisition_id="acq_noframes",
            path=None, tilt_angles=None,
        ))
        s.add(orm.AcquisitionORM(
            sample_id="sample_a", acquisition_id="acq_emptyframes",
            path=str(acq_emptyframes_dir),
        ))

        # zarr-backed series
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq1", tilt_series_id="ts_zarr",
            zarr_path=str(zarr_path), mtime=1234567890.0,
        ))
        # st-backed series
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq1", tilt_series_id="ts_st",
            st_path=str(st_path), mtime=1234567890.0,
        ))
        # no stack artifact → falls back to acq1's Frames/ (has images)
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq1", tilt_series_id="ts_frames",
            mtime=1234567890.0,
        ))
        # no stack artifact, acquisition has no Frames/ dir → 422
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq_noframes",
            tilt_series_id="ts_nopath",
        ))
        # no stack artifact, Frames/ exists but no viewable images → 422
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq_emptyframes",
            tilt_series_id="ts_empty",
        ))

        # Soft-deleted parent sample
        s.add(orm.SampleORM(
            sample_id="sample_dead", data_source=DataSource.experimental, project=Project.chromatin,
            deleted_at=time.time(),
        ))
        s.add(orm.AcquisitionORM(
            sample_id="sample_dead", acquisition_id="acq1",
            path=str(acq1_dir), tilt_angles=[0.0],
        ))
        s.add(orm.TiltSeriesORM(
            sample_id="sample_dead", acquisition_id="acq1", tilt_series_id="ts_zarr",
            zarr_path=str(zarr_path),
        ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


# ── preview.png ─────────────────────────────────────────────────────────

def test_preview_zarr_returns_png(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_zarr/preview.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_st_returns_png(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_st/preview.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_frames_fallback_returns_png(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_frames/preview.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_no_frames_dir_422(client):
    r = client.get("/tilt-series/sample_a/acq_noframes/ts_nopath/preview.png")
    assert r.status_code == 422


def test_preview_no_viewable_images_422(client):
    r = client.get("/tilt-series/sample_a/acq_emptyframes/ts_empty/preview.png")
    assert r.status_code == 422


def test_preview_unknown_tilt_series_404(client):
    r = client.get("/tilt-series/sample_a/acq1/nope/preview.png")
    assert r.status_code == 404


def test_preview_soft_deleted_parent_404(client):
    r = client.get("/tilt-series/sample_dead/acq1/ts_zarr/preview.png")
    assert r.status_code == 404


# ── acquisition polar.png ─────────────────────────────────────────────────

def test_polar_returns_png(client):
    r = client.get("/acquisitions/sample_a/acq1/polar.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_polar_cache_returns_same_bytes(client):
    r1 = client.get("/acquisitions/sample_a/acq1/polar.png")
    r2 = client.get("/acquisitions/sample_a/acq1/polar.png")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.content == r2.content


def test_polar_missing_angles_422(client):
    r = client.get("/acquisitions/sample_a/acq_noframes/polar.png")
    assert r.status_code == 422


def test_polar_unknown_acquisition_404(client):
    r = client.get("/acquisitions/sample_a/nope/polar.png")
    assert r.status_code == 404
