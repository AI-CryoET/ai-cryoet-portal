"""Tilt-series upsert + soft-delete behavior.

Per plan decision §11.22, ``tilt_series`` rows are **left untouched** on
soft-delete (same convention as every other child table). Resurrection via
re-upsert re-populates the rows.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from schema import (
    Acquisition,
    AcquisitionFile,
    Sample,
    SampleRecord,
    TiltSeries,
)
from schema.schema import DataSource, Project

from catalog import db, orm
from catalog.persistence import upsert_sample_record


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


def _make_record_with_tilt_series(
    sample_id: str = "s1", *, tilt_series_ids: tuple[str, ...] = ("ts_a",)
) -> SampleRecord:
    acq = Acquisition(acquisition_id="Pos1")
    ts_list = [
        TiltSeries(
            tilt_series_id=tid,
            derived_from="Frames",
            is_aligned=False,
            st_path=f"/data/{sample_id}/Pos1/TiltSeries/{tid}/stack/{tid}.st",
            mtime=1234567890.0,
        )
        for tid in tilt_series_ids
    ]
    return SampleRecord(
        sample=Sample(
            sample_id=sample_id,
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={
            "Pos1": AcquisitionFile(acquisition=acq, tilt_series=ts_list)
        },
    )


def test_upsert_writes_tilt_series_row(session) -> None:
    r = _make_record_with_tilt_series()
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=time.time()
    )
    session.commit()

    rows = session.execute(select(orm.TiltSeriesORM)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.sample_id == "s1"
    assert row.acquisition_id == "Pos1"
    assert row.tilt_series_id == "ts_a"
    assert row.derived_from == "Frames"
    assert row.is_aligned is False
    assert row.st_path.endswith("/TiltSeries/ts_a/stack/ts_a.st")
    assert row.mtime == 1234567890.0


def test_soft_delete_leaves_tilt_series_rows_in_place(session) -> None:
    r = _make_record_with_tilt_series()
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=time.time()
    )
    # Mimic ``soft_delete_missing_samples``: only flip ``deleted_at``,
    # never touch child rows.
    session.execute(
        orm.SampleORM.__table__.update().values(deleted_at=time.time())
    )
    session.commit()

    rows = session.execute(select(orm.TiltSeriesORM)).scalars().all()
    assert len(rows) == 1, (
        "tilt_series rows must survive soft-delete — same convention as "
        "tomograms/annotations (plan §11.22)"
    )


def test_resurrection_via_reupsert_brings_tilt_series_back(session) -> None:
    r = _make_record_with_tilt_series()
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=time.time()
    )
    session.execute(
        orm.SampleORM.__table__.update().values(deleted_at=time.time())
    )
    session.commit()

    # Re-upsert (resurrection path) clears deleted_at and the surviving
    # tilt_series rows remain reachable.
    upsert_sample_record(
        session, r, extras=[], run_id="run-2", now=time.time()
    )
    session.commit()

    sample = session.get(orm.SampleORM, "s1")
    assert sample is not None
    assert sample.deleted_at is None
    rows = session.execute(select(orm.TiltSeriesORM)).scalars().all()
    assert {(r.tilt_series_id,) for r in rows} == {("ts_a",)}


def test_stale_per_mdoc_rows_pruned_on_relaxed_parser(session) -> None:
    """Phase 4.6 regression: a DB seeded by the OLD parser with one row per
    MDOC must collapse to a single row on re-upsert with the new parser.

    Mimics the gouauxlab upgrade path: the previous scan persisted 33 rows
    (one per MDOC file). After the parser change, a re-scan collapses them
    to one row, and ``_delete_stale_children`` prunes the obsolete 32.
    """
    # Seed with 33 per-MDOC rows (the broken-old-parser state).
    old_ids = tuple(f"file_{i:03d}_{i * 3 - 30}.0" for i in range(33))
    r_old = _make_record_with_tilt_series(tilt_series_ids=old_ids)
    upsert_sample_record(
        session, r_old, extras=[], run_id="run-old", now=time.time()
    )
    session.commit()
    assert (
        len(session.execute(select(orm.TiltSeriesORM)).scalars().all()) == 33
    )

    # Re-upsert with the collapsed (new-parser) shape: one row. This is a
    # deliberate 32-of-33 (97%) drop — exactly the shape §08b's child safety
    # floor exists to catch — so this stand-in for an operator-run parser
    # migration opts out via an explicit floor, the same way a real migration
    # would pass a relaxed --child-prune-safety-floor for that one run.
    r_new = _make_record_with_tilt_series(
        tilt_series_ids=("20241211_HippWaffle_49",)
    )
    upsert_sample_record(
        session,
        r_new,
        extras=[],
        run_id="run-new",
        now=time.time(),
        child_prune_safety_floor=1.0,
    )
    session.commit()

    rows = session.execute(select(orm.TiltSeriesORM)).scalars().all()
    assert [r.tilt_series_id for r in rows] == ["20241211_HippWaffle_49"]


def test_upsert_removes_stale_tilt_series_rows(session) -> None:
    """Re-upserting with a smaller tilt_series set deletes the dropped row."""
    r1 = _make_record_with_tilt_series(tilt_series_ids=("ts_a", "ts_b"))
    upsert_sample_record(
        session, r1, extras=[], run_id="run-1", now=time.time()
    )
    session.commit()
    assert (
        len(session.execute(select(orm.TiltSeriesORM)).scalars().all()) == 2
    )

    r2 = _make_record_with_tilt_series(tilt_series_ids=("ts_a",))
    upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=time.time()
    )
    session.commit()

    rows = session.execute(select(orm.TiltSeriesORM)).scalars().all()
    assert [r.tilt_series_id for r in rows] == ["ts_a"]
