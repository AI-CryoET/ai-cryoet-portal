"""Tests for GET /md-previews/{relpath} endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from catalog import db
from catalog.api.deps import get_session
from catalog.api.main import create_app

_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _seed_app(tmp_path, md_root):
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    app = create_app()
    app.state.engine = engine
    app.state.data_root_resolved = tmp_path  # required by lifespan guard
    app.state.thumbnail_root = tmp_path  # bypass required-thumbnail guard
    app.state.md_preview_root = md_root

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session
    return app


@pytest.fixture
def client(tmp_path):
    md_dir = tmp_path / ".md-preview-cache"
    md_dir.mkdir()
    app = _seed_app(tmp_path, md_dir)
    return TestClient(app), md_dir


def test_get_md_preview_existing_file(client):
    test_client, md_dir = client
    name = "Bulk_25_dna_wrap_preview.png"
    (md_dir / name).write_bytes(_FAKE_PNG)

    r = test_client.get(f"/md-previews/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == _FAKE_PNG


def test_get_md_preview_missing_file(client):
    test_client, _ = client
    r = test_client.get("/md-previews/nonexistent_preview.png")
    assert r.status_code == 404


def test_get_md_preview_traversal_attempt(client):
    test_client, _ = client
    r = test_client.get("/md-previews/../etc/passwd")
    assert r.status_code == 404


def test_get_md_preview_non_png_rejected(client):
    test_client, md_dir = client
    (md_dir / "notes.txt").write_text("hello")
    r = test_client.get("/md-previews/notes.txt")
    assert r.status_code == 404


def test_get_md_preview_by_prefix(client):
    test_client, md_dir = client
    # Cached name has an unpredictable suffix; caller only knows the prefix.
    (md_dir / "Slab_12mer_25_0.073_md_runs_r1_Trajectories_dna_wrap_preview.png").write_bytes(
        _FAKE_PNG
    )
    r = test_client.get("/md-previews/by-prefix/Slab_12mer_25_0.073")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == _FAKE_PNG


def test_get_md_preview_by_prefix_no_match(client):
    test_client, _ = client
    r = test_client.get("/md-previews/by-prefix/Slab_does_not_exist")
    assert r.status_code == 404


def test_get_md_preview_by_prefix_traversal(client):
    test_client, _ = client
    r = test_client.get("/md-previews/by-prefix/..%2f..%2fetc")
    assert r.status_code == 404


def test_get_md_preview_not_configured(tmp_path):
    """If md_preview_root is None, every request returns 404."""
    app = _seed_app(tmp_path, None)
    test_client = TestClient(app)
    r = test_client.get("/md-previews/Bulk_25_dna_wrap_preview.png")
    assert r.status_code == 404
