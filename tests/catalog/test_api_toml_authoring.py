"""Tests for ``POST /toml/{kind}`` (backend-authoritative TOML generation).

Asserts the endpoint seam (ADR-0001): valid -> 200 clean value-only TOML +
Content-Disposition; invalid -> 422 field errors; empties omitted; extras
preserved; unknown kind -> 404; id omitted from md_run output.
"""

from __future__ import annotations

import tomllib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

pytest.importorskip("tomli_w")

from catalog import db, orm  # noqa: E402
from catalog.api.deps import get_session  # noqa: E402
from catalog.api.main import create_app  # noqa: E402
from schema.schema import DataSource, Project  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def seeded_client(tmp_path):
    """Client with a DB holding one md_run, for the pull-from-API load seam."""
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    try:
        s.add(
            orm.SampleORM(
                sample_id="samp1",
                data_source=DataSource.simulation,
                project=Project.chromatin,
            )
        )
        s.add(orm.MdRunORM(sample_id="samp1", md_run_id="run01", seed=42, timestep=2.0))
        s.commit()
    finally:
        s.close()

    app = create_app()
    app.state.engine = engine

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    return TestClient(app)


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


# ── Seed mode: upload (parse) ───────────────────────────────────────────────


def test_parse_populates_fields(client):
    resp = client.post(
        "/toml/md_run/parse", json={"toml": "seed = 42\ntimestep = 2.0\n"}
    )
    assert resp.status_code == 200
    assert resp.json()["fields"] == {"seed": 42, "timestep": 2.0}


def test_parse_bad_toml_returns_422(client):
    resp = client.post("/toml/md_run/parse", json={"toml": "this is = = not toml"})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["type"] == "toml_parse"


def test_uploaded_extra_survives_round_trip(client):
    # Parse an uploaded file carrying an extra, then generate from the parsed
    # state: the extra must reach the downloaded output (endpoint seam, AC#3).
    parsed = client.post(
        "/toml/md_run/parse",
        json={"toml": 'seed = 1\ncustom_note = "keep me"\n'},
    ).json()["fields"]
    parsed["md_run_id"] = "run01"  # file is id-less; the form supplies it
    out = client.post("/toml/md_run", json=parsed)
    assert out.status_code == 200
    assert tomllib.loads(out.text) == {"seed": 1, "custom_note": "keep me"}


def test_custom_typed_fields_serialize_as_their_type(client):
    # A boolean/number custom field serializes as that TOML type (AC#4).
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "run01", "is_final": True, "replicate": 3},
    )
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed == {"is_final": True, "replicate": 3}
    assert isinstance(parsed["is_final"], bool)
    assert isinstance(parsed["replicate"], int)


# ── Seed mode: pull-from-API (load) ─────────────────────────────────────────


def test_load_by_id_returns_fields(seeded_client):
    resp = seeded_client.get("/toml/md_run/load/run01")
    assert resp.status_code == 200
    assert resp.json()["fields"] == {"md_run_id": "run01", "seed": 42, "timestep": 2.0}


def test_load_unknown_id_returns_404(seeded_client):
    assert seeded_client.get("/toml/md_run/load/nope").status_code == 404


def test_load_unsupported_kind_returns_404(seeded_client):
    assert seeded_client.get("/toml/sample/load/x").status_code == 404
