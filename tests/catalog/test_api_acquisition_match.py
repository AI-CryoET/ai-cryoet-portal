"""Shared-fixture consumer test: the backend acquisition predicate must agree
with every case in ``tests/fixtures/acquisition_match_cases.json``.

The same JSON file is consumed by the Phase 6 TS ``matchAcquisition`` vitest so
the two implementations are pinned to identical cases and can't silently drift.

Fixture case shape (language-neutral JSON — comments live here, not in the file):
    name      human label for the case
    acq       an AcquisitionOut-shaped dict. Scalar keys (microscope,
              resolution, phase_plate, …) map to AcquisitionORM columns.
              Nested keys map to per-acquisition child rows:
                tilt_series                list[ {is_aligned, zarr_path, …} ]
                raw_tomograms              list[ {tomogram_id, zarr_path, …} ]
                post_processed_tomograms   list[ {tomogram_id, zarr_path, …} ]
                annotations                list[ {annotation_id, type, …} ]
    filters   dict of registry param -> value(s) exactly as the URL would carry
              them: text/annotation_type -> list[str], {key}_min/{key}_max for
              ranges, "true"/"false" for boolean/existence checkboxes.
    expected  true  => the seeded sample IS returned by GET /samples?<filters>
              false => it is NOT (the single acquisition fails the predicate).

Each case seeds exactly one sample with exactly one acquisition, so a returned
sample proves the acquisition EXISTS predicate matched that acquisition.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from catalog import db, orm
from catalog.api.deps import get_session
from catalog.api.main import create_app
from schema.schema import DataSource, Project

_CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "acquisition_match_cases.json").read_text()
)

_SAMPLE_ID = "sample_x"
_ACQ_ID = "acq1"

# AcquisitionOut nested children -> not AcquisitionORM scalar columns.
_NESTED = {"tilt_series", "raw_tomograms", "post_processed_tomograms", "annotations"}


@pytest.fixture
def make_client(tmp_path):
    """Returns a factory that seeds one sample+acquisition from an ``acq`` dict
    and yields a TestClient against it."""
    def _factory(acq: dict) -> TestClient:
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
            s.add(
                orm.SampleORM(
                    sample_id=_SAMPLE_ID,
                    data_source=DataSource.experimental,
                    project=Project.chromatin,
                )
            )
            acq_scalars = {k: v for k, v in acq.items() if k not in _NESTED}
            s.add(
                orm.AcquisitionORM(
                    sample_id=_SAMPLE_ID, acquisition_id=_ACQ_ID, **acq_scalars
                )
            )

            for i, ts in enumerate(acq.get("tilt_series") or []):
                s.add(
                    orm.TiltSeriesORM(
                        sample_id=_SAMPLE_ID,
                        acquisition_id=_ACQ_ID,
                        tilt_series_id=f"ts{i}",
                        is_aligned=ts.get("is_aligned"),
                        zarr_path=ts.get("zarr_path"),
                    )
                )

            for i, raw in enumerate(acq.get("raw_tomograms") or []):
                s.add(
                    orm.RawTomogramORM(
                        sample_id=_SAMPLE_ID,
                        acquisition_id=_ACQ_ID,
                        reconstruction_alignment_id=raw.get(
                            "reconstruction_alignment_id", "align1"
                        ),
                        tomogram_id=raw.get("tomogram_id", f"r{i}"),
                        zarr_path=raw.get("zarr_path"),
                    )
                )

            for i, p in enumerate(acq.get("post_processed_tomograms") or []):
                s.add(
                    orm.PostProcessedTomogramORM(
                        sample_id=_SAMPLE_ID,
                        acquisition_id=_ACQ_ID,
                        reconstruction_alignment_id=p.get(
                            "reconstruction_alignment_id", "align1"
                        ),
                        tomogram_id=p.get("tomogram_id", f"p{i}"),
                        derived_from=[],
                        zarr_path=p.get("zarr_path"),
                    )
                )

            for i, ann in enumerate(acq.get("annotations") or []):
                s.add(
                    orm.AnnotationORM(
                        sample_id=_SAMPLE_ID,
                        acquisition_id=_ACQ_ID,
                        reconstruction_alignment_id=ann.get(
                            "reconstruction_alignment_id", "align1"
                        ),
                        annotation_id=ann.get("annotation_id", f"a{i}"),
                        type=ann.get("type"),
                        files=[],
                    )
                )

            s.commit()
        finally:
            s.close()

        return TestClient(app)

    return _factory


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_acquisition_predicate_matches_fixture(make_client, case):
    client = make_client(case["acq"])
    params = []
    for key, val in case["filters"].items():
        if isinstance(val, list):
            params.extend((key, v) for v in val)
        else:
            params.append((key, val))
    ids = {s["sample_id"] for s in client.get("/samples", params=params).json()}
    returned = _SAMPLE_ID in ids
    assert returned is case["expected"], (
        f"{case['name']}: expected returned={case['expected']}, got {returned}"
    )
