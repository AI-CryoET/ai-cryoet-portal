"""Tests for ``GET /stats/overview`` (plan §7.3)."""
from __future__ import annotations
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from schema.schema import DataSource, Project
from catalog import db, orm
from catalog.api.deps import get_session
from catalog.api.main import create_app


def _make_app(tmp_path):
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
    return app, Session


@pytest.fixture
def seeded_client(tmp_path):
    """Two projects, varied child counts, plus a soft-deleted sample whose
    rows must not contribute. Sizes seeded so per-project byte totals are
    verifiable. Two completed scans seeded to test the most-recent rule."""
    app, Session = _make_app(tmp_path)

    s = Session()
    try:
        # ── chromatin: two live samples ────────────────────────────────
        # chrom_a: 2 acq × (2 tomos + 1 tilt_series + 1 annotation)
        # disk_size_bytes=6000 → chromatin total will be 6000 (chrom_b is NULL/0)
        s.add(orm.SampleORM(
            sample_id="chrom_a", data_source=DataSource.experimental,
            project=Project.chromatin,
            disk_size_bytes=6000,
        ))
        for acq_id in ("acq1", "acq2"):
            s.add(orm.AcquisitionORM(
                sample_id="chrom_a", acquisition_id=acq_id,
            ))
            s.add(orm.PostProcessedTomogramORM(
                sample_id="chrom_a", acquisition_id=acq_id,
                reconstruction_alignment_id="align1", tomogram_id="t1",
                size_bytes=1000,
            ))
            s.add(orm.PostProcessedTomogramORM(
                sample_id="chrom_a", acquisition_id=acq_id,
                reconstruction_alignment_id="align1", tomogram_id="t2",
                size_bytes=2000,
            ))
            s.add(orm.TiltSeriesORM(
                sample_id="chrom_a", acquisition_id=acq_id, tilt_series_id="ts1",
            ))
            s.add(orm.AnnotationORM(
                sample_id="chrom_a", acquisition_id=acq_id,
                reconstruction_alignment_id="align1", annotation_id="a1",
            ))

        # chrom_b: 1 acq × (1 tomo with NULL size_bytes + 0 tilt_series + 0 annotations)
        # disk_size_bytes=None → must coalesce to 0 in by_project size_bytes
        s.add(orm.SampleORM(
            sample_id="chrom_b", data_source=DataSource.experimental,
            project=Project.chromatin,
            disk_size_bytes=None,
        ))
        s.add(orm.AcquisitionORM(
            sample_id="chrom_b", acquisition_id="acq1",
        ))
        s.add(orm.PostProcessedTomogramORM(
            sample_id="chrom_b", acquisition_id="acq1",
            reconstruction_alignment_id="align1", tomogram_id="t1",
            size_bytes=None,  # must coalesce to 0 in by_project size_bytes
        ))

        # ── synapse: two live samples ──────────────────────────────────
        # syn_a: 1 acq × (1 tomo + 2 tilt_series + 1 annotation)
        # disk_size_bytes=5000 → synapse total will be 5000 (syn_b is NULL/0)
        s.add(orm.SampleORM(
            sample_id="syn_a", data_source=DataSource.simulation,
            project=Project.synapse,
            disk_size_bytes=5000,
        ))
        s.add(orm.AcquisitionORM(
            sample_id="syn_a", acquisition_id="acq1",
        ))
        s.add(orm.PostProcessedTomogramORM(
            sample_id="syn_a", acquisition_id="acq1",
            reconstruction_alignment_id="align1", tomogram_id="t1",
            size_bytes=5000,
        ))
        # Same stem "t1"/"a1" in a second alignment group: distinct files on
        # disk, so distinct rows — this is what the group-scoped PK fixes.
        s.add(orm.PostProcessedTomogramORM(
            sample_id="syn_a", acquisition_id="acq1",
            reconstruction_alignment_id="align2", tomogram_id="t1",
            size_bytes=5000,
        ))
        for ts_id in ("ts1", "ts2"):
            s.add(orm.TiltSeriesORM(
                sample_id="syn_a", acquisition_id="acq1", tilt_series_id=ts_id,
            ))
        s.add(orm.AnnotationORM(
            sample_id="syn_a", acquisition_id="acq1",
            reconstruction_alignment_id="align1", annotation_id="a1",
        ))
        s.add(orm.AnnotationORM(
            sample_id="syn_a", acquisition_id="acq1",
            reconstruction_alignment_id="align2", annotation_id="a1",
        ))

        # syn_b: 1 acq, no tomograms / tilt_series / annotations
        # disk_size_bytes=None → contributes 0 to synapse size total
        s.add(orm.SampleORM(
            sample_id="syn_b", data_source=DataSource.simulation,
            project=Project.synapse,
            disk_size_bytes=None,
        ))
        s.add(orm.AcquisitionORM(
            sample_id="syn_b", acquisition_id="acq1",
        ))

        # ── soft-deleted sample whose rows must NOT contribute ─────────
        # disk_size_bytes=99999 → must NOT contribute to chromatin size_bytes
        s.add(orm.SampleORM(
            sample_id="dead", data_source=DataSource.experimental,
            project=Project.chromatin,
            deleted_at=time.time(),
            disk_size_bytes=99999,
        ))
        s.add(orm.AcquisitionORM(
            sample_id="dead", acquisition_id="acq1",
        ))
        s.add(orm.PostProcessedTomogramORM(
            sample_id="dead", acquisition_id="acq1",
            reconstruction_alignment_id="align1", tomogram_id="t1",
            size_bytes=99999,  # must NOT contribute to chromatin size_bytes
        ))
        s.add(orm.TiltSeriesORM(
            sample_id="dead", acquisition_id="acq1", tilt_series_id="ts1",
        ))
        s.add(orm.AnnotationORM(
            sample_id="dead", acquisition_id="acq1",
            reconstruction_alignment_id="align1", annotation_id="a1",
        ))

        # ── issues (current state; totals.warnings = outstanding count) ──
        # 3 outstanding issues (resolved_at IS NULL) → the totals.warnings value.
        for i in range(3):
            s.add(orm.IssueORM(
                fingerprint=f"fp-out-{i}",
                severity="warning", scope="sample", sample_id="syn_a",
                file_kind="sample_toml", location=f"loc{i}",
                category="cat", message=f"outstanding-{i}",
                first_seen_at=time.time() - 100, first_seen_run_id="run-new",
                last_seen_at=time.time() - 50, last_seen_run_id="run-new",
            ))
        # 10 RESOLVED issues — must NOT be counted in totals.warnings.
        for i in range(10):
            s.add(orm.IssueORM(
                fingerprint=f"fp-res-{i}",
                severity="warning", scope="sample", sample_id="chrom_a",
                file_kind="sample_toml", location=f"rloc{i}",
                category="cat", message=f"resolved-{i}",
                first_seen_at=time.time() - 1000, first_seen_run_id="run-old",
                last_seen_at=time.time() - 950, last_seen_run_id="run-old",
                resolved_at=time.time() - 900, resolved_run_id="run-old",
            ))

        s.commit()
    finally:
        s.close()

    return TestClient(app)


