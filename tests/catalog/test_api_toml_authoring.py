"""Tests for ``POST /toml/{kind}`` (backend-authoritative TOML generation).

Asserts the endpoint seam (ADR-0001): valid -> 200 clean value-only TOML +
Content-Disposition; invalid -> 422 field errors; empties omitted; extras
preserved; unknown kind -> 404; id omitted from md_run output.
"""

from __future__ import annotations

import tomllib

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("tomli_w")

from catalog.api.main import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())


def test_valid_md_run_downloads_clean_toml(client):
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "run01", "seed": 42, "timestep": 2.0},
    )
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="md_run.toml"'
    body = resp.text
    # Clean value-only: no comments, no #:schema pragma.
    assert "#" not in body
    parsed = tomllib.loads(body)
    # Directory-derived id is not written into the file.
    assert "id" not in parsed and "md_run_id" not in parsed
    assert parsed == {"seed": 42, "timestep": 2.0}


def test_empty_optional_fields_omitted(client):
    resp = client.post("/toml/md_run", json={"md_run_id": "run01", "seed": 7})
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed == {"seed": 7}  # unfilled optionals absent, not null/empty


def test_invalid_input_returns_422_with_field_errors(client):
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "bad id with spaces", "seed": "not-an-int"},
    )
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    located = {e["loc"][-1] for e in errors}
    assert "md_run_id" in located
    assert "seed" in located
    # Errors are JSON-serializable (loc/msg/type only).
    for e in errors:
        assert set(e) >= {"loc", "msg", "type"}


def test_missing_required_id_returns_422(client):
    resp = client.post("/toml/md_run", json={"seed": 1})
    assert resp.status_code == 422
    located = {e["loc"][-1] for e in resp.json()["errors"]}
    assert "md_run_id" in located


def test_extra_fields_preserved(client):
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "run01", "custom_note": "hello"},
    )
    assert resp.status_code == 200
    assert tomllib.loads(resp.text) == {"custom_note": "hello"}


def test_non_toml_serializable_extra_returns_422_not_500(client):
    # extra="allow" lets a nested null through validation; it must not crash
    # tomli_w into a 500 (ADR-0001: endpoint is status-discriminated).
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "run01", "weird": {"k": None}},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["type"] == "toml_serialization"


def test_unknown_kind_returns_404(client):
    resp = client.post("/toml/not_a_kind", json={"md_run_id": "x"})
    assert resp.status_code == 404
