"""Tests for catalog.persistence.soft_delete_missing_samples (whole-run
sample floor), the §08b child safety floor (ChildPruneSafetyFloorExceeded),
and the §08c ``renamed_from`` hint (suppression/exemption/rename events)."""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from schema import Acquisition, AcquisitionFile, RawTomogram, Sample, SampleRecord
from schema.schema import DataSource, Project

from catalog import db, orm
from catalog.persistence import (
    ChildPruneSafetyFloorExceeded,
    PruneSafetyFloorExceeded,
    RenameContinuity,
    _filter_to_columns,
    soft_delete_missing_samples,
    upsert_sample_record,
    upsert_sample_scan_status,
)

_NOW = 1_700_000_000.0


@pytest.fixture
def session():
    engine = db.make_engine("sqlite:///:memory:")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _seed(session, ids: list[str]) -> None:
    for sid in ids:
        upsert_sample_record(
            session,
            SampleRecord(
                sample=Sample(
                    sample_id=sid,
                    data_source=DataSource.experimental,
                    project=Project.chromatin,
                )
            ),
            extras=[],
            run_id="seed", now=time.time(),
        )
    session.commit()


class FakeReport:
    def __init__(self) -> None:
        self.would_soft_delete: list[str] | None = None
        self.soft_deleted: int = 0


def test_soft_delete_sets_deleted_at(session):
    _seed(session, ["a", "b", "c"])
    soft_delete_missing_samples(
        session, fs_sample_ids={"a", "b"}, run_id="run-1", now=_NOW, safety_floor=1.0
    )
    session.commit()
    assert session.get(orm.SampleORM, "a").deleted_at is None
    assert session.get(orm.SampleORM, "b").deleted_at is None
    c = session.get(orm.SampleORM, "c")
    assert c.deleted_at is not None and c.deleted_at > 0


def test_soft_delete_logs_one_deletion_event_per_sample(session):
    _seed(session, ["a", "b", "c"])
    soft_delete_missing_samples(
        session, fs_sample_ids={"a"}, run_id="run-1", now=_NOW, safety_floor=1.0
    )
    session.commit()

    events = (
        session.execute(select(orm.DeletionEventORM).order_by(orm.DeletionEventORM.sample_id))
        .scalars()
        .all()
    )
    assert [ev.sample_id for ev in events] == ["b", "c"]
    for ev in events:
        assert ev.entity_type == "sample"
        assert ev.scan_run_id == "run-1"
        assert ev.detected_at == _NOW
        assert ev.acquisition_id is None
        assert ev.entity_id is None
        assert ev.last_known_json is not None


def test_dry_run_does_not_log_deletion_events(session):
    _seed(session, ["a", "b"])
    soft_delete_missing_samples(
        session,
        fs_sample_ids={"a"},
        run_id="run-1",
        now=_NOW,
        dry_run=True,
        safety_floor=1.0,
    )
    session.commit()
    assert session.execute(select(orm.DeletionEventORM)).scalars().all() == []


def test_safety_floor_abort_does_not_log_deletion_events(session):
    _seed(session, ["a", "b", "c", "d"])
    with pytest.raises(PruneSafetyFloorExceeded):
        soft_delete_missing_samples(
            session, fs_sample_ids={"a"}, run_id="run-1", now=_NOW, safety_floor=0.5
        )
    assert session.execute(select(orm.DeletionEventORM)).scalars().all() == []


def test_resurrection_clears_deleted_at(session):
    _seed(session, ["a"])
    soft_delete_missing_samples(
        session, fs_sample_ids=set(), run_id="run-1", now=_NOW, safety_floor=1.0
    )
    session.commit()
    assert session.get(orm.SampleORM, "a").deleted_at is not None

    # Re-upsert resurrects.
    _seed(session, ["a"])
    assert session.get(orm.SampleORM, "a").deleted_at is None


