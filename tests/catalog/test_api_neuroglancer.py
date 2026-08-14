"""Stateless Neuroglancer launch endpoints (plan §7.4, §7.5).

Tomogram and annotation launches build a Neuroglancer ``ViewerState`` URL over
a ``precomputed://`` source served by mrc-ng-server — no server started, no
volume loaded in-process.

Coverage:
    - ``read_mrc_viewer_params`` voxel size matches mrc-server's own header parse
    - 404 on unknown tomogram id
    - Tomogram launch returns a precomputed viewer URL; 500 without MRCNG_BASE_URL
    - IMOD X/Y mirror + contrast bake into the layer state
    - Annotation launch falls back to its group tomogram, with the bbox inlined
"""
from __future__ import annotations

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


def _write_synthetic_mrc(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.linspace(0, 100, 4 * 8 * 8, dtype=np.float32).reshape(4, 8, 8)
    with mrcfile.new(path, overwrite=True) as mrc:
        mrc.set_data(data)
        mrc.voxel_size = (10.0, 10.0, 10.0)


def test_viewer_params_voxel_equals_mrc_server_advertised(tmp_path):
    """Portal's baked ViewerState scale == mrc-server's advertised base resolution.

    Both must go through ``mrcng.parse_header`` + ``/ 10`` so the coordinate
    space in the stateless URL matches the precomputed ``info`` mrc-server serves.
    Fails if the portal ever re-derives voxel size a different way.
    """
    import os as _os

    from mrcng.mrcheader import parse_header
    from mrcng.precomputed import build_info, plan_scales

    from catalog.imaging._mrc import read_mrc_viewer_params

    path = tmp_path / "t.mrc"
    _write_synthetic_mrc(path)

    _size, voxel_nm, _contrast = read_mrc_viewer_params(path)

    st = _os.stat(path)
    fd = _os.open(str(path), _os.O_RDONLY)
    try:
        hdr = parse_header(fd, st.st_size, st.st_mtime_ns)
    finally:
        _os.close(fd)
    scales = plan_scales((hdr.nx, hdr.ny, hdr.nz), min_axis_size=32, max_levels=1)
    advertised = tuple(build_info(hdr, scales, chunk_size=(64, 64, 64))["scales"][0]["resolution"])

    assert voxel_nm == pytest.approx(advertised)


@pytest.fixture
def client(tmp_path):
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

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    # A bounding-box annotation: a *_neuroglancer.json overlay, no derived_from,
    # so the launch must fall back to a tomogram in its alignment group.
    bbox_json = data_root / "sample_a" / "acq1" / "bbox_neuroglancer.json"
    bbox_json.write_text(json.dumps([{"type": "annotation", "name": "bb", "annotations": []}]))

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


def _viewer_state(url: str) -> dict:
    """Decode a Neuroglancer ``<base>#!<json>`` URL back to its state dict."""
    return json.loads(unquote(url.split("#!", 1)[1]))


def test_launch_returns_precomputed_viewer_url(client, monkeypatch):
    """Tomogram launch returns a stateless viewer URL (no in-process viewer).

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
    # View centered on the volume, not the [0.5, 0.5, 0.5] corner default.
    assert state["position"] == [100.0, 50.0, 25.0]  # size_xyz / 2


def test_bbox_annotation_falls_back_to_group_tomogram(client, monkeypatch):
    """A bbox annotation with no derived_from launches over a group tomogram.

    Regression: the route used a stale ``target_tomogram`` attribute (500), and
    even renamed it would 422 since scanned annotations rarely set derived_from.

    The launch is stateless (no in-process viewer, black-screen z-scale-0 bug
    gone): it returns a precomputed viewer URL over the group tomogram with the
    bbox baked in as an inline annotation layer.
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
