"""CATALOG_THUMBNAIL_DIR / CATALOG_MD_PREVIEW_DIR default under ./data in the
cwd when unset, so local dev doesn't have to pass them to `pixi run api` — and
so concurrent devs pointed at the same shared CATALOG_DATA_ROOT don't race on
the same cache files."""
from __future__ import annotations

from fastapi.testclient import TestClient

from catalog.api.main import create_app


def test_thumbnail_and_md_preview_dirs_default_under_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("CATALOG_THUMBNAIL_DIR", raising=False)
    monkeypatch.delenv("CATALOG_MD_PREVIEW_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "data_root"
    data_root.mkdir()
    monkeypatch.setenv("CATALOG_DATA_ROOT", str(data_root))
    monkeypatch.setenv("CATALOG_DB_URL", f"sqlite:///{tmp_path / 'test.db'}")

    thumb_dir = tmp_path / "data" / ".thumbnail-cache"
    thumb_dir.mkdir(parents=True)
    md_dir = tmp_path / "data" / ".md-preview-cache"
    md_dir.mkdir(parents=True)

    app = create_app()
    with TestClient(app):
        assert app.state.thumbnail_root == thumb_dir.resolve()
        assert app.state.md_preview_root == md_dir.resolve()


def test_missing_md_preview_dir_disables_route_without_failing_startup(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CATALOG_THUMBNAIL_DIR", raising=False)
    monkeypatch.delenv("CATALOG_MD_PREVIEW_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "data_root"
    data_root.mkdir()
    monkeypatch.setenv("CATALOG_DATA_ROOT", str(data_root))
    monkeypatch.setenv("CATALOG_DB_URL", f"sqlite:///{tmp_path / 'test.db'}")
    (tmp_path / "data" / ".thumbnail-cache").mkdir(parents=True)
    # .md-preview-cache deliberately left absent.

    app = create_app()
    with TestClient(app):
        assert app.state.md_preview_root is None