def test_safety_floor_aborts(session):
    _seed(session, ["a", "b", "c", "d"])
    # Would soft-delete 3 of 4 = 75% > default 50%.
    with pytest.raises(PruneSafetyFloorExceeded) as excinfo:
        soft_delete_missing_samples(
            session, fs_sample_ids={"a"}, run_id="run-1", now=_NOW, safety_floor=0.5
        )
    assert excinfo.value.ratio > 0.5
    assert excinfo.value.threshold == 0.5
    assert sorted(excinfo.value.missing) == ["b", "c", "d"]
    # No samples were modified.
    rows = (
        session.execute(
            select(orm.SampleORM).where(orm.SampleORM.deleted_at.is_not(None))
        )
        .scalars()
        .all()
    )
    assert rows == []


def test_safety_floor_skipped_on_empty_db(session):
    """No live samples -> skip safety floor (first scan must not fail)."""
    soft_delete_missing_samples(
        session, fs_sample_ids=set(), run_id="run-1", now=_NOW, safety_floor=0.5
    )


def test_dry_run_reports_without_modifying(session):
    _seed(session, ["a", "b"])
    report = FakeReport()
    soft_delete_missing_samples(
        session,
        fs_sample_ids={"a"},
        run_id="run-1",
        now=_NOW,
        dry_run=True,
        safety_floor=1.0,
        report=report,
    )
    session.commit()
    assert report.would_soft_delete == ["b"]
    assert session.get(orm.SampleORM, "b").deleted_at is None


def test_dry_run_still_safety_floor_checks(session):
    _seed(session, ["a", "b", "c", "d"])
    with pytest.raises(PruneSafetyFloorExceeded):
        soft_delete_missing_samples(
            session,
            fs_sample_ids={"a"},
            run_id="run-1",
            now=_NOW,
            dry_run=True,
            safety_floor=0.5,
        )


def test_already_deleted_samples_not_recounted(session):
    _seed(session, ["a", "b", "c"])
    # Pre-mark "a" as soft-deleted.
    session.execute(
        orm.SampleORM.__table__.update()
        .where(orm.SampleORM.sample_id == "a")
        .values(deleted_at=time.time())
    )
    session.commit()
    # fs has b and c — no live samples missing.
    soft_delete_missing_samples(
        session, fs_sample_ids={"b", "c"}, run_id="run-1", now=_NOW, safety_floor=0.5
    )
    session.commit()
    assert session.get(orm.SampleORM, "a").deleted_at is not None
    assert session.get(orm.SampleORM, "b").deleted_at is None
    assert session.get(orm.SampleORM, "c").deleted_at is None


def test_no_op_when_fs_matches_db(session):
    _seed(session, ["a", "b"])
    soft_delete_missing_samples(
        session, fs_sample_ids={"a", "b"}, run_id="run-1", now=_NOW, safety_floor=0.5
    )
    session.commit()
    assert session.get(orm.SampleORM, "a").deleted_at is None
    assert session.get(orm.SampleORM, "b").deleted_at is None


def test_report_soft_deleted_counter_incremented(session):
    _seed(session, ["a", "b", "c"])
    report = FakeReport()
    soft_delete_missing_samples(
        session,
        fs_sample_ids={"a", "b"},
        run_id="run-1",
        now=_NOW,
        safety_floor=1.0,
        report=report,
    )
    session.commit()
    assert report.soft_deleted == 1


def test_dry_run_appends_to_existing_list(session):
    """If report.would_soft_delete is already a list, extend it (not replace)."""
    _seed(session, ["a", "b"])
    report = FakeReport()
    report.would_soft_delete = ["preexisting"]
    soft_delete_missing_samples(
        session,
        fs_sample_ids={"a"},
        run_id="run-1",
        now=_NOW,
        dry_run=True,
        safety_floor=1.0,
        report=report,
    )
    assert report.would_soft_delete == ["preexisting", "b"]


# ─── §08b child safety floor ─────────────────────────────────────────────────


