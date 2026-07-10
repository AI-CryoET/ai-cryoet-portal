"""Tests for ``POST /toml/sample`` and ``GET /toml/sample/load`` (issue 04).

Covers the composite-form seam: nested per-section TOML, clean value-only
output with directory-derived keys (sample_id / data_source) dropped, native
list + date serialization, the synapse invariants enforced at the model level
(ADR-0003), extras preserved, and pull-from-API load shaped per-section.
"""

from __future__ import annotations

import datetime as _dt
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
    """Client over a DB holding one chromatin sample with two labels."""
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    try:
        s.add(
            orm.SampleORM(
                sample_id="samp1",
                data_source=DataSource.experimental,
                project=Project.chromatin,
                lab_name=None,
                description="a sample",
            )
        )
        s.add(orm.ChromatinORM(sample_id="samp1", buffer="2mM MgCl2", linker_pattern=[20, 50]))
        s.add(orm.LabelORM(sample_id="samp1", ordinal=0, label_target="AMPAR"))
        s.add(orm.LabelORM(sample_id="samp1", ordinal=1, label_target="NMDAR"))
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


def test_valid_sample_downloads_clean_nested_toml(client):
    resp = client.post(
        "/toml/sample",
        json={
            "sample": {
                "sample_id": "samp1",  # directory-derived: must not be written
                "data_source": "experimental",  # derived: must not be written
                "project": "chromatin",
                "lab_name": "rosen",
            },
            "chromatin": {"linker_pattern": [20, 50, 20], "buffer": "2mM MgCl2"},
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="sample.toml"'
    assert "#" not in resp.text  # no comments / #:schema pragma
    parsed = tomllib.loads(resp.text)
    assert parsed == {
        "sample": {"project": "chromatin", "lab_name": "rosen"},
        "chromatin": {"linker_pattern": [20, 50, 20], "buffer": "2mM MgCl2"},
    }
    # Identity + derived keys never reach the file.
    assert "sample_id" not in parsed["sample"]
    assert "data_source" not in parsed["sample"]


def test_list_and_date_serialize_correctly(client):
    resp = client.post(
        "/toml/sample",
        json={
            "sample": {"project": "chromatin"},
            "chromatin": {"linker_pattern": [20, 50]},
            "milling": {"date": "2024-01-02", "scheme": "cryo-FIB"},
        },
    )
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed["chromatin"]["linker_pattern"] == [20, 50]
    # Native TOML date literal (not a quoted string).
    assert parsed["milling"]["date"] == _dt.date(2024, 1, 2)
    assert isinstance(parsed["milling"]["date"], _dt.date)


def test_repeatable_labels_round_trip(client):
    resp = client.post(
        "/toml/sample",
        json={
            "sample": {"project": "nanogold"},
            "label": [
                {"label_target": "AMPAR", "aunp_size_nm": [1.4, 2.2]},
                {"label_target": "NMDAR", "aunp_size_nm": 1.4},
            ],
        },
    )
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed["label"] == [
        {"label_target": "AMPAR", "aunp_size_nm": [1.4, 2.2]},
        {"label_target": "NMDAR", "aunp_size_nm": 1.4},
    ]


def test_missing_required_project_returns_422(client):
    resp = client.post("/toml/sample", json={"sample": {}})
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    # Error locates the nested field so the form maps it to sample.project.
    assert ["sample", "project"] in [e["loc"] for e in errors]


def test_invalid_enum_returns_422(client):
    resp = client.post("/toml/sample", json={"sample": {"project": "not_a_project"}})
    assert resp.status_code == 422
    assert any(e["loc"][-1] == "project" for e in resp.json()["errors"])


def test_synapse_with_chromatin_block_rejected(client):
    resp = client.post(
        "/toml/sample",
        json={"sample": {"project": "synapse"}, "chromatin": {"buffer": "x"}},
    )
    assert resp.status_code == 422


def test_synapse_with_simulation_block_rejected(client):
    # ADR-0003: synapse data is never simulation-derived.
    resp = client.post(
        "/toml/sample",
        json={"sample": {"project": "synapse"}, "simulation": {"dataset_type": "bulk"}},
    )
    assert resp.status_code == 422


def test_section_extra_preserved(client):
    resp = client.post(
        "/toml/sample",
        json={
            "sample": {"project": "chromatin"},
            "chromatin": {"buffer": "x", "ionic_strength_mM": 154.0},
        },
    )
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed["chromatin"]["ionic_strength_mM"] == 154.0


def test_load_sample_by_id_returns_nested_fields(seeded_client):
    resp = seeded_client.get("/toml/sample/load/samp1")
    assert resp.status_code == 200
    fields = resp.json()["fields"]
    assert fields["sample"]["project"] == "chromatin"
    assert fields["sample"]["data_source"] == "experimental"  # for arm lock
    assert fields["sample"]["sample_id"] == "samp1"  # placement hint
    assert fields["chromatin"] == {"buffer": "2mM MgCl2", "linker_pattern": [20, 50]}
    assert [lbl["label_target"] for lbl in fields["label"]] == ["AMPAR", "NMDAR"]


def test_load_unknown_sample_returns_404(seeded_client):
    assert seeded_client.get("/toml/sample/load/nope").status_code == 404
