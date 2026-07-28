"""Neuroglancer launch endpoints (plan §7.4, §7.5).

Neuroglancer's HTTP server is process-global and binds once via
``set_server_bind_address`` (plan §11.9). We monkeypatch ``view_neuroglancer``
to a fake viewer for the LRU/race tests so the test process doesn't have
to actually spin up a server — leaving the real-server smoke check for
the ``slow`` marker.

Coverage:
    - ``read_mrc_volume`` returns voxel size in nm, in array-axis order
    - 404 on unknown tomogram / tilt_series id
    - LRU eviction at capacity (oldest entry dropped, new one inserted)
    - Re-launching an already-registered key moves it to the end (no eviction)
    - Concurrent launches at capacity don't crash (asyncio.gather race)
    - ``slow``: real ``view_neuroglancer`` returns a URL
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import mrcfile
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from catalog import db, orm
from catalog.api.deps import get_session
from catalog.api.main import create_app
from schema.schema import DataSource, Project


class _FakeViewer:
    """Stand-in for ``neuroglancer.Viewer``; returns a stable URL via str()."""

    _counter = 0

    def __init__(self):
        type(self)._counter += 1
        self.id = type(self)._counter

    def __str__(self) -> str:
        return f"http://fake-host:8001/v/#!fake-{self.id}/"


def _write_synthetic_mrc(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.linspace(0, 100, 4 * 8 * 8, dtype=np.float32).reshape(4, 8, 8)
    with mrcfile.new(path, overwrite=True) as mrc:
        mrc.set_data(data)
        mrc.voxel_size = (10.0, 10.0, 10.0)


def test_read_mrc_volume_returns_nm_in_array_order(tmp_path):
    """Voxel size comes back in nm (header is Angstrom), reordered to the array axes.

    The viewer declares ``CoordinateSpace(units="nm")``, so a raw Angstrom
    spacing renders the volume 10x oversized against nm-authored annotations.
    Anisotropic spacing here so the x/y/z -> array-axis reorder is covered too.
    """
    from catalog.imaging._mrc import read_mrc_volume

    path = tmp_path / "aniso.mrc"
    with mrcfile.new(path, overwrite=True) as mrc:
        mrc.set_data(np.zeros((4, 8, 8), dtype=np.float32))
        mrc.voxel_size = (10.0, 20.0, 30.0)  # (x, y, z) Angstrom

    _, voxel_size, axis_order = read_mrc_volume(path)

    assert axis_order == "zyx"
    assert voxel_size == pytest.approx((3.0, 2.0, 1.0))


def test_read_mrc_volume_small_is_in_ram_copy(tmp_path):
    """Volumes under COPY_MAX_BYTES are read fully into RAM (not a memmap)."""
    from catalog.imaging import _mrc

    p = tmp_path / "small.mrc"
    _write_synthetic_mrc(p)
    data, _voxel, _axes = _mrc.read_mrc_volume(p)
    assert not isinstance(data, np.memmap)


def test_read_mrc_volume_oversize_falls_back_to_mmap(tmp_path, monkeypatch):
    """Volumes over COPY_MAX_BYTES fall back to mmap so the pod can't OOM."""
    from catalog.imaging import _mrc

    monkeypatch.setattr(_mrc, "COPY_MAX_BYTES", 1)  # force the tiny file oversize
    p = tmp_path / "oversize.mrc"
    _write_synthetic_mrc(p)
    data, _voxel, _axes = _mrc.read_mrc_volume(p)
    assert isinstance(data, np.memmap)


def test_read_mrc_volume_returns_readonly_array(tmp_path):
    """The shared cached array is read-only so a stray in-place write can't corrupt other viewers."""
    from catalog.imaging import _mrc

    p = tmp_path / "ro.mrc"
    _write_synthetic_mrc(p)
    data, _voxel, _axes = _mrc.read_mrc_volume(p)
    assert data.flags.writeable is False


