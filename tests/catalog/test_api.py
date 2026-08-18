import time
import pytest
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from schema import (
    Acquisition,
    AcquisitionFile,
    Annotation,
    Chromatin,
    Fiducial,
    Label,
    PostProcessedTomogram,
    Sample,
    SampleRecord,
)
from schema.schema import DataSource, Project
from schema.loader import ExtrasEntry
from catalog import db, orm
from catalog.persistence import upsert_sample_record
from catalog.api.main import create_app
from catalog.api.deps import get_session
from catalog.api.routes.samples import _file_formats


@pytest.fixture
def client(tmp_path):
    # Use a temp-file SQLite (not :memory:) so multiple connections share state.
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    app = create_app()
    # Bypass lifespan engine setup — store directly
    app.state.engine = engine

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    # Seed
    s = Session()
    try:
        # sample_a — full with everything
        tomo = PostProcessedTomogram(
            id="t1",
            voxel_size=11.72,
            reconstruction_alignment_id="align1",
            mrc_path="align1/t1.mrc",
            zarr_path="align1/t1.zarr",
        )
        ann = Annotation(
            id="a1",
            files=["x.mrc", "x.json"],
            reconstruction_alignment_id="align1",
        )
        acq = AcquisitionFile(
            acquisition=Acquisition(acquisition_id="acq1"),
            post_processed_tomogram=[tomo],
            annotation=[ann],
        )
        rec_a = SampleRecord(
            sample=Sample(
                sample_id="sample_a",
                data_source=DataSource.experimental,
                project=Project.chromatin,
                description="A",
            ),
            chromatin=Chromatin(buffer="HEPES"),
            fiducial=Fiducial(vendor="Aurion", aunp_size_nm=10.0),
            label=[Label(label_target="actin", aunp_size_nm=5.0)],
            acquisitions={"acq1": acq},
        )
        upsert_sample_record(
            s,
            rec_a,
            extras=[
                ExtrasEntry(
                    entity_type="sample",
                    entity_pk=("sample_a",),
                    key="weird",
                    value="value",
                ),
                ExtrasEntry(
                    entity_type="chromatin",
                    entity_pk=("sample_a",),
                    key="weird",
                    value=1,
                ),
            ],
            run_id="run-A",
            now=time.time(),
        )
        # One outstanding issue for sample_a (current state; resolved_at NULL).
        s.add(orm.IssueORM(
            fingerprint="fp-a-1",
            severity="warning",
            scope="sample",
            sample_id="sample_a",
            file_kind="sample_toml",
            location="sample",
            category="extra_field",
            message="extra field 'weird'",
            first_seen_at=time.time(),
            first_seen_run_id="run-A",
            last_seen_at=time.time(),
            last_seen_run_id="run-A",
        ))

        # sample_b — minimal (nanogold has no data_source constraint, so it can
        # be a simulation sample, unlike synapse)
        rec_b = SampleRecord(
            sample=Sample(
                sample_id="sample_b",
                data_source=DataSource.simulation,
                project=Project.nanogold,
            )
        )
        upsert_sample_record(
            s, rec_b, extras=[], run_id="run-A", now=time.time()
        )

        # sample_c — soft-deleted (filter test)
        rec_c = SampleRecord(
            sample=Sample(
                sample_id="sample_c",
                data_source=DataSource.experimental,
                project=Project.chromatin,
            )
        )
        upsert_sample_record(
            s, rec_c, extras=[], run_id="run-A", now=time.time()
        )
        from sqlalchemy import update as sa_update
        s.execute(
            sa_update(orm.SampleORM)
            .where(orm.SampleORM.sample_id == "sample_c")
            .values(deleted_at=time.time())
        )

        # scan_runs rows (new model; /manage/scans coverage lives in
        # test_api_manage.py — these just exercise the shared engine seeding).
        s.add(orm.ScanRunORM(
            scan_run_id="run-A", started_at=time.time()-100, ended_at=time.time()-50,
            root="/data", status="completed",
            n_upserted=2, n_skipped=0, n_failed=0,
        ))
        s.add(orm.ScanRunORM(
            scan_run_id="run-B", started_at=time.time()-10, ended_at=None,
            root="/data", status="running",
        ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


# ── _file_formats ────────────────────────────────────────
def test_file_formats_dedupes_and_uppercases():
    assert _file_formats("a/b.mrc", "a/b.zarr", "a/b.mrc") == ["MRC", "ZARR"]


def test_file_formats_skips_none_and_empty():
    assert _file_formats(None, "", "a/b.star") == ["STAR"]


def test_file_formats_all_none():
    assert _file_formats(None, None) == []


# ── /samples ──────────────────────────────────────────────
def test_list_samples_excludes_soft_deleted(client):
    r = client.get("/samples")
    assert r.status_code == 200
    ids = {s["sample_id"] for s in r.json()}
    assert ids == {"sample_a", "sample_b"}
    assert "sample_c" not in ids


def test_list_samples_filter_project(client):
    r = client.get("/samples", params={"project": "chromatin"})
    assert r.status_code == 200
    assert {s["sample_id"] for s in r.json()} == {"sample_a"}


def test_list_samples_filter_data_source(client):
    r = client.get("/samples", params={"data_source": "simulation"})
    assert {s["sample_id"] for s in r.json()} == {"sample_b"}


def test_list_samples_includes_warning_count(client):
    r = client.get("/samples")
    by_id = {s["sample_id"]: s for s in r.json()}
    assert by_id["sample_a"]["warning_count"] == 1
    assert by_id["sample_b"]["warning_count"] == 0


def test_list_samples_includes_child_counts(client):
    """sample_a is seeded with 1 acquisition, 1 (post-processed) tomogram, 0 tilt_series."""
    r = client.get("/samples")
    by_id = {s["sample_id"]: s for s in r.json()}
    assert by_id["sample_a"]["n_acquisitions"] == 1
    assert by_id["sample_a"]["n_tomograms"] == 1
    assert by_id["sample_a"]["n_tilt_series"] == 0
    assert by_id["sample_b"]["n_acquisitions"] == 0
    assert by_id["sample_b"]["n_tomograms"] == 0
    assert by_id["sample_b"]["n_tilt_series"] == 0


def test_list_samples_pagination(client):
    r = client.get("/samples", params={"limit": 1, "offset": 0})
    assert len(r.json()) == 1
    r2 = client.get("/samples", params={"limit": 1, "offset": 1})
    assert len(r2.json()) == 1
    assert r.json()[0]["sample_id"] != r2.json()[0]["sample_id"]


# ── /samples/{id} ─────────────────────────────────────────
def test_get_sample_detail(client):
    r = client.get("/samples/sample_a")
    assert r.status_code == 200
    body = r.json()
    assert body["sample_id"] == "sample_a"
    assert body["chromatin"] is not None
    assert body["chromatin"]["buffer"] == "HEPES"
    assert body["fiducial"] is not None
    assert body["fiducial"]["vendor"] == "Aurion"
    assert body["label"][0]["label_target"] == "actin"
    assert body["label"][0]["aunp_size_nm"] == 5.0
    assert len(body["acquisitions"]) == 1
    acq = body["acquisitions"][0]
    assert acq["acquisition_id"] == "acq1"
    assert acq["raw_tomograms"] == []
    assert len(acq["post_processed_tomograms"]) == 1
    assert acq["post_processed_tomograms"][0]["voxel_size"] == pytest.approx(11.72)
    assert acq["post_processed_tomograms"][0]["file_formats"] == ["MRC", "ZARR"]
    assert acq["annotations"][0]["file_formats"] == ["MRC", "JSON"]


def test_get_sample_detail_never_exposes_renamed_from(client):
    """§08c: ``renamed_from`` is a scan-time directive, never stored/served —
    spot-check the API response schema doesn't leak it even though the
    underlying Pydantic models carry the field."""
    body = client.get("/samples/sample_a").json()
    assert "renamed_from" not in body
    assert len(body["acquisitions"]) == 1
    acq = body["acquisitions"][0]
    assert "renamed_from" not in acq
    assert "renamed_from" not in acq["post_processed_tomograms"][0]


def test_get_sample_404(client):
    r = client.get("/samples/missing")
    assert r.status_code == 404


def test_get_sample_soft_deleted_404(client):
    r = client.get("/samples/sample_c")
    assert r.status_code == 404


# ── /samples/{id}/warnings ────────────────────────────────
def test_warnings_for_sample(client):
    r = client.get("/samples/sample_a/warnings")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["category"] == "extra_field"
    assert body[0]["scan_run_id"] == "run-A"


def test_warnings_for_soft_deleted_404(client):
    r = client.get("/samples/sample_c/warnings")
    assert r.status_code == 404


# ── /samples/{id} scan_status block (LEFT JOIN; §4.6) ─────────────────────
def test_sample_detail_scan_status_null_when_not_rescanned(client):
    """A not-yet-rescanned sample/acquisition returns null scan_status blocks
    (LEFT JOIN against the side tables)."""
    body = client.get("/samples/sample_a").json()
    assert body["scan_status"] is None
    assert body["acquisitions"][0]["scan_status"] is None


def test_sample_detail_scan_status_present_when_rescanned(client):
    """Seeding sample_scan_status + acquisition_scan_status surfaces the
    scan_status blocks on the detail payload."""
    # Reach the shared engine via the session override.
    gen = client.app.dependency_overrides[get_session]()
    s = next(gen)
    try:
        s.add(orm.SampleScanStatusORM(
            sample_id="sample_a", last_scanned_at=111.0, last_changed_at=100.0,
            last_outcome="upserted", last_scan_run_id="run-A",
        ))
        s.add(orm.AcquisitionScanStatusORM(
            sample_id="sample_a", acquisition_id="acq1",
            last_scanned_at=111.0, last_changed_at=100.0,
            last_outcome="upserted", last_scan_run_id="run-A",
            thumbnail_path="sample_a/acq1.png", thumbnail_source_kind="frames",
            thumbnail_source_path="/data/Frames", thumbnail_generated_at=100.0,
            thumbnail_status="ok",
        ))
        s.commit()
    finally:
        gen.close()

    body = client.get("/samples/sample_a").json()
    assert body["scan_status"]["last_outcome"] == "upserted"
    assert body["scan_status"]["last_scanned_at"] == 111.0
    assert body["scan_status"]["last_changed_at"] == 100.0
    acq_status = body["acquisitions"][0]["scan_status"]
    assert acq_status["thumbnail_status"] == "ok"
    assert acq_status["thumbnail_source_kind"] == "frames"
    assert acq_status["thumbnail_source_path"] == "/data/Frames"


# ── /extras/summary ───────────────────────────────────────
def test_extras_summary(client):
    r = client.get("/extras/summary")
    assert r.status_code == 200
    body = r.json()
    # Two rows: sample/weird × 1, chromatin/weird × 1
    assert {(row["entity_type"], row["key"], row["count"]) for row in body} == {
        ("sample", "weird", 1), ("chromatin", "weird", 1),
    }


# ── thumbnail_path in /samples list ──────────────────────────────────────────


def _make_client_with_thumbnail(tmp_path, thumbnail_path_value):
    """Helper: build a TestClient seeded with one SampleORM that has a given thumbnail_path."""
    engine = db.make_engine(f"sqlite:///{tmp_path / 'thumb_test.db'}")
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

    from schema.schema import DataSource, Project

    s = Session()
    try:
        rec = SampleRecord(
            sample=Sample(
                sample_id="sample_thumb",
                data_source=DataSource.experimental,
                project=Project.chromatin,
            )
        )
        from catalog.persistence import upsert_sample_record
        upsert_sample_record(
            s, rec, extras=[], run_id="run-thumb", now=time.time(),
            thumbnail_path=thumbnail_path_value,
        )
        s.commit()
    finally:
        s.close()

    return TestClient(app)


def test_list_samples_thumbnail_path_round_trips(tmp_path):
    test_client = _make_client_with_thumbnail(tmp_path, "s/a/t.png")
    r = test_client.get("/samples")
    assert r.status_code == 200
    by_id = {s["sample_id"]: s for s in r.json()}
    assert by_id["sample_thumb"]["thumbnail_path"] == "s/a/t.png"


def test_list_samples_thumbnail_path_null_when_not_set(tmp_path):
    test_client = _make_client_with_thumbnail(tmp_path, None)
    r = test_client.get("/samples")
    assert r.status_code == 200
    by_id = {s["sample_id"]: s for s in r.json()}
    assert by_id["sample_thumb"]["thumbnail_path"] is None
