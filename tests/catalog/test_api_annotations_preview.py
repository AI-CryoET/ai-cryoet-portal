"""Annotation preview endpoint.

Seeds a small synthetic MRC under a tmp ``CATALOG_DATA_ROOT``, registers an
annotation row whose ``files`` list points at it, then hits
``GET /annotations/.../preview.png``.

Coverage:
    - 200 + ``image/png`` for an annotation with a real ``.mrc``
    - ETag round-trip → 304 on ``If-None-Match``
    - 404 for unknown id
    - 404 for soft-deleted parent sample
    - 422 for an annotation whose ``files`` has no ``.mrc``
    - 404 for an annotation whose ``.mrc`` is missing on disk
"""
from __future__ import annotations

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


def _write_synthetic_mrc(path: Path) -> None:
    """Write a small valid MRC at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.linspace(0, 255, 8 * 16 * 16, dtype=np.float32).reshape(8, 16, 16)
    with mrcfile.new(path, overwrite=True) as mrc:
        mrc.set_data(data)
        mrc.voxel_size = (10.0, 10.0, 10.0)


@pytest.fixture
def client(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    mrc_path = data_root / "sample_a" / "acq1" / "ann1" / "seg.mrc"
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

    s = Session()
    try:
        s.add(orm.SampleORM(
            sample_id="sample_a",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ))
        s.add(orm.AcquisitionORM(sample_id="sample_a", acquisition_id="acq1"))
        # Annotation with an .mrc (plus sibling artifacts that must be ignored)
        s.add(orm.AnnotationORM(
            sample_id="sample_a", acquisition_id="acq1",
            reconstruction_alignment_id="align1", annotation_id="ann1",
            type="membrane_segmentation",
            files=[
                str(mrc_path.with_suffix(".zarr")),
                str(mrc_path),
                str(mrc_path.with_suffix(".star")),
            ],
        ))
        # Annotation with no .mrc artifact
        s.add(orm.AnnotationORM(
            sample_id="sample_a", acquisition_id="acq1",
            reconstruction_alignment_id="align1", annotation_id="ann_nomrc",
            files=[str(mrc_path.with_suffix(".star"))],
        ))
        # Annotation whose .mrc doesn't exist on disk
        s.add(orm.AnnotationORM(
            sample_id="sample_a", acquisition_id="acq1",
            reconstruction_alignment_id="align1", annotation_id="ann_missing",
            files=[str(data_root / "sample_a" / "acq1" / "ann_missing" / "gone.mrc")],
        ))
        # Soft-deleted sample
        import time
        s.add(orm.SampleORM(
            sample_id="sample_dead",
            data_source=DataSource.experimental,
            project=Project.chromatin,
            deleted_at=time.time(),
        ))
        s.add(orm.AcquisitionORM(sample_id="sample_dead", acquisition_id="acq1"))
        s.add(orm.AnnotationORM(
            sample_id="sample_dead", acquisition_id="acq1",
            reconstruction_alignment_id="align1", annotation_id="ann1",
            files=[str(mrc_path)],
        ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


def test_preview_returns_png(client):
    r = client.get("/annotations/sample_a/acq1/align1/ann1/preview.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "etag" in {k.lower() for k in r.headers}
    assert r.headers["cache-control"].startswith("public")


def test_preview_etag_roundtrip_returns_304(client):
    r1 = client.get("/annotations/sample_a/acq1/align1/ann1/preview.png")
    etag = r1.headers["etag"]
    r2 = client.get(
        "/annotations/sample_a/acq1/align1/ann1/preview.png",
        headers={"If-None-Match": etag},
    )
    assert r2.status_code == 304
    assert r2.headers["etag"] == etag


def test_preview_unknown_annotation_404(client):
    r = client.get("/annotations/sample_a/acq1/align1/nope/preview.png")
    assert r.status_code == 404


def test_preview_soft_deleted_sample_404(client):
    r = client.get("/annotations/sample_dead/acq1/align1/ann1/preview.png")
    assert r.status_code == 404


def test_preview_no_mrc_artifact_422(client):
    r = client.get("/annotations/sample_a/acq1/align1/ann_nomrc/preview.png")
    assert r.status_code == 422


def test_preview_missing_file_404_via_path_validation(client):
    """``Path.resolve(strict=True)`` raises FileNotFoundError, surfaced as 404."""
    r = client.get("/annotations/sample_a/acq1/align1/ann_missing/preview.png")
    assert r.status_code == 404


def test_neuroglancer_no_mrc_artifact_422(client):
    r = client.post("/annotations/sample_a/acq1/align1/ann_nomrc/neuroglancer")
    assert r.status_code == 422


def test_neuroglancer_unknown_annotation_404(client):
    r = client.post("/annotations/sample_a/acq1/align1/nope/neuroglancer")
    assert r.status_code == 404


def test_neuroglancer_soft_deleted_sample_404(client):
    r = client.post("/annotations/sample_dead/acq1/align1/ann1/neuroglancer")
    assert r.status_code == 404