def _record_with_acquisitions(
    sample_id: str, acq_ids: list[str], *, raw_tomo_acq_ids: frozenset = frozenset()
) -> SampleRecord:
    """A sample with one bare acquisition per id in ``acq_ids``; acquisitions
    listed in ``raw_tomo_acq_ids`` additionally carry a raw_tomogram child."""
    acquisitions = {
        aid: AcquisitionFile(
            acquisition=Acquisition(acquisition_id=aid),
            raw_tomogram=(
                RawTomogram(id=f"{aid}_raw") if aid in raw_tomo_acq_ids else None
            ),
        )
        for aid in acq_ids
    }
    return SampleRecord(
        sample=Sample(
            sample_id=sample_id,
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions=acquisitions,
    )


def test_child_floor_trips_at_acquisition_level(session):
    """Dropping 3 of 4 acquisitions (75% > default 50% floor, 4 >= default
    min-count 3) aborts with ChildPruneSafetyFloorExceeded; nothing is
    deleted."""
    r = _record_with_acquisitions("s1", ["a1", "a2", "a3", "a4"])
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    r2 = _record_with_acquisitions("s1", ["a1"])
    with pytest.raises(ChildPruneSafetyFloorExceeded) as excinfo:
        upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW)
    session.rollback()

    exc = excinfo.value
    assert exc.entity_type == "acquisition"
    assert exc.sample_id == "s1"
    assert exc.acquisition_id is None
    assert exc.threshold == 0.5
    assert exc.ratio == pytest.approx(0.75)
    assert len(exc.to_delete) == 3

    # Nothing was actually deleted — the whole upsert rolled back.
    acqs = (
        session.execute(
            select(orm.AcquisitionORM).where(orm.AcquisitionORM.sample_id == "s1")
        )
        .scalars()
        .all()
    )
    assert len(acqs) == 4
    assert session.execute(select(orm.DeletionEventORM)).scalars().all() == []


def test_child_floor_trips_at_child_type_level(session):
    """Acquisitions all survive (no acquisition-level drop) but 3 of 4
    raw_tomogram rows vanish — the raw_tomogram-level floor trips
    independently."""
    acq_ids = ["a1", "a2", "a3", "a4"]
    r = _record_with_acquisitions("s1", acq_ids, raw_tomo_acq_ids=frozenset(acq_ids))
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    # Same 4 acquisitions survive; only a1 keeps its raw_tomogram.
    r2 = _record_with_acquisitions("s1", acq_ids, raw_tomo_acq_ids=frozenset({"a1"}))
    with pytest.raises(ChildPruneSafetyFloorExceeded) as excinfo:
        upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW)
    session.rollback()

    assert excinfo.value.entity_type == "raw_tomogram"
    assert excinfo.value.ratio == pytest.approx(0.75)

    # All 4 acquisitions and all 4 raw_tomogram rows are untouched.
    assert (
        len(session.execute(select(orm.AcquisitionORM)).scalars().all()) == 4
    )
    assert (
        len(session.execute(select(orm.RawTomogramORM)).scalars().all()) == 4
    )


def test_child_floor_does_not_trip_below_min_count(session):
    """Only 2 acquisitions existed (< default min-count 3) — dropping both
    (100%) does NOT trip; it flows through to the 08a feed as normal."""
    r = _record_with_acquisitions("s1", ["a1", "a2"])
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    r2 = _record_with_acquisitions("s1", [])
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW)
    session.commit()

    assert session.execute(select(orm.AcquisitionORM)).scalars().all() == []
    events = session.execute(select(orm.DeletionEventORM)).scalars().all()
    assert len(events) == 2


def test_child_floor_does_not_trip_at_low_ratio(session):
    """4 existed, only 1 dropped (25% <= default 50% floor) — no trip."""
    r = _record_with_acquisitions("s1", ["a1", "a2", "a3", "a4"])
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    r2 = _record_with_acquisitions("s1", ["a1", "a2", "a3"])
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW)
    session.commit()

    acqs = session.execute(select(orm.AcquisitionORM)).scalars().all()
    assert len(acqs) == 3
    events = session.execute(select(orm.DeletionEventORM)).scalars().all()
    assert len(events) == 1