@pytest.fixture
def empty_client(tmp_path):
    """No rows at all."""
    app, _ = _make_app(tmp_path)
    return TestClient(app)


# ── totals ──────────────────────────────────────────────────────────────


def test_totals_match_seeded_counts(seeded_client):
    r = seeded_client.get("/stats/overview")
    assert r.status_code == 200
    totals = r.json()["totals"]

    # Live samples: chrom_a, chrom_b, syn_a, syn_b → 4 (dead excluded).
    assert totals["samples"] == 4
    # Live acquisitions: chrom_a×2 + chrom_b×1 + syn_a×1 + syn_b×1 = 5.
    assert totals["acquisitions"] == 5
    # Live tomograms: chrom_a 2*2 + chrom_b 1 + syn_a 2 = 7. syn_a's two
    # rows share the stem "t1" and differ only by alignment group.
    assert totals["tomograms"] == 7
    # Live tilt_series: chrom_a 2 + syn_a 2 = 4.
    assert totals["tilt_series"] == 4
    # Live annotations: chrom_a 2 + syn_a 2 = 4 (syn_a's "a1" in two groups).
    assert totals["annotations"] == 4


def test_totals_warnings_counts_outstanding_issues(seeded_client):
    r = seeded_client.get("/stats/overview")
    totals = r.json()["totals"]
    # 3 outstanding (resolved_at IS NULL); 10 resolved must be ignored.
    assert totals["warnings"] == 3


