"""Filter coverage for `GET /samples` (plan §7.1).

Each new query parameter narrows the result set; repeatable categorical
params act as OR within a facet; range filters are NULL-tolerant; aggregate
counts on the SELECT list are filter-independent (decision §11.15).

Fixture seeds five live samples covering a spread of project/data_source/
type/microscope/voltage/camera/pixel_size combinations.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from catalog import db, orm
from catalog.api.deps import get_session
from catalog.api.main import create_app
from schema.schema import DataSource, Project


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

    # ── Seed: five live samples ───────────────────────────────────────────
    # sample_alpha   chromatin/cryoet/lamella   Krios @300kV K3, px=1.0
    #                tomo voxel=10.0, 1 tilt-series
    # sample_beta    chromatin/cryoet/cell      Glacios @200kV Falcon, px=2.5
    #                tomo voxel=20.0, 1 tilt-series
    # sample_gamma   synapse/simulation/lamella Krios @300kV K3, px=1.5
    #                tomo voxel=NULL (NULL-tolerance), 2 tomograms
    #                1 tilt-series
    # sample_delta   chromatin/cryoet/lamella   no acquisitions, no tomograms
    # sample_epsilon synapse/cryoet/cell        Krios @300kV K3, px=NULL
    #                3 tomograms (count-independence test), 1 tilt-series
    s = Session()
    try:
        # samples
        s.add_all([
            orm.SampleORM(
                sample_id="sample_alpha",
                data_source=DataSource.experimental,
                project=Project.chromatin,
                type="lamella",
                description="alpha lamella with chromatin",
            ),
            orm.SampleORM(
                sample_id="sample_beta",
                data_source=DataSource.experimental,
                project=Project.chromatin,
                type="cell",
                description="beta whole cell",
            ),
            orm.SampleORM(
                sample_id="sample_gamma",
                data_source=DataSource.simulation,
                project=Project.synapse,
                type="lamella",
                description="GAMMA synapse simulated",
            ),
            orm.SampleORM(
                sample_id="sample_delta",
                data_source=DataSource.experimental,
                project=Project.chromatin,
                type="lamella",
                description="empty sample",
            ),
            orm.SampleORM(
                sample_id="sample_epsilon",
                data_source=DataSource.experimental,
                project=Project.synapse,
                type="cell",
                description="epsilon cell with three tomograms",
            ),
        ])

        # acquisitions
        s.add_all([
            orm.AcquisitionORM(
                sample_id="sample_alpha", acquisition_id="acq1",
                microscope="Krios", voltage=300.0, camera="K3", pixel_size=1.0,
            ),
            orm.AcquisitionORM(
                sample_id="sample_beta", acquisition_id="acq1",
                microscope="Glacios", voltage=200.0, camera="Falcon", pixel_size=2.5,
            ),
            orm.AcquisitionORM(
                sample_id="sample_gamma", acquisition_id="acq1",
                microscope="Krios", voltage=300.0, camera="K3", pixel_size=1.5,
            ),
            orm.AcquisitionORM(
                sample_id="sample_epsilon", acquisition_id="acq1",
                microscope="Krios", voltage=300.0, camera="K3", pixel_size=None,
            ),
        ])

        # tomograms
        s.add_all([
            orm.PostProcessedTomogramORM(
                sample_id="sample_alpha", acquisition_id="acq1",
                reconstruction_alignment_id="align1", tomogram_id="t1", derived_from=[], voxel_size=10.0,
            ),
            orm.PostProcessedTomogramORM(
                sample_id="sample_beta", acquisition_id="acq1",
                reconstruction_alignment_id="align1", tomogram_id="t1", derived_from=[], voxel_size=20.0,
            ),
            # gamma: two tomograms, both NULL voxel — exercises NULL-tolerance
            orm.PostProcessedTomogramORM(
                sample_id="sample_gamma", acquisition_id="acq1",
                reconstruction_alignment_id="align1", tomogram_id="t1", derived_from=[], voxel_size=None,
            ),
            orm.PostProcessedTomogramORM(
                sample_id="sample_gamma", acquisition_id="acq1",
                reconstruction_alignment_id="align1", tomogram_id="t2", derived_from=[], voxel_size=None,
            ),
            # epsilon: three tomograms, varying voxel spacings — count-independence
            orm.PostProcessedTomogramORM(
                sample_id="sample_epsilon", acquisition_id="acq1",
                reconstruction_alignment_id="align1", tomogram_id="t1", derived_from=[], voxel_size=5.0,
            ),
            orm.PostProcessedTomogramORM(
                sample_id="sample_epsilon", acquisition_id="acq1",
                reconstruction_alignment_id="align1", tomogram_id="t2", derived_from=[], voxel_size=15.0,
            ),
            orm.PostProcessedTomogramORM(
                sample_id="sample_epsilon", acquisition_id="acq1",
                reconstruction_alignment_id="align1", tomogram_id="t3", derived_from=[], voxel_size=25.0,
            ),
        ])

        # tilt-series
        s.add_all([
            orm.TiltSeriesORM(
                sample_id="sample_alpha", acquisition_id="acq1",
                tilt_series_id="ts1",
            ),
            orm.TiltSeriesORM(
                sample_id="sample_beta", acquisition_id="acq1",
                tilt_series_id="ts1",
            ),
            orm.TiltSeriesORM(
                sample_id="sample_gamma", acquisition_id="acq1",
                tilt_series_id="ts1",
            ),
            orm.TiltSeriesORM(
                sample_id="sample_epsilon", acquisition_id="acq1",
                tilt_series_id="ts1",
            ),
        ])

        s.commit()
    finally:
        s.close()

    return TestClient(app)


def _ids(response):
    return {s["sample_id"] for s in response.json()}


# ── Categorical filters ───────────────────────────────────────────────────


def test_filter_project_single(client):
    assert _ids(client.get("/samples", params={"project": "synapse"})) == {
        "sample_gamma", "sample_epsilon",
    }


def test_filter_project_repeatable(client):
    """Multiple ?project= values OR within the facet."""
    r = client.get("/samples", params=[("project", "chromatin"), ("project", "synapse")])
    assert _ids(r) == {
        "sample_alpha", "sample_beta", "sample_gamma", "sample_delta", "sample_epsilon",
    }


def test_filter_data_source_repeatable(client):
    r = client.get(
        "/samples",
        params=[("data_source", "experimental"), ("data_source", "simulation")],
    )
    assert _ids(r) == {
        "sample_alpha", "sample_beta", "sample_gamma", "sample_delta", "sample_epsilon",
    }


def test_filter_type(client):
    assert _ids(client.get("/samples", params={"type": "cell"})) == {
        "sample_beta", "sample_epsilon",
    }


def test_filter_type_repeatable(client):
    r = client.get("/samples", params=[("type", "cell"), ("type", "lamella")])
    assert _ids(r) == {
        "sample_alpha", "sample_beta", "sample_gamma", "sample_delta", "sample_epsilon",
    }


def test_filter_microscope(client):
    assert _ids(client.get("/samples", params={"microscope": "Glacios"})) == {
        "sample_beta",
    }


def test_filter_microscope_repeatable(client):
    r = client.get(
        "/samples", params=[("microscope", "Krios"), ("microscope", "Glacios")]
    )
    assert _ids(r) == {
        "sample_alpha", "sample_beta", "sample_gamma", "sample_epsilon",
    }


def test_filter_voltage(client):
    assert _ids(client.get("/samples", params={"voltage": 200.0})) == {"sample_beta"}


def test_filter_camera_repeatable(client):
    r = client.get("/samples", params=[("camera", "K3"), ("camera", "Falcon")])
    assert _ids(r) == {
        "sample_alpha", "sample_beta", "sample_gamma", "sample_epsilon",
    }


# ── Range filters (pixel_size; voxel range dropped — resolved decision 7) ──


def test_pixel_size_min(client):
    """pixel_size_min=2.0 selects acquisitions with px>=2.0 OR px IS NULL.

    Expected hits:
      sample_beta    (px=2.5)
      sample_epsilon (px=NULL passes)
    """
    assert _ids(client.get("/samples", params={"pixel_size_min": 2.0})) == {
        "sample_beta", "sample_epsilon",
    }


def test_pixel_size_max(client):
    """pixel_size_max=1.5 selects acquisitions with px<=1.5 OR px IS NULL.

    Expected hits:
      sample_alpha   (px=1.0)
      sample_gamma   (px=1.5, exact bound)
      sample_epsilon (px=NULL passes)
    """
    assert _ids(client.get("/samples", params={"pixel_size_max": 1.5})) == {
        "sample_alpha", "sample_gamma", "sample_epsilon",
    }


def test_pixel_size_range_exact_bounds(client):
    r = client.get(
        "/samples", params={"pixel_size_min": 1.5, "pixel_size_max": 2.5},
    )
    # NULL passes both bounds.
    assert _ids(r) == {"sample_beta", "sample_gamma", "sample_epsilon"}


# ── q (search) ─────────────────────────────────────────────────────────────


def test_q_matches_sample_id_case_insensitive(client):
    assert _ids(client.get("/samples", params={"q": "ALPHA"})) == {"sample_alpha"}


def test_q_does_not_match_description_phrase(client):
    """`q` is IDs-only by design (sample/acquisition/tomogram/annotation IDs);
    description text is deliberately not searched.

    'whole cell' appears only in sample_beta's description (not in any
    sample_id/acquisition_id/tomogram_id), so a description-search hit would
    return sample_beta. Since q no longer searches descriptions, it must
    return nothing.
    """
    assert _ids(client.get("/samples", params={"q": "WHOLE CELL"})) == set()


def test_q_does_not_match_description_word(client):
    """Same regression check with a different description-only token.

    'simulated' appears only in sample_gamma's description, not in any ID in
    the fixture, so it must not match now that q is IDs-only.
    """
    assert _ids(client.get("/samples", params={"q": "simulated"})) == set()


# ── Sort + order ──────────────────────────────────────────────────────────


def test_sort_sample_id_asc(client):
    r = client.get("/samples", params={"sort": "sample_id", "order": "asc"})
    ids = [s["sample_id"] for s in r.json()]
    assert ids == sorted(ids)


def test_sort_sample_id_desc(client):
    r = client.get("/samples", params={"sort": "sample_id", "order": "desc"})
    ids = [s["sample_id"] for s in r.json()]
    assert ids == sorted(ids, reverse=True)


def test_sort_project(client):
    r = client.get("/samples", params={"sort": "project", "order": "asc"})
    projects = [s["project"] for s in r.json()]
    assert projects == sorted(projects)


def test_sort_type_desc(client):
    r = client.get("/samples", params={"sort": "type", "order": "desc"})
    types = [s["type"] for s in r.json()]
    # SQLite places NULLs last in DESC mode (per default ordering); we have no
    # NULL types in the fixture so a plain reverse-sort is sufficient.
    assert types == sorted(types, reverse=True)


# ── Aggregate counts are filter-independent (§11.15) ──────────────────────


def test_counts_are_filter_independent(client):
    """sample_epsilon has 3 tomograms regardless of the active range filter."""
    # Narrow to epsilon by combining filters — voxel_spacing_max=15 picks up
    # epsilon (has a t1@5.0 + t2@15.0 child) plus alpha + gamma. But the
    # n_tomograms count for epsilon must still be 3, not the count of
    # matching tomograms.
    r = client.get("/samples", params={"voxel_size_max": 15.0})
    by_id = {s["sample_id"]: s for s in r.json()}
    assert by_id["sample_epsilon"]["n_tomograms"] == 3
    assert by_id["sample_epsilon"]["n_acquisitions"] == 1
    assert by_id["sample_epsilon"]["n_tilt_series"] == 1
    # gamma should also report its full counts:
    assert by_id["sample_gamma"]["n_tomograms"] == 2


def test_counts_present_in_unfiltered_response(client):
    r = client.get("/samples")
    by_id = {s["sample_id"]: s for s in r.json()}
    assert by_id["sample_alpha"]["n_acquisitions"] == 1
    assert by_id["sample_alpha"]["n_tomograms"] == 1
    assert by_id["sample_alpha"]["n_tilt_series"] == 1
    assert by_id["sample_delta"]["n_acquisitions"] == 0
    assert by_id["sample_delta"]["n_tomograms"] == 0
    assert by_id["sample_delta"]["n_tilt_series"] == 0
    assert by_id["sample_epsilon"]["n_tomograms"] == 3