def test_child_floor_ratio_and_min_count_configurable(session):
    """Relaxing child_prune_safety_floor lets a scan that would otherwise
    trip the default go through."""
    r = _record_with_acquisitions("s1", ["a1", "a2", "a3", "a4"])
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    r2 = _record_with_acquisitions("s1", ["a1"])
    # 75% drop would trip the default 0.5 floor — raise the floor to allow it.
    upsert_sample_record(
        session,
        r2,
        extras=[],
        run_id="run-2",
        now=_NOW,
        child_prune_safety_floor=0.9,
    )
    session.commit()
    assert len(session.execute(select(orm.AcquisitionORM)).scalars().all()) == 1

    # Tightening child_prune_min_count so 2 existing is enough to guard.
    r3 = _record_with_acquisitions("s1", ["a1", "a2"])
    upsert_sample_record(session, r3, extras=[], run_id="run-3", now=_NOW)
    session.commit()
    r4 = _record_with_acquisitions("s1", [])
    with pytest.raises(ChildPruneSafetyFloorExceeded):
        upsert_sample_record(
            session,
            r4,
            extras=[],
            run_id="run-4",
            now=_NOW,
            child_prune_min_count=2,
        )
    session.rollback()


def test_whole_run_sample_floor_untouched_by_child_floor(session):
    """soft_delete_missing_samples (the §08a-predating whole-run floor) is
    unaffected by the new per-sample child floor — same behavior as before
    08b (regression guard per TODO.md task 2 acceptance criteria)."""
    _seed(session, ["a", "b", "c", "d"])
    with pytest.raises(PruneSafetyFloorExceeded) as excinfo:
        soft_delete_missing_samples(
            session, fs_sample_ids={"a"}, run_id="run-1", now=_NOW, safety_floor=0.5
        )
    assert excinfo.value.ratio > 0.5
    assert sorted(excinfo.value.missing) == ["b", "c", "d"]


# ─── §08c `renamed_from` hint ────────────────────────────────────────────────


def test_filter_to_columns_drops_renamed_from():
    """`renamed_from` is directive-only — it must never survive into an ORM
    payload, regardless of which entity's columns it's filtered against."""
    payload = {"acquisition_id": "a1", "sample_id": "s1", "renamed_from": "old"}
    assert "renamed_from" not in _filter_to_columns(payload, orm.AcquisitionORM)
    assert "renamed_from" not in _filter_to_columns(
        {"sample_id": "s1", "renamed_from": "old"}, orm.SampleORM
    )


def test_acquisition_rename_suppresses_event_and_floor_and_records_rename(session):
    """Renaming 3 of 4 acquisitions would trip the 75% > 50% floor as an
    ordinary drop, but since all 3 carry `renamed_from`, none count toward
    the floor or get an ordinary deletion event — each gets a rename event
    instead, and the row still physically drops (no PK rewrite)."""
    r = _record_with_acquisitions("s1", ["a1", "a2", "a3", "a4"])
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    acquisitions = {
        "a1": AcquisitionFile(acquisition=Acquisition(acquisition_id="a1")),
        "b2": AcquisitionFile(
            acquisition=Acquisition(acquisition_id="b2", renamed_from="a2")
        ),
        "b3": AcquisitionFile(
            acquisition=Acquisition(acquisition_id="b3", renamed_from="a3")
        ),
        "b4": AcquisitionFile(
            acquisition=Acquisition(acquisition_id="b4", renamed_from="a4")
        ),
    }
    r2 = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions=acquisitions,
    )
    # Must NOT raise ChildPruneSafetyFloorExceeded despite a 75% drop.
    rename_info = upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW + 1
    )
    session.commit()

    assert rename_info == RenameContinuity(
        sample=None,
        acquisitions={"b2": "a2", "b3": "a3", "b4": "a4"},
    )

    events = session.execute(select(orm.DeletionEventORM)).scalars().all()
    assert len(events) == 3
    assert {ev.kind for ev in events} == {"rename"}
    assert {ev.entity_type for ev in events} == {"acquisition"}
    renamed_pairs = {
        (
            json.loads(ev.last_known_json)["renamed_from"],
            json.loads(ev.last_known_json)["renamed_to"],
        )
        for ev in events
    }
    assert renamed_pairs == {("a2", "b2"), ("a3", "b3"), ("a4", "b4")}

    # Old acquisitions genuinely gone; new ones genuinely fresh rows (no PK
    # rewrite — a1 survives untouched, a2/a3/a4 are simply absent).
    acq_ids = {
        a.acquisition_id
        for a in session.execute(select(orm.AcquisitionORM)).scalars().all()
    }
    assert acq_ids == {"a1", "b2", "b3", "b4"}


