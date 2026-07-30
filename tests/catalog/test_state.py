"""Unit tests for ``catalog.state`` (mtime gating + scan tracking)."""

from __future__ import annotations

import os
import time

import pytest

# SQLAlchemy + the catalog package both live under the `catalog` feature;
# in the bare `test` env those imports fail. Skip the whole module rather
# than fail collection.
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from catalog import db, orm, state  # noqa: E402
from schema.schema import DataSource, Project  # noqa: E402


@pytest.fixture
def session(tmp_path):
    engine = create_engine("sqlite:///:memory:", future=True)
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    s.add(
        orm.SampleORM(
            sample_id="sample_a",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        )
    )
    s.commit()
    yield s
    s.close()


def test_record_and_load_sample_state(session, tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello")
    state.record_file_scan(session, f, "sample_a", f.stat().st_mtime)
    session.commit()
    loaded = state.load_sample_state(session, "sample_a")
    assert f in loaded
    assert loaded[f][0] == f.stat().st_mtime


def test_is_file_changed(session, tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello")
    mtime = f.stat().st_mtime
    state.record_file_scan(session, f, "sample_a", mtime)
    session.commit()
    s = state.load_sample_state(session, "sample_a")
    assert state.is_file_changed(s, f) is False
    new_mtime = mtime + 10
    os.utime(f, (new_mtime, new_mtime))
    assert state.is_file_changed(s, f) is True


def test_is_file_changed_same_mtime_new_content(session, tmp_path):
    """Content rewritten but mtime reset to the recorded value still counts as
    changed — the mtime-preserving-sync case that stuck stale scan warnings."""
    f = tmp_path / "sample.toml"
    f.write_text("salt_mM = 1\n")
    mtime = f.stat().st_mtime
    state.record_file_scan(session, f, "sample_a", mtime)
    session.commit()
    s = state.load_sample_state(session, "sample_a")
    assert state.is_file_changed(s, f) is False
    # Rewrite content, then reset mtime to the recorded value.
    f.write_text("")
    os.utime(f, (mtime, mtime))
    assert state.is_file_changed(s, f) is True


def test_is_file_changed_null_hash_falls_back_to_mtime(session, tmp_path):
    """A row with no recorded hash (pre-migration / oversized file) gates on
    mtime alone — an unchanged mtime is treated as unchanged."""
    f = tmp_path / "x.txt"
    f.write_text("hello")
    mtime = f.stat().st_mtime
    s = {f: (mtime, None)}
    assert state.is_file_changed(s, f) is False
    f.write_text("changed but same mtime")
    os.utime(f, (mtime, mtime))
    assert state.is_file_changed(s, f) is False  # no hash → can't detect


def test_is_file_changed_missing_path(session, tmp_path):
    """A missing path counts as 'changed' (orchestrator will re-assemble)."""
    s: dict = {}
    assert state.is_file_changed(s, tmp_path / "nope.txt") is True


def test_parse_target_set_changed(session, tmp_path):
    s = {tmp_path / "a": 1.0}
    assert state.parse_target_set_changed(s, [tmp_path / "a"]) is False
    assert state.parse_target_set_changed(s, [tmp_path / "a", tmp_path / "b"]) is True


def test_prune_missing(session, tmp_path):
    a = tmp_path / "a"
    a.write_text("a")
    b = tmp_path / "b"
    b.write_text("b")
    state.record_file_scan(session, a, "sample_a", a.stat().st_mtime)
    state.record_file_scan(session, b, "sample_a", b.stat().st_mtime)
    session.commit()
    n = state.prune_missing(session, "sample_a", kept_paths={a})
    session.commit()
    assert n == 1
    loaded = state.load_sample_state(session, "sample_a")
    assert a in loaded and b not in loaded


def test_prune_missing_noop_when_all_kept(session, tmp_path):
    a = tmp_path / "a"
    a.write_text("a")
    state.record_file_scan(session, a, "sample_a", a.stat().st_mtime)
    session.commit()
    n = state.prune_missing(session, "sample_a", kept_paths={a})
    assert n == 0


def test_load_soft_deleted_ids(session):
    session.add(
        orm.SampleORM(
            sample_id="sample_dead",
            data_source=DataSource.experimental,
            project=Project.chromatin,
            deleted_at=time.time(),
        )
    )
    session.commit()
    ids = state.load_soft_deleted_ids(session)
    assert ids == {"sample_dead"}


def test_start_and_finish_scan(session, tmp_path):
    started_at = state.start_scan(session, "run-1", tmp_path)
    session.commit()
    assert isinstance(started_at, float)
    row = session.get(orm.ScanRunORM, "run-1")
    assert row is not None
    assert row.status == "running"
    assert row.root == str(tmp_path)
    assert row.started_at == started_at
    meta = session.get(orm.CatalogMetaORM, 1)
    assert meta is not None
    assert meta.data_root == str(tmp_path)

    class FakeReport:
        upserted = 5
        skipped = 2
        # finish_scan counts failures from failed_samples (sample_id, detail).
        failed_samples = [("sample_bad", "boom")]
        errors = ["one error"]
        upserted_ids = ["s1", "s2", "s3", "s4", "s5"]
        skipped_ids = ["sk1", "sk2"]

    finished_at = started_at + 50.0
    state.finish_scan(
        session, "run-1", status="completed", report=FakeReport(), now=finished_at
    )
    session.commit()
    row = session.get(orm.ScanRunORM, "run-1")
    assert row.status == "completed"
    assert row.ended_at == finished_at
    assert row.n_upserted == 5
    assert row.n_skipped == 2
    assert row.n_failed == 1


def test_start_scan_returns_started_at_threads_now(session, tmp_path):
    """start_scan returns the run-level ``now`` (== started_at) so the
    orchestrator can thread one timestamp through the whole run (§9.6)."""
    started_at = state.start_scan(session, "run-x", tmp_path)
    session.commit()
    row = session.get(orm.ScanRunORM, "run-x")
    assert row.started_at == started_at


def test_finish_scan_records_sample_outcomes(session, tmp_path):
    """_record_scan_membership writes ScanSampleOutcomeORM rows; failed wins the
    unique (scan_run_id, sample_id) slot over skipped/upserted."""
    started_at = state.start_scan(session, "run-2", tmp_path)
    session.commit()

    class FakeReport:
        upserted = 1
        skipped = 1
        failed_samples = [("ghost", "assemble failed")]
        upserted_ids = ["good"]
        skipped_ids = ["stale"]

    state.finish_scan(
        session, "run-2", status="completed", report=FakeReport(),
        now=started_at + 1,
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.ScanSampleOutcomeORM).where(
                orm.ScanSampleOutcomeORM.scan_run_id == "run-2"
            )
        )
        .scalars()
        .all()
    )
    by_sample = {r.sample_id: r for r in rows}
    assert by_sample["good"].outcome == "upserted"
    assert by_sample["stale"].outcome == "skipped"
    assert by_sample["ghost"].outcome == "failed"
    assert by_sample["ghost"].detail == "assemble failed"


def test_record_file_scan_updates_existing(session, tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello")
    state.record_file_scan(session, f, "sample_a", 100.0)
    session.commit()
    state.record_file_scan(session, f, "sample_a", 200.0)
    session.commit()
    loaded = state.load_sample_state(session, "sample_a")
    assert loaded[f][0] == 200.0