def test_read_mrc_volume_shared_cache_returns_same_array(tmp_path):
    """Two loads of the same unchanged file share one array (no re-read)."""
    from catalog.imaging import _mrc

    p = tmp_path / "shared.mrc"
    _write_synthetic_mrc(p)
    d1, _v1, _a1 = _mrc.read_mrc_volume(p)
    d2, _v2, _a2 = _mrc.read_mrc_volume(p)
    assert d1 is d2


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    data_root.mkdir()
    mrc_path = data_root / "sample_a" / "acq1" / "t1.mrc"
    _write_synthetic_mrc(mrc_path)

    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    app = create_app()
    app.state.engine = engine
    app.state.data_root_resolved = data_root.resolve()
    # Pre-seed the registry so the lifespan handler's defaults run.
    from collections import OrderedDict
    app.state.active_viewers = OrderedDict()
    app.state.active_viewers_lock = asyncio.Lock()
    app.state.neuroglancer_max_viewers = 2  # small for eviction tests

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    # Patch view_neuroglancer to return a fake viewer (no real server spin-up).
    # The route imports it inside the launch closure, so patch at the source
    # module rather than the route's namespace.
    import catalog.imaging._neuroglancer as ng_mod
    monkeypatch.setattr(ng_mod, "view_neuroglancer", lambda data, **kw: _FakeViewer())

    s = Session()
    try:
        s.add(orm.SampleORM(
            sample_id="sample_a", data_source=DataSource.experimental, project=Project.chromatin,
        ))
        s.add(orm.AcquisitionORM(sample_id="sample_a", acquisition_id="acq1"))
        for tid in ("t1", "t2", "t3", "t4"):
            s.add(orm.PostProcessedTomogramORM(
                sample_id="sample_a", acquisition_id="acq1", tomogram_id=tid,
                mrc_path=str(mrc_path),
            ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


def test_unknown_tomogram_404(client):
    r = client.post("/tomograms/sample_a/acq1/nope/neuroglancer")
    assert r.status_code == 404


def test_unknown_tilt_series_404(client):
    r = client.post("/tilt-series/sample_a/acq1/nope/neuroglancer")
    assert r.status_code == 404


def test_launch_returns_url(client):
    r = client.post("/tomograms/sample_a/acq1/t1/neuroglancer")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].startswith("http://fake-host")


def test_lru_evicts_oldest_at_capacity(client):
    """At capacity 2, launching a 3rd viewer evicts the first."""
    app = client.app
    for tid in ("t1", "t2"):
        r = client.post(f"/tomograms/sample_a/acq1/{tid}/neuroglancer")
        assert r.status_code == 200
    assert list(app.state.active_viewers.keys()) == [
        ("tomogram", "sample_a", "acq1", "t1"),
        ("tomogram", "sample_a", "acq1", "t2"),
    ]
    r = client.post("/tomograms/sample_a/acq1/t3/neuroglancer")
    assert r.status_code == 200
    keys = list(app.state.active_viewers.keys())
    # Oldest (t1) evicted; t2 and t3 remain.
    assert ("tomogram", "sample_a", "acq1", "t1") not in keys
    assert keys[-1] == ("tomogram", "sample_a", "acq1", "t3")
    assert len(keys) == 2


def test_lru_relaunch_same_key_moves_to_end_no_evict(client):
    """Re-launching an already-registered key updates its position, not capacity."""
    app = client.app
    for tid in ("t1", "t2"):
        client.post(f"/tomograms/sample_a/acq1/{tid}/neuroglancer")
    # Re-launch t1 — should NOT evict t2.
    r = client.post("/tomograms/sample_a/acq1/t1/neuroglancer")
    assert r.status_code == 200
    keys = list(app.state.active_viewers.keys())
    assert keys[-1] == ("tomogram", "sample_a", "acq1", "t1")
    assert ("tomogram", "sample_a", "acq1", "t2") in keys
    assert len(keys) == 2


def test_concurrent_launches_dont_crash(client):
    """Concurrent launches at capacity race for eviction — must not crash.

    Hits ``launch_viewer_in_registry`` directly with a stub launch_fn so
    the test exercises the lock + LRU logic without serializing on the
    sync TestClient. The test process drives the coroutines with
    ``asyncio.run`` to avoid a pytest-asyncio dependency.
    """
    from catalog.api.routes.tomograms import launch_viewer_in_registry

    class FakeRequest:
        def __init__(self, app):
            self.app = app

    # Reset the registry + lock — TestClient drives a fresh event loop per
    # call, so the previous lock instance is bound to a closed loop and
    # would explode under asyncio.gather on a new loop.
    from collections import OrderedDict
    client.app.state.active_viewers = OrderedDict()

    keys = [("tomogram", "sample_a", "acq1", f"t{i}") for i in range(5)]

    async def driver():
        # Build the lock inside the same event loop that will await it.
        client.app.state.active_viewers_lock = asyncio.Lock()
        fake_req = FakeRequest(client.app)

        async def go(key):
            return await launch_viewer_in_registry(fake_req, key, lambda: _FakeViewer())

        return await asyncio.gather(*[go(k) for k in keys])

    results = asyncio.run(driver())
    assert all(isinstance(u, str) and u.startswith("http://fake-host") for u in results)
    assert len(client.app.state.active_viewers) <= 2
