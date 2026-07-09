"""Drift guard: the committed starter-template zips under
frontend/public/templates/ must match a fresh deterministic build of the
canonical templates/ dirs. Mirrors the sync_templates --check pattern.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from schema.build_template_zips import ZIP_TARGETS, build_zip

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_zip_is_deterministic():
    src = _REPO_ROOT / "templates" / "sample_id_experimental"
    assert build_zip(src) == build_zip(src)


def test_zip_contains_sample_toml_and_skeleton_dirs():
    src = _REPO_ROOT / "templates" / "sample_id_experimental"
    names = set(zipfile.ZipFile(io.BytesIO(build_zip(src))).namelist())
    assert "sample_id_experimental/sample.toml" in names
    assert "sample_id_experimental/acquisition_id/Frames/" in names


def test_committed_zips_match_fresh_build():
    stale = []
    for src, out in ZIP_TARGETS:
        if not out.is_file() or out.read_bytes() != build_zip(src):
            stale.append(out.relative_to(_REPO_ROOT))
    assert not stale, (
        f"stale template zips: {stale}. Run `pixi run template-zips`."
    )
