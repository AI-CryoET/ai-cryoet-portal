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
import json
from pathlib import Path
from urllib.parse import unquote

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

    # A bounding-box annotation: a *_neuroglancer.json overlay, no derived_from,
    # so the launch must fall back to a tomogram in its alignment group.
    import json as _json
    bbox_json = data_root / "sample_a" / "acq1" / "bbox_neuroglancer.json"
    bbox_json.write_text(_json.dumps([{"type": "annotation", "name": "bb", "annotations": []}]))

    s = Session()
    try:
        s.add(orm.SampleORM(
            sample_id="sample_a", data_source=DataSource.experimental, project=Project.chromatin,
        ))
        s.add(orm.AcquisitionORM(sample_id="sample_a", acquisition_id="acq1"))
        for tid in ("t1", "t2", "t3", "t4"):
            s.add(orm.PostProcessedTomogramORM(
                sample_id="sample_a", acquisition_id="acq1",
                reconstruction_alignment_id="align1", tomogram_id=tid,
                mrc_path=str(mrc_path),
                image_size_x=8, image_size_y=8, image_size_z=4,
            ))
        s.add(orm.AnnotationORM(
            sample_id="sample_a", acquisition_id="acq1",
            reconstruction_alignment_id="align1", annotation_id="bounding_boxes",
            derived_from=None, files=[str(bbox_json)],
        ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


def test_unknown_tomogram_404(client):
    r = client.post("/tomograms/sample_a/acq1/align1/nope/neuroglancer")
    assert r.status_code == 404


def test_unknown_tilt_series_404(client):
    r = client.post("/tilt-series/sample_a/acq1/nope/neuroglancer")
    assert r.status_code == 404


def _viewer_state(url: str) -> dict:
    """Decode a Neuroglancer ``<base>#!<json>`` URL back to its state dict."""
    return json.loads(unquote(url.split("#!", 1)[1]))


def test_launch_returns_precomputed_viewer_url(client, monkeypatch):
    """Tomogram launch now returns a stateless viewer URL (no in-process viewer).

    The URL points the configured viewer app at a ``precomputed://`` source
    under MRCNG_BASE_URL, with the tomogram's mrc_path as the served relpath.
    """
    monkeypatch.setenv("MRCNG_BASE_URL", "http://mrc-server:9000/data")
    monkeypatch.setenv("NEUROGLANCER_VIEWER_URL", "https://viewer.example/ng")
    r = client.post("/tomograms/sample_a/acq1/align1/t1/neuroglancer")
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("https://viewer.example/ng#!")
    state = _viewer_state(url)
    (layer,) = state["layers"]
    src = layer["source"]
    src_url = src["url"] if isinstance(src, dict) else src[0]["url"]
    assert src_url.startswith("precomputed://http://mrc-server:9000/data/")
    assert src_url.endswith("/sample_a/acq1/t1.mrc")


def test_launch_500_without_mrcng_base_url(client, monkeypatch):
    """A missing MRCNG_BASE_URL is a config error, surfaced as 500 (not a bad URL)."""
    monkeypatch.delenv("MRCNG_BASE_URL", raising=False)
    r = client.post("/tomograms/sample_a/acq1/align1/t1/neuroglancer")
    assert r.status_code == 500


def test_build_precomputed_viewer_url_bakes_mirror_and_contrast():
    """The IMOD X/Y mirror and contrast serialize into the layer state.

    Guards the flip matrix: x and y get ``-1`` on the diagonal and an
    ``(extent-1)`` translation; z stays identity. A wrong translation here
    silently shows scientists a mis-registered / mirrored volume.
    """
    pytest.importorskip("neuroglancer")
    from catalog.api.routes.tomograms import _build_precomputed_viewer_url

    url = _build_precomputed_viewer_url(
        source_url="precomputed://http://h/data/t.mrc",
        name="t",
        viewer_base="https://viewer.example/ng",
        size_xyz=(200, 100, 50),
        voxel_nm_xyz=(1.0, 1.0, 1.0),
        contrast=(12.0, 88.0),
        mirror_xy=True,
    )
    state = _viewer_state(url)
    (layer,) = state["layers"]
    src = layer["source"]
    src = src if isinstance(src, dict) else src[0]
    m = src["transform"]["matrix"]
    assert m[0][0] == -1.0 and m[0][3] == 199.0  # flip x, extent nx-1
    assert m[1][1] == -1.0 and m[1][3] == 99.0   # flip y, extent ny-1
    assert m[2] == [0.0, 0.0, 1.0, 0.0]          # z identity
    assert layer["shaderControls"]["normalized"]["range"] == [12.0, 88.0]


def test_bbox_annotation_falls_back_to_group_tomogram(client, monkeypatch):
    """A bbox annotation with no derived_from launches over a group tomogram.

    Regression: the route used a stale ``target_tomogram`` attribute (500), and
    even renamed it would 422 since scanned annotations rarely set derived_from.

    The launch is now stateless (no in-process viewer, black-screen z-scale-0
    bug gone): it returns a precomputed viewer URL over the group tomogram with
    the bbox baked in as an inline annotation layer.
    """
    monkeypatch.setenv("MRCNG_BASE_URL", "http://mrc-server:9000/data")
    monkeypatch.setenv("NEUROGLANCER_VIEWER_URL", "https://viewer.example/ng")
    r = client.post("/annotations/sample_a/acq1/align1/bounding_boxes/neuroglancer")
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("https://viewer.example/ng#!")
    state = _viewer_state(url)
    img = [layer for layer in state["layers"] if layer.get("type") != "annotation"][0]
    src = img["source"]
    src_url = src["url"] if isinstance(src, dict) else src[0]["url"]
    assert src_url.startswith("precomputed://http://mrc-server:9000/data/")
    assert src_url.endswith("/sample_a/acq1/t1.mrc")  # the group tomogram, not the annotation
    bbox = [layer for layer in state["layers"] if layer.get("type") == "annotation"][0]
    assert bbox["name"] == "bb"


def test_lru_evicts_oldest_at_capacity(client):
    """At capacity 2, launching a 3rd viewer evicts the first (shared registry
    logic behind the tilt-series / annotation in-process launches)."""
    from catalog.api.routes.tomograms import launch_viewer_in_registry

    class FakeRequest:
        def __init__(self, app):
            self.app = app

    keys = [("tomogram", "sample_a", "acq1", f"t{i}") for i in (1, 2, 3)]

    async def driver():
        client.app.state.active_viewers_lock = asyncio.Lock()
        req = FakeRequest(client.app)
        for k in keys:
            await launch_viewer_in_registry(req, k, lambda: _FakeViewer())

    from collections import OrderedDict
    client.app.state.active_viewers = OrderedDict()
    asyncio.run(driver())
    reg_keys = list(client.app.state.active_viewers.keys())
    assert keys[0] not in reg_keys  # oldest evicted
    assert reg_keys[-1] == keys[2]  # newest at the end
    assert len(reg_keys) == 2


def test_lru_relaunch_same_key_moves_to_end_no_evict(client):
    """Re-launching an already-registered key updates its position, not capacity."""
    from catalog.api.routes.tomograms import launch_viewer_in_registry

    class FakeRequest:
        def __init__(self, app):
            self.app = app

    k1 = ("tomogram", "sample_a", "acq1", "t1")
    k2 = ("tomogram", "sample_a", "acq1", "t2")

    async def driver():
        client.app.state.active_viewers_lock = asyncio.Lock()
        req = FakeRequest(client.app)
        for k in (k1, k2, k1):  # relaunch k1 last — must NOT evict k2
            await launch_viewer_in_registry(req, k, lambda: _FakeViewer())

    from collections import OrderedDict
    client.app.state.active_viewers = OrderedDict()
    asyncio.run(driver())
    reg_keys = list(client.app.state.active_viewers.keys())
    assert reg_keys[-1] == k1
    assert k2 in reg_keys
    assert len(reg_keys) == 2


def test_teardown_viewer_releases_volume():
    """Teardown drops every strong ref to the viewer's volume so it can be freed.

    Pins the layer/volume-manager coupling ``teardown_viewer`` relies on: a
    neuroglancer bump that changed it would silently reintroduce the leak. We
    assert the semantic invariant (nothing strongly references the volume after
    teardown → it's collectable) rather than RSS, which is allocator-dependent
    in a shared test process. RSS return is verified standalone: ~1 GiB volume,
    RSS 1074 → 51 MB after teardown.
    """
    import gc
    import weakref

    neuroglancer = pytest.importorskip("neuroglancer")
    from catalog.imaging._neuroglancer import teardown_viewer

    neuroglancer.set_server_bind_address("127.0.0.1", bind_port=0)

    def build():
        """Build in a helper so the txn-state local (which holds the layer →
        LocalVolume) is gone when we return — otherwise it pins the volume."""
        data = np.ones((64, 128, 128), dtype=np.uint16)
        dims = neuroglancer.CoordinateSpace(
            names=["z", "y", "x"], scales=[1, 1, 1], units="nm"
        )
        lv = neuroglancer.LocalVolume(data, dimensions=dims)
        viewer = neuroglancer.Viewer()
        with viewer.txn() as s:
            s.layers["vol"] = neuroglancer.ImageLayer(
                source=neuroglancer.LayerDataSource(url=lv)
            )
        return viewer, weakref.ref(lv), weakref.ref(data)

    viewer, vol_ref, arr_ref = build()
    # NB: never put ``vol_ref()`` inside an ``assert`` — pytest's assertion
    # rewriting binds the returned object to a hidden frame local, keeping it
    # alive and defeating the weakref check. Evaluate liveness in plain
    # statements instead.
    volumes_before = len(viewer.volume_manager.volumes)
    alive_before = vol_ref() is not None and arr_ref() is not None
    assert volumes_before == 1
    assert alive_before

    teardown_viewer(viewer)
    gc.collect()

    volumes_after = len(viewer.volume_manager.volumes)
    vol_dead = vol_ref() is None  # LocalVolume no longer referenced → freed
    arr_dead = arr_ref() is None  # and so is its numpy array
    assert volumes_after == 0
    assert vol_dead
    assert arr_dead


def test_teardown_viewer_survives_broken_viewer():
    """Teardown of a viewer without a usable ``txn`` must not raise (best-effort)."""
    from catalog.imaging._neuroglancer import teardown_viewer

    teardown_viewer(_FakeViewer())  # _FakeViewer has no .txn(); must be swallowed


def test_eviction_tears_down_evicted_viewer(client, monkeypatch):
    """LRU eviction calls teardown_viewer on the dropped viewer."""
    import catalog.imaging._neuroglancer as ng_mod
    from catalog.api.routes.tomograms import launch_viewer_in_registry

    torn = []
    monkeypatch.setattr(ng_mod, "teardown_viewer", lambda v: torn.append(v.id))

    class FakeRequest:
        def __init__(self, app):
            self.app = app

    async def driver():
        client.app.state.active_viewers_lock = asyncio.Lock()
        req = FakeRequest(client.app)
        for i in range(3):  # cap is 2 → the 3rd launch evicts the 1st
            await launch_viewer_in_registry(
                req, ("tomogram", "s", "a", f"t{i}"), lambda: _FakeViewer()
            )

    from collections import OrderedDict
    client.app.state.active_viewers = OrderedDict()
    asyncio.run(driver())
    assert len(torn) == 1  # exactly one viewer evicted + torn down


class _GenViewer:
    """Viewer whose state_generation we can bump to simulate interaction."""

    def __init__(self, gen):
        self._gen = gen

    @property
    def config_state(self):
        outer = self

        class _CS:
            state_generation = outer._gen

        return _CS()


def _run_one_sweep(app, **kw):
    """Drive ``sweep_idle_viewers`` through a single pass, then cancel it."""
    from catalog.api.routes.tomograms import sweep_idle_viewers

    async def driver():
        app.state.active_viewers_lock = asyncio.Lock()
        task = asyncio.create_task(sweep_idle_viewers(app, interval=0.01, **kw))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(driver())


def test_sweep_reclaims_idle_under_pressure_but_keeps_active(client, monkeypatch):
    """Under memory pressure, the sweep tears down a stale entry, spares an active one."""
    import catalog.imaging._neuroglancer as ng_mod
    import catalog.api.routes.tomograms as tomo_mod
    from catalog.api.routes.tomograms import ViewerEntry

    torn = []
    monkeypatch.setattr(ng_mod, "teardown_viewer", lambda v: torn.append(v))
    monkeypatch.setattr(tomo_mod, "_memory_usage_ratio", lambda: 0.95)  # under pressure

    from collections import OrderedDict
    idle = _GenViewer(1)
    active = _GenViewer(1)
    reg = OrderedDict()
    reg[("idle",)] = ViewerEntry(idle, last_active=0.0, last_gen=1)  # far in the past
    reg[("active",)] = ViewerEntry(active, last_active=0.0, last_gen=1)
    client.app.state.active_viewers = reg
    active._gen = 2  # active viewer's client pushed new state since last sweep

    _run_one_sweep(client.app, ttl=1.0, pressure_ratio=0.8)

    assert torn == [idle]
    assert list(reg.keys()) == [("active",)]


def test_sweep_keeps_idle_when_no_memory_pressure(client, monkeypatch):
    """With RAM to spare, an idle viewer is NOT reclaimed (only fires under pressure)."""
    import catalog.imaging._neuroglancer as ng_mod
    import catalog.api.routes.tomograms as tomo_mod
    from catalog.api.routes.tomograms import ViewerEntry

    torn = []
    monkeypatch.setattr(ng_mod, "teardown_viewer", lambda v: torn.append(v))
    monkeypatch.setattr(tomo_mod, "_memory_usage_ratio", lambda: 0.10)  # no pressure

    from collections import OrderedDict
    reg = OrderedDict()
    reg[("idle",)] = ViewerEntry(_GenViewer(1), last_active=0.0, last_gen=1)
    client.app.state.active_viewers = reg

    _run_one_sweep(client.app, ttl=1.0, pressure_ratio=0.8)

    assert torn == []
    assert list(reg.keys()) == [("idle",)]


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

    keys = [("tomogram", "sample_a", "acq1", "align1", f"t{i}") for i in range(5)]

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
