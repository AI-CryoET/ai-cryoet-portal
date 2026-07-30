"""Drift guard for the committed frontend/openapi.json.

`frontend/src/types.gen.ts` is generated from this file, so a stale
openapi.json silently ships frontend types that no longer match schemas.py.
Mirrors the style of test_filter_fields_drift.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# FastAPI is part of the `api` feature; skip in the bare `test` env.
pytest.importorskip("fastapi")

from catalog.api.generate_openapi import _DEFAULT_OUT  # noqa: E402
from catalog.api.main import create_app  # noqa: E402


def test_committed_openapi_matches_the_app():
    assert _DEFAULT_OUT.is_file(), f"missing generated schema {_DEFAULT_OUT}"
    committed = json.loads(_DEFAULT_OUT.read_text())
    assert committed == create_app().openapi(), (
        f"{Path(_DEFAULT_OUT).name} is stale against schemas.py / the routes. "
        "Run `pixi run gen-frontend-types` and commit openapi.json + "
        "src/types.gen.ts."
    )