def test_acquisition_rename_rescan_does_not_duplicate_event(session):
    """`renamed_from` is a permanent breadcrumb (§08c: "it can stay in the
    file"), so an unrelated later rescan still sees it. The old acquisition
    is already gone after the first scan recorded the rename — a second scan
    must not record it again."""
    r = _record_with_acquisitions("s1", ["a1", "a2"])
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    acquisitions = {
        "a1": AcquisitionFile(acquisition=Acquisition(acquisition_id="a1")),
        "b2": AcquisitionFile(
            acquisition=Acquisition(acquisition_id="b2", renamed_from="a2")
        ),
    }
    r2 = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions=acquisitions,
    )
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    # Unrelated rescan: same fs state, "b2" still authored with the same
    # `renamed_from = "a2"` breadcrumb.
    upsert_sample_record(session, r2, extras=[], run_id="run-3", now=_NOW + 2)
    session.commit()

    events = session.execute(select(orm.DeletionEventORM)).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "rename"
    assert events[0].scan_run_id == "run-2"


def test_child_rename_suppresses_event_and_does_not_trip_floor_at_100_percent(
    session,
):
    """A child-level rename (raw_tomogram): all 4 existing raw_tomogram rows
    are "renamed" in one scan (100% of existing) — would trip the floor at
    any nonzero threshold as an ordinary drop, but must not trip since every
    dropped row is exempt."""
    acq_ids = ["a1", "a2", "a3", "a4"]
    r = _record_with_acquisitions("s1", acq_ids, raw_tomo_acq_ids=frozenset(acq_ids))
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    acquisitions = {
        aid: AcquisitionFile(
            acquisition=Acquisition(acquisition_id=aid),
            raw_tomogram=RawTomogram(id=f"{aid}_raw2", renamed_from=f"{aid}_raw"),
        )
        for aid in acq_ids
    }
    r2 = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions=acquisitions,
    )
    # Must not raise despite a 100% drop of the existing raw_tomogram rows.
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    events = session.execute(select(orm.DeletionEventORM)).scalars().all()
    assert len(events) == 4
    assert {ev.kind for ev in events} == {"rename"}
    assert {ev.entity_type for ev in events} == {"raw_tomogram"}

    raw_ids = {
        t.tomogram_id
        for t in session.execute(select(orm.RawTomogramORM)).scalars().all()
    }
    assert raw_ids == {f"{aid}_raw2" for aid in acq_ids}


def test_acquisition_rename_without_hint_falls_back_to_delete_and_add(session):
    """Documented fallback (§08c acceptance): no `renamed_from` -> ordinary
    delete+add. The old id gets a normal deletion event, no rename event is
    recorded, and it would count toward the floor like any other drop."""
    r = _record_with_acquisitions("s1", ["a1"])
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    r2 = _record_with_acquisitions("s1", ["b1"])  # "b1" is NOT a rename of "a1"
    rename_info = upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW + 1
    )
    session.commit()

    assert rename_info == RenameContinuity(sample=None, acquisitions={})
    events = session.execute(select(orm.DeletionEventORM)).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "deletion"
    assert events[0].entity_type == "acquisition"
    assert events[0].acquisition_id == "a1"


