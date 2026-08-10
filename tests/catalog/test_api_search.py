"""ID search over the sample hierarchy (GET /samples?q=...)."""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from schema import (
    Acquisition,
    AcquisitionFile,
    Annotation,
    PostProcessedTomogram,
    Sample,
    SampleRecord,
)
from schema.schema import DataSource, Project
from catalog import db, orm
from catalog.persistence import upsert_sample_record
from catalog.api.deps import get_session
from catalog.api.main import create_app


@pytest.fixture
def client(tmp_path):
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    app = create_app()
    app.state.engine = engine

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    s = Session()
    try:
        acq = AcquisitionFile(
            acquisition=Acquisition(acquisition_id="acq-100"),
            post_processed_tomogram=[
                PostProcessedTomogram(
                    id="tomo-777", reconstruction_alignment_id="align1"
                )
            ],
            annotation=[
                Annotation(
                    id="annot-999",
                    files=["x.mrc"],
                    reconstruction_alignment_id="align1",
                )
            ],
        )
        rec = SampleRecord(
            sample=Sample(
                sample_id="smp-alpha",
                data_source=DataSource.experimental,
                project=Project.chromatin,
                description="quickbrownfox marker",
            ),
            acquisitions={"acq-100": acq},
        )
        upsert_sample_record(s, rec, extras=[], run_id="run-1", now=time.time())
        # A second sample with none of the search tokens, to prove filtering.
        upsert_sample_record(
            s,
            SampleRecord(
                sample=Sample(
                    sample_id="smp-beta",
                    data_source=DataSource.simulation,
                    project=Project.nanogold,
                )
            ),
            extras=[],
            run_id="run-1",
            now=time.time(),
        )
        s.commit()
    finally:
        s.close()
    return TestClient(app)


def _by_id(resp):
    return {s["sample_id"]: s for s in resp.json()}


def test_q_matches_tomogram_id_surfaces_sample_and_acquisition(client):
    r = client.get("/samples", params={"q": "tomo-777"})
    assert r.status_code == 200
    samples = _by_id(r)
    assert set(samples) == {"smp-alpha"}
    tomo = [m for m in samples["smp-alpha"]["matches"] if m["kind"] == "tomogram"]
    assert tomo == [
        {"kind": "tomogram", "acquisition_id": "acq-100", "matched_id": "tomo-777"}
    ]


def test_q_matches_annotation_id(client):
    samples = _by_id(client.get("/samples", params={"q": "annot-999"}))
    assert set(samples) == {"smp-alpha"}
    assert any(m["kind"] == "annotation" for m in samples["smp-alpha"]["matches"])


def test_q_matches_acquisition_id(client):
    samples = _by_id(client.get("/samples", params={"q": "acq-100"}))
    assert set(samples) == {"smp-alpha"}
    assert any(m["kind"] == "acquisition" for m in samples["smp-alpha"]["matches"])


def test_q_matches_sample_id_with_null_acquisition(client):
    samples = _by_id(client.get("/samples", params={"q": "smp-alpha"}))
    assert set(samples) == {"smp-alpha"}
    assert {
        "kind": "sample",
        "acquisition_id": None,
        "matched_id": "smp-alpha",
    } in samples["smp-alpha"]["matches"]


def test_q_is_case_insensitive(client):
    assert set(_by_id(client.get("/samples", params={"q": "TOMO-777"}))) == {
        "smp-alpha"
    }


def test_q_no_match_returns_empty(client):
    assert client.get("/samples", params={"q": "no-such-id"}).json() == []


def test_q_does_not_match_description(client):
    # 'quickbrownfox' is only in smp-alpha.description — IDs-only search ignores it.
    assert client.get("/samples", params={"q": "quickbrownfox"}).json() == []


def test_matches_absent_without_q(client):
    samples = _by_id(client.get("/samples"))
    assert samples["smp-alpha"]["matches"] == []
    assert samples["smp-beta"]["matches"] == []


def test_q_underscore_is_escaped_not_wildcard(client):
    # '_' is a LIKE single-char wildcard; a literal underscore in a pasted id
    # must be matched literally, not treated as "any one character". smp-alpha
    # has a hyphen at that position, so a search for "smp_alpha" (underscore)
    # must NOT match it.
    assert client.get("/samples", params={"q": "smp_alpha"}).json() == []


def test_q_composes_with_registry_filter_as_and(client):
    # q="smp-alpha" matches smp-alpha but not smp-beta; project=nanogold
    # matches smp-beta but not smp-alpha. The two conditions AND together, so
    # no sample satisfies both -> empty result.
    r = client.get("/samples", params={"q": "smp-alpha", "project": "nanogold"})
    assert r.status_code == 200
    assert r.json() == []