# ── by_project ──────────────────────────────────────────────────────────


def test_by_project_rows_match_seeded_counts(seeded_client):
    r = seeded_client.get("/stats/overview")
    rows = r.json()["by_project"]

    # Sorted alphabetically by project name.
    assert [row["project"] for row in rows] == ["chromatin", "synapse"]

    chrom = next(row for row in rows if row["project"] == "chromatin")
    # chrom_a + chrom_b → 2 live samples, 3 acquisitions, 5 tomograms.
    assert chrom["samples"] == 2
    assert chrom["acquisitions"] == 3
    assert chrom["tomograms"] == 5
    # size_bytes: SampleORM.disk_size_bytes — chrom_a=6000, chrom_b=NULL(→0),
    # soft-deleted "dead" excluded → 6000.
    assert chrom["size_bytes"] == 6000

    syn = next(row for row in rows if row["project"] == "synapse")
    # syn_a + syn_b → 2 live samples, 2 acquisitions, 2 tomograms (one stem
    # per alignment group), 5000 bytes.
    assert syn["samples"] == 2
    assert syn["acquisitions"] == 2
    assert syn["tomograms"] == 2
    assert syn["size_bytes"] == 5000


def test_soft_deleted_excluded_from_by_project(seeded_client):
    """The soft-deleted sample's disk_size_bytes=99999 must not leak into the
    chromatin size_bytes total."""
    r = seeded_client.get("/stats/overview")
    chrom = next(
        row for row in r.json()["by_project"] if row["project"] == "chromatin"
    )
    assert chrom["size_bytes"] == 6000  # not 6000 + 99999


def test_null_size_bytes_contributes_zero(seeded_client):
    """``chrom_b`` has NULL ``disk_size_bytes``; the project total must include
    it as 0, not None / not error."""
    r = seeded_client.get("/stats/overview")
    chrom = next(
        row for row in r.json()["by_project"] if row["project"] == "chromatin"
    )
    # size_bytes is a plain int.
    assert isinstance(chrom["size_bytes"], int)
    # And matches the strict sum (no None contribution).
    assert chrom["size_bytes"] == 6000


# ── empty edge cases ────────────────────────────────────────────────────


def test_empty_db_returns_zero_totals_and_empty_by_project(empty_client):
    r = empty_client.get("/stats/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"] == {
        "samples": 0, "acquisitions": 0, "tilt_series": 0,
        "tomograms": 0, "annotations": 0, "warnings": 0,
    }
    assert body["by_project"] == []


def test_only_resolved_issues_returns_zero_warnings(tmp_path):
    """Live data + only resolved issues → outstanding warnings total is 0."""
    app, Session = _make_app(tmp_path)
    s = Session()
    try:
        s.add(orm.SampleORM(
            sample_id="x", data_source=DataSource.experimental,
            project=Project.chromatin,
        ))
        # A resolved issue must NOT count toward outstanding warnings.
        s.add(orm.IssueORM(
            fingerprint="fp-resolved",
            severity="warning", scope="sample", sample_id="x",
            file_kind="sample_toml", location="loc", category="cat",
            message="resolved", first_seen_at=time.time() - 100,
            first_seen_run_id="r1", last_seen_at=time.time() - 90,
            last_seen_run_id="r1", resolved_at=time.time() - 50,
            resolved_run_id="r1",
        ))
        s.commit()
    finally:
        s.close()
    client = TestClient(app)
    body = client.get("/stats/overview").json()
    assert body["totals"]["warnings"] == 0
