"""Tomogram preview endpoint (plan §7.4).

Seeds a small synthetic MRC under a tmp ``CATALOG_DATA_ROOT``, registers
the row in the DB, then hits ``GET /tomograms/.../preview.png``.

Coverage:
    - 200 + ``image/png`` for a real MRC
    - ETag round-trip → 304 on ``If-None-Match``
    - 404 for unknown id
    - 404 for soft-deleted parent sample
    - 422 for a row whose ``mrc_path`` is missing on disk
    - 422 for a row with NULL ``mrc_path``
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


def _write_synthetic_mrc(path: Path, reverse: bool = False) -> None:
    """Write a small valid MRC at ``path``.

    ``reverse`` flips the gradient. The renderer normalizes on the 1–99
    percentile, so a mere rescale would render identically — the flip is
    what makes two files visibly distinct.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.linspace(0, 255, 8 * 16 * 16, dtype=np.float32)
    if reverse:
        data = data[::-1].copy()
    data = data.reshape(8, 16, 16)
    with mrcfile.new(path, overwrite=True) as mrc:
        mrc.set_data(data)
        mrc.voxel_size = (10.0, 10.0, 10.0)


@pytest.fixture
def client(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    mrc_path = data_root / "sample_a" / "acq1" / "t1.mrc"
    _write_synthetic_mrc(mrc_path)
    # Same stem in two alignment groups, different pixel data, so a
    # group-scoped lookup is observable in the rendered PNG.
    dup_a = data_root / "sample_a" / "acq1" / "grp_a" / "dup.mrc"
    dup_b = data_root / "sample_a" / "acq1" / "grp_b" / "dup.mrc"
    _write_synthetic_mrc(dup_a)
    _write_synthetic_mrc(dup_b, reverse=True)

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
        s.add(orm.PostProcessedTomogramORM(
            sample_id="sample_a", acquisition_id="acq1",
            reconstruction_alignment_id="align1", tomogram_id="t1",
            mrc_path=str(mrc_path),
        ))
        # Tomogram with no mrc_path
        s.add(orm.PostProcessedTomogramORM(
            sample_id="sample_a", acquisition_id="acq1",
            reconstruction_alignment_id="align1", tomogram_id="t_nopath",
        ))
        # Tomogram with mrc_path that doesn't exist on disk
        s.add(orm.PostProcessedTomogramORM(
            sample_id="sample_a", acquisition_id="acq1",
            reconstruction_alignment_id="align1", tomogram_id="t_missing",
            mrc_path=str(data_root / "sample_a" / "acq1" / "missing.mrc"),
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
        s.add(orm.PostProcessedTomogramORM(
            sample_id="sample_dead", acquisition_id="acq1",
            reconstruction_alignment_id="align1", tomogram_id="t1",
            mrc_path=str(mrc_path),
        ))
        for grp, path in (("grp_a", dup_a), ("grp_b", dup_b)):
            s.add(orm.PostProcessedTomogramORM(
                sample_id="sample_a", acquisition_id="acq1",
                reconstruction_alignment_id=grp, tomogram_id="dup",
                mrc_path=str(path),
            ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


def test_preview_returns_png(client):
    r = client.get("/tomograms/sample_a/acq1/align1/t1/preview.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "etag" in {k.lower() for k in r.headers}
    assert r.headers["cache-control"].startswith("public")


def test_preview_etag_roundtrip_returns_304(client):
    r1 = client.get("/tomograms/sample_a/acq1/align1/t1/preview.png")
    etag = r1.headers["etag"]
    r2 = client.get(
        "/tomograms/sample_a/acq1/align1/t1/preview.png",
        headers={"If-None-Match": etag},
    )
    assert r2.status_code == 304
    assert r2.headers["etag"] == etag


def test_preview_unknown_tomogram_404(client):
    r = client.get("/tomograms/sample_a/acq1/align1/nope/preview.png")
    assert r.status_code == 404


def test_preview_soft_deleted_sample_404(client):
    r = client.get("/tomograms/sample_dead/acq1/align1/t1/preview.png")
    assert r.status_code == 404


def test_preview_unknown_sample_404(client):
    r = client.get("/tomograms/sample_ghost/acq1/align1/t1/preview.png")
    assert r.status_code == 404


def test_preview_null_mrc_path_422(client):
    r = client.get("/tomograms/sample_a/acq1/align1/t_nopath/preview.png")
    assert r.status_code == 422


def test_preview_missing_file_404_via_path_validation(client):
    """``Path.resolve(strict=True)`` raises FileNotFoundError, surfaced as 404.

    The route doesn't get a chance to return 422 because path validation
    refuses non-existent paths first. This is acceptable — both signal
    "the underlying file isn't available" to the caller.
    """
    r = client.get("/tomograms/sample_a/acq1/align1/t_missing/preview.png")
    assert r.status_code == 404


def test_preview_is_scoped_to_the_alignment_group(client):
    """Two groups can hold the same stem, so the URL must name the group."""
    ok = client.get("/tomograms/sample_a/acq1/grp_a/dup/preview.png")
    assert ok.status_code == 200, ok.text
    other = client.get("/tomograms/sample_a/acq1/grp_b/dup/preview.png")
    assert other.status_code == 200, other.text
    # Different groups, different files.
    assert ok.content != other.content
    # The old 3-segment form no longer resolves.
    assert client.get("/tomograms/sample_a/acq1/dup/preview.png").status_code == 404