def test_sample_rename_records_event_and_exempts_from_prune_floor(session):
    """Sample-level rename: the rename event is recorded immediately by
    upsert_sample_record; suppression of the ordinary deletion event and
    exemption from the whole-run floor happen in soft_delete_missing_samples
    (the only place fresh fs ids and live DB samples are both in hand for
    the sample level) via its `renamed_exempt` param."""
    _seed(session, ["a", "b"])
    session.commit()

    # "a" renamed to "a2"; "b" separately, genuinely vanishes this run.
    rename_info = upsert_sample_record(
        session,
        SampleRecord(
            sample=Sample(
                sample_id="a2",
                data_source=DataSource.experimental,
                project=Project.chromatin,
                renamed_from="a",
            )
        ),
        extras=[],
        run_id="run-2",
        now=_NOW,
    )
    session.commit()
    assert rename_info == RenameContinuity(sample="a", acquisitions={})

    # The rename event was recorded immediately, regardless of prune.
    events = session.execute(select(orm.DeletionEventORM)).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "rename"
    assert events[0].entity_type == "sample"
    assert events[0].sample_id == "a2"
    assert json.loads(events[0].last_known_json) == {
        "renamed_from": "a",
        "renamed_to": "a2",
    }

    # live = {a, b, a2} = 3; fs = {a2}; to_delete = {a, b}. Without the
    # exemption this would be 2/3 = 67% > the 50% floor and abort.
    with pytest.raises(PruneSafetyFloorExceeded):
        soft_delete_missing_samples(
            session, fs_sample_ids={"a2"}, run_id="run-2", now=_NOW, safety_floor=0.5
        )
    # With "a" exempted, only "b" counts: 1/3 = 33% <= 50% -> no trip.
    soft_delete_missing_samples(
        session,
        fs_sample_ids={"a2"},
        run_id="run-2",
        now=_NOW,
        safety_floor=0.5,
        renamed_exempt=frozenset({"a"}),
    )
    session.commit()

    # Both old rows still soft-delete as usual (no PK rewrite) ...
    assert session.get(orm.SampleORM, "a").deleted_at is not None
    assert session.get(orm.SampleORM, "b").deleted_at is not None
    # ... but only "b" got an ordinary deletion event; "a" only ever got the
    # rename event recorded above (no double-counting).
    events = session.execute(select(orm.DeletionEventORM)).scalars().all()
    assert len(events) == 2
    by_sample = {ev.sample_id: ev.kind for ev in events}
    assert by_sample == {"a2": "rename", "b": "deletion"}


def test_sample_rename_rescan_does_not_duplicate_event(session):
    """Same permanent-breadcrumb concern as the acquisition case, one level
    up: once `soft_delete_missing_samples` has tombstoned the old sample,
    a later unrelated rescan of the renamed-to sample (still carrying
    `renamed_from`) must not record a second rename event."""
    _seed(session, ["a"])
    session.commit()

    def _rescan(run_id: str, now: float) -> dict:
        return upsert_sample_record(
            session,
            SampleRecord(
                sample=Sample(
                    sample_id="a2",
                    data_source=DataSource.experimental,
                    project=Project.chromatin,
                    renamed_from="a",
                )
            ),
            extras=[],
            run_id=run_id,
            now=now,
        )

    _rescan("run-2", _NOW)
    session.commit()
    soft_delete_missing_samples(
        session,
        fs_sample_ids={"a2"},
        run_id="run-2",
        now=_NOW,
        safety_floor=0.5,
        renamed_exempt=frozenset({"a"}),
    )
    session.commit()
    assert session.get(orm.SampleORM, "a").deleted_at is not None

    # Unrelated rescan of "a2" — the TOML still carries `renamed_from = "a"`.
    _rescan("run-3", _NOW + 1)
    session.commit()

    events = session.execute(select(orm.DeletionEventORM)).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "rename"
    assert events[0].scan_run_id == "run-2"


def test_sample_rename_carries_last_changed_at(session):
    """Continuity stamp: `upsert_sample_scan_status`'s `carried_last_changed_at`
    is used (instead of `now`) when `changed=True` — the mechanism scanner.py
    uses to carry the old sample's freshness stamp onto the rename target."""
    _seed(session, ["a"])
    session.commit()
    old_last_changed = _NOW - 500
    session.merge(
        orm.SampleScanStatusORM(
            sample_id="a",
            last_scanned_at=_NOW,
            last_changed_at=old_last_changed,
            last_outcome="upserted",
            last_scan_run_id="run-1",
        )
    )
    session.commit()

    upsert_sample_scan_status(
        session,
        "a2",
        now=_NOW + 100,
        outcome="upserted",
        run_id="run-2",
        changed=True,
        carried_last_changed_at=old_last_changed,
    )
    session.commit()

    status = session.get(orm.SampleScanStatusORM, "a2")
    assert status.last_changed_at == old_last_changed
    assert status.last_changed_at != _NOW + 100
    assert status.last_scanned_at == _NOW + 100  # always stamped to `now`
