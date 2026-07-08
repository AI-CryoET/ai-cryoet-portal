"""ORM round-trip smoke for the scan data model (plan §8).

Pins that ``init_schema`` materializes the scan-run-history + current-state
tables (safe to run twice), and that each ORM class round-trips through the
DB.
"""
from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from catalog import db, orm  # noqa: E402
from schema.schema import DataSource, Project  # noqa: E402


def _engine(tmp_path, name="cat.db"):
    return db.make_engine(f"sqlite:///{tmp_path / name}")


def test_init_schema_idempotent_twice(tmp_path):
    engine = _engine(tmp_path)
    db.init_schema(engine)
    before = set(inspect(engine).get_table_names())
    db.init_schema(engine)  # safe to run again
    assert set(inspect(engine).get_table_names()) == before


def test_scan_data_model_round_trip(tmp_path):
    engine = _engine(tmp_path)
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    try:
        s.add(orm.SampleORM(
            sample_id="s1", data_source=DataSource.experimental,
            project=Project.chromatin,
        ))
        s.add(orm.ScanRunORM(
            scan_run_id="run-1", started_at=1.0, ended_at=2.0,
            status="completed", root="/data",
            n_upserted=1, n_skipped=0, n_failed=0,
            n_new_issues=1, n_resolved_issues=0,
            n_warning_active=1, n_error_active=0,
        ))
        s.add(orm.ScanLogLineORM(
            scan_run_id="run-1", seq=1, ts=1.5, level="INFO",
            sample_id="s1", message="hello",
        ))
        s.add(orm.ScanSampleOutcomeORM(
            scan_run_id="run-1", sample_id="s1", outcome="upserted",
        ))
        s.add(orm.IssueORM(
            fingerprint="fp1", severity="warning", scope="sample",
            sample_id="s1", file_kind="sample_toml", location="loc",
            category="cat", message="m", first_seen_at=1.0,
            first_seen_run_id="run-1", last_seen_at=1.0, last_seen_run_id="run-1",
        ))
        s.add(orm.SampleScanStatusORM(
            sample_id="s1", last_scanned_at=1.0, last_changed_at=1.0,
            last_outcome="upserted", last_scan_run_id="run-1",
        ))
        s.add(orm.AcquisitionScanStatusORM(
            sample_id="s1", acquisition_id="acq1", last_scanned_at=1.0,
            last_changed_at=1.0, last_outcome="upserted", last_scan_run_id="run-1",
            thumbnail_path="s1/acq1.png", thumbnail_source_kind="frames",
            thumbnail_source_path="/data/Frames", thumbnail_generated_at=1.0,
            thumbnail_status="ok",
        ))
        s.commit()
    finally:
        s.close()

    s = Session()
    try:
        assert s.get(orm.ScanRunORM, "run-1").status == "completed"
        assert s.get(orm.ScanSampleOutcomeORM, 1).outcome == "upserted"
        issue = s.get(orm.IssueORM, 1)
        assert issue.fingerprint == "fp1" and issue.resolved_at is None
        assert s.get(orm.SampleScanStatusORM, "s1").last_outcome == "upserted"
        acq = s.get(orm.AcquisitionScanStatusORM, ("s1", "acq1"))
        assert acq.thumbnail_status == "ok"
        assert acq.thumbnail_source_kind == "frames"
        log = s.get(orm.ScanLogLineORM, 1)
        assert log.sample_id == "s1" and log.level == "INFO"
    finally:
        s.close()


def test_issue_fingerprint_unique(tmp_path):
    """The ``issues.fingerprint`` column is globally UNIQUE."""
    from sqlalchemy.exc import IntegrityError

    engine = _engine(tmp_path)
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        common = dict(
            severity="warning", scope="sample", sample_id="s1",
            file_kind="sample_toml", location="loc", category="cat",
            message="m", first_seen_at=1.0, first_seen_run_id="r",
            last_seen_at=1.0, last_seen_run_id="r",
        )
        s.add(orm.IssueORM(fingerprint="dup", **common))
        s.add(orm.IssueORM(fingerprint="dup", **common))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.close()
