"""Tests for catalog.persistence.upsert_sample_record."""

from __future__ import annotations

import datetime as _dt
import json
import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from schema import (
    Acquisition,
    AcquisitionFile,
    Annotation,
    Chromatin,
    Fiducial,
    Label,
    MdRun,
    MdSource,
    PostProcessedTomogram,
    RawTomogram,
    ReconstructionAlignment,
    Sample,
    SampleRecord,
    Simulation,
    TiltSeries,
)
from schema.loader import ExtrasEntry
from schema.schema import DataSource, DatasetType, Project, ReconstructionFile

from catalog import db, orm
from catalog.assembler import ScanIssue
from catalog.persistence import (
    reconcile_run_issues,
    reconcile_sample_issues,
    upsert_acquisition_scan_status,
    upsert_sample_record,
    upsert_sample_scan_status,
)

# Fixed run-level ``now`` threaded through the upsert calls (one timestamp per
# run, decision §9.6); value is arbitrary but stable for assertions.
_NOW = 1_700_000_000.0


def _issue(
    *,
    sample_id="s1",
    category="extra_field",
    location="<root>",
    message="m",
    severity="warning",
    scope="sample",
    acquisition_id=None,
    md_run_id=None,
    file_kind="sample_toml",
    file_path=None,
) -> ScanIssue:
    return ScanIssue(
        severity=severity,
        scope=scope,
        category=category,
        location=location,
        message=message,
        sample_id=sample_id,
        acquisition_id=acquisition_id,
        md_run_id=md_run_id,
        file_kind=file_kind,
        file_path=file_path,
    )


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


def _make_record(sample_id: str = "s1", **overrides) -> SampleRecord:
    sample = Sample(
        sample_id=sample_id,
        data_source=DataSource.experimental,
        project=Project.chromatin,
    )
    return SampleRecord(sample=sample, **overrides)


def test_upsert_basic_sample(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.sample_id == "s1"
    assert row.deleted_at is None


def test_upsert_resurrects_soft_deleted(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    # Force a soft delete.
    session.execute(
        orm.SampleORM.__table__.update().values(deleted_at=time.time())
    )
    session.commit()
    assert session.get(orm.SampleORM, "s1").deleted_at is not None

    upsert_sample_record(
        session, r, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()
    assert session.get(orm.SampleORM, "s1").deleted_at is None


def test_upsert_persists_experiment_date(session):
    sample = Sample(
        sample_id="s1",
        data_source=DataSource.experimental,
        project=Project.chromatin,
        experiment_date=_dt.date(2025, 8, 20),
    )
    r = SampleRecord(sample=sample)
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row.experiment_date == _dt.date(2025, 8, 20)


def test_upsert_chromatin_then_remove(session):
    r1 = _make_record(chromatin=Chromatin(buffer="HEPES"))
    upsert_sample_record(
        session, r1, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    chrom = session.get(orm.ChromatinORM, "s1")
    assert chrom is not None
    assert chrom.buffer == "HEPES"

    # Re-upsert with no chromatin block — row must be deleted.
    r2 = _make_record()
    upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()
    assert session.get(orm.ChromatinORM, "s1") is None


def test_upsert_fiducial_then_remove(session):
    r1 = _make_record(
        fiducial=Fiducial(vendor="Aurion", aunp_size_nm=10.0)
    )
    upsert_sample_record(
        session, r1, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    fid = session.get(orm.FiducialORM, "s1")
    assert fid is not None
    assert fid.vendor == "Aurion"
    assert fid.aunp_size_nm == 10.0

    r2 = _make_record()
    upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()
    assert session.get(orm.FiducialORM, "s1") is None


def test_upsert_label_ordinal_cleanup(session):
    r1 = _make_record(
        label=[
            Label(label_target="actin", aunp_size_nm=5.0),
            Label(label_target="tubulin", aunp_size_nm=10.0),
            Label(label_target="myosin", aunp_size_nm=15.0),
        ]
    )
    upsert_sample_record(
        session, r1, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.LabelORM)
            .where(orm.LabelORM.sample_id == "s1")
            .order_by(orm.LabelORM.ordinal)
        )
        .scalars()
        .all()
    )
    assert [a.ordinal for a in rows] == [0, 1, 2]
    assert [a.label_target for a in rows] == ["actin", "tubulin", "myosin"]
    assert [a.aunp_size_nm for a in rows] == [5.0, 10.0, 15.0]

    # Reduce to two — ordinal 2 must be cleaned up.
    r2 = _make_record(
        label=[
            Label(label_target="actin", aunp_size_nm=5.0),
            Label(label_target="tubulin", aunp_size_nm=10.0),
        ]
    )
    upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.LabelORM)
            .where(orm.LabelORM.sample_id == "s1")
            .order_by(orm.LabelORM.ordinal)
        )
        .scalars()
        .all()
    )
    assert [a.ordinal for a in rows] == [0, 1]


def test_label_aunp_size_nm_polymorphic(session):
    """``Label.aunp_size_nm`` is ``float | list[float] | None`` — both round-trip."""
    r = _make_record(
        label=[
            Label(label_target="x", aunp_size_nm=5.0),
            Label(label_target="y", aunp_size_nm=[5.0, 10.0]),
            Label(label_target="z", aunp_size_nm=None),
        ]
    )
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.LabelORM)
            .where(orm.LabelORM.sample_id == "s1")
            .order_by(orm.LabelORM.ordinal)
        )
        .scalars()
        .all()
    )
    assert rows[0].aunp_size_nm == 5.0
    assert rows[1].aunp_size_nm == [5.0, 10.0]
    assert rows[2].aunp_size_nm is None


def test_upsert_raw_and_post_tomogram_share_id_namespace(session):
    """One acquisition can carry a raw tomogram + one or more post-processed
    tomograms; both land in their respective tables under the same composite PK
    shape (sample_id, acquisition_id, tomogram_id).
    """
    raw = RawTomogram(
        id="t_raw", reconstruction_alignment_id="grp1", voxel_size=11.72
    )
    post1 = PostProcessedTomogram(
        id="t_post1", reconstruction_alignment_id="grp1", voxel_size=11.72,
        size_bytes=12345,
    )
    post2 = PostProcessedTomogram(
        id="t_post2", reconstruction_alignment_id="grp1", voxel_size=11.72,
        denoising_software="cryoCARE",
    )
    ann = Annotation(id="a1", reconstruction_alignment_id="grp1", files=["x.mrc"])
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        raw_tomogram=[raw],
        post_processed_tomogram=[post1, post2],
        annotation=[ann],
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()

    raw_row = session.get(orm.RawTomogramORM, ("s1", "acq1", "grp1", "t_raw"))
    assert raw_row is not None
    assert raw_row.voxel_size == pytest.approx(11.72)

    post1_row = session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "grp1", "t_post1")
    )
    assert post1_row is not None
    assert post1_row.size_bytes == 12345

    post2_row = session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "grp1", "t_post2")
    )
    assert post2_row is not None
    assert post2_row.denoising_software == "cryoCARE"

    ann_row = session.get(orm.AnnotationORM, ("s1", "acq1", "grp1", "a1"))
    assert ann_row is not None
    assert ann_row.files == ["x.mrc"]


def test_upsert_persists_reconstruction_toml_rows(session):
    """Under reconstruction.toml the assembler populates
    ``record.reconstructions[acq_id][group_id]`` and leaves ``acq_file.*`` empty.
    Persistence must upsert those rows into the same ORM tables the legacy
    acq_file.* loops write to (§4.5)."""
    rf = ReconstructionFile(
        reconstruction_alignment=ReconstructionAlignment(
            id="grpA", alignment_software="AreTomo"
        ),
        raw_tomogram=[RawTomogram(id="ctf", pipeline="bp", voxel_size=11.72)],
        post_processed_tomogram=[PostProcessedTomogram(id="ctf_dn")],
        annotation=[Annotation(id="mito", files=["mito.mrc"])],
    )
    acq_file = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
        reconstructions={"acq1": {"grpA": rf}},
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    raw_row = session.get(orm.RawTomogramORM, ("s1", "acq1", "grpA", "ctf"))
    assert raw_row is not None
    assert raw_row.pipeline == "bp"
    assert raw_row.voxel_size == pytest.approx(11.72)

    post_row = session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "grpA", "ctf_dn")
    )
    assert post_row is not None

    ann_row = session.get(orm.AnnotationORM, ("s1", "acq1", "grpA", "mito"))
    assert ann_row is not None
    assert ann_row.files == ["mito.mrc"]

    ra_row = session.get(orm.ReconstructionAlignmentORM, ("s1", "acq1", "grpA"))
    assert ra_row is not None
    assert ra_row.alignment_software == "AreTomo"

    # A re-upsert of the same state must not delete the reconstruction rows
    # (keep-set regression guard).
    upsert_sample_record(session, r, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()
    assert session.get(
        orm.RawTomogramORM, ("s1", "acq1", "grpA", "ctf")
    ) is not None
    assert session.get(
        orm.ReconstructionAlignmentORM, ("s1", "acq1", "grpA")
    ) is not None


def test_stale_raw_tomogram_cleaned_up_on_disappearance(session):
    raw = RawTomogram(id="t_raw", reconstruction_alignment_id="grp1")
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        raw_tomogram=[raw],
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    assert session.get(
        orm.RawTomogramORM, ("s1", "acq1", "grp1", "t_raw")
    ) is not None

    # Drop the raw tomogram in the next upsert.
    acq_file2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()
    assert session.get(orm.RawTomogramORM, ("s1", "acq1", "grp1", "t_raw")) is None


def test_stale_post_processed_tomogram_cleaned_up(session):
    tomos1 = [
        PostProcessedTomogram(id="t1", reconstruction_alignment_id="grp1"),
        PostProcessedTomogram(id="t2", reconstruction_alignment_id="grp1"),
    ]
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        post_processed_tomogram=tomos1,
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "grp1", "t2")
    ) is not None

    tomos2 = [PostProcessedTomogram(id="t1", reconstruction_alignment_id="grp1")]
    acq_file2 = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        post_processed_tomogram=tomos2,
    )
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()
    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "grp1", "t1")
    ) is not None
    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "grp1", "t2")
    ) is None


def test_md_run_and_md_source_round_trip(session):
    """Simulation samples carry [[md_run]] at sample scope and ``[md_source]``
    per acquisition; both upsert and clear on disappearance."""
    sample = Sample(
        sample_id="sim1",
        data_source=DataSource.simulation,
        project=Project.chromatin,
    )
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        md_source=MdSource(md_run_id="run_a", now=_NOW, frame=42),
    )
    r = SampleRecord(
        sample=sample,
        simulation=Simulation(dataset_type=DatasetType.bulk),
        md_run=[
            MdRun(
                id="run_a",
                seed=123,
                computer="dgx-01",
                sample_time=100.0,
                timestep=0.002,
                reference_contact="Jane Researcher",
                force_field_version="amber99sb-ildn",
            )
        ],
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()

    md_run_row = session.get(orm.MdRunORM, ("sim1", "run_a"))
    assert md_run_row is not None
    assert md_run_row.seed == 123
    assert md_run_row.computer == "dgx-01"
    # New MdRun columns flow through model_dump + _filter_to_columns.
    assert md_run_row.sample_time == pytest.approx(100.0)
    assert md_run_row.timestep == pytest.approx(0.002)
    assert md_run_row.reference_contact == "Jane Researcher"
    assert md_run_row.force_field_version == "amber99sb-ildn"

    # simulation.dataset_type round-trips as the enum value string.
    sim_row = session.get(orm.SimulationORM, "sim1")
    assert sim_row is not None
    assert sim_row.dataset_type == "bulk"

    md_source_row = session.get(orm.MdSourceORM, ("sim1", "acq1"))
    assert md_source_row is not None
    assert md_source_row.md_run_id == "run_a"
    assert md_source_row.frame == 42

    # Re-upsert without md_source — row must be deleted while md_run stays.
    acq_file2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r2 = SampleRecord(
        sample=sample,
        simulation=Simulation(dataset_type=DatasetType.bulk),
        md_run=r.md_run,
        acquisitions={"acq1": acq_file2},
    )
    upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()
    assert session.get(orm.MdSourceORM, ("sim1", "acq1")) is None
    assert session.get(orm.MdRunORM, ("sim1", "run_a")) is not None

    # Now drop md_run too.
    r3 = SampleRecord(
        sample=sample,
        simulation=Simulation(dataset_type=DatasetType.bulk),
        acquisitions={"acq1": acq_file2},
    )
    upsert_sample_record(
        session, r3, extras=[], run_id="run-3", now=_NOW
    )
    session.commit()
    assert session.get(orm.MdRunORM, ("sim1", "run_a")) is None


def test_upsert_acquisition_facility_and_tilt_quality(session):
    """New Acquisition columns ``facility`` and ``acquisition_quality``
    flow through to the DB; the removed ``quality`` column is simply absent."""
    acq_file = AcquisitionFile(
        acquisition=Acquisition(
            acquisition_id="acq1",
            facility="Janelia",
            acquisition_quality=4,
        ),
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()

    row = session.get(orm.AcquisitionORM, ("s1", "acq1"))
    assert row is not None
    assert row.facility == "Janelia"
    assert row.acquisition_quality == 4
    # The dropped ``quality`` column no longer exists on the ORM.
    assert not hasattr(row, "quality")


def test_stale_acquisition_cleaned_up(session):
    acq1 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    acq2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq2"))
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq1, "acq2": acq2},
    )
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    assert session.get(orm.AcquisitionORM, ("s1", "acq2")) is not None

    # Re-upsert without acq2.
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq1})
    upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()
    assert session.get(orm.AcquisitionORM, ("s1", "acq1")) is not None
    assert session.get(orm.AcquisitionORM, ("s1", "acq2")) is None


def test_extras_refresh(session):
    r = _make_record()
    extras = [
        ExtrasEntry(
            entity_type="sample",
            entity_pk=("s1",),
            key="weird_key",
            value="weird_value",
        ),
        ExtrasEntry(
            entity_type="label",
            entity_pk=("s1", 0),
            key="custom",
            value={"nested": 1},
        ),
    ]
    upsert_sample_record(
        session, r, extras=extras, run_id="run-1", now=_NOW
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.ExtrasORM).where(orm.ExtrasORM.sample_id == "s1")
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2

    # Re-upsert with one fewer extra — old ones must be gone.
    upsert_sample_record(
        session, r, extras=extras[:1], run_id="run-2", now=_NOW
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.ExtrasORM).where(orm.ExtrasORM.sample_id == "s1")
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert json.loads(rows[0].entity_pk_json) == ["s1"]
    assert json.loads(rows[0].value_json) == "weird_value"


def test_extras_value_json_handles_dates(session):
    """json.dumps default fallback handles datetime.date for safety."""
    import datetime

    r = _make_record()
    extras = [
        ExtrasEntry(
            entity_type="milling",
            entity_pk=("s1",),
            key="custom_date",
            value=datetime.date(2026, 5, 1),
        )
    ]
    upsert_sample_record(
        session, r, extras=extras, run_id="run-1", now=_NOW
    )
    session.commit()
    row = (
        session.execute(
            select(orm.ExtrasORM).where(orm.ExtrasORM.sample_id == "s1")
        )
        .scalars()
        .one()
    )
    assert json.loads(row.value_json) == "2026-05-01"


def test_upsert_sample_record_does_not_write_issues(session):
    """upsert_sample_record no longer touches the issues table — issue
    reconciliation is a separate call (the scan_warnings write path is gone)."""
    r = _make_record()
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()
    assert session.execute(select(orm.IssueORM)).scalars().all() == []


def test_idempotent_double_upsert_same_state(session):
    r = _make_record(
        chromatin=Chromatin(buffer="HEPES"),
        label=[Label(label_target="actin", aunp_size_nm=5.0)],
    )
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    upsert_sample_record(
        session, r, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()
    samples = session.execute(select(orm.SampleORM)).scalars().all()
    chromatin = session.execute(select(orm.ChromatinORM)).scalars().all()
    labels = session.execute(select(orm.LabelORM)).scalars().all()
    assert len(samples) == 1
    assert len(chromatin) == 1
    assert len(labels) == 1


def test_unflushed_inserts_dont_get_deleted_by_stale_cleanup(session):
    """Adding a new tomogram in a follow-up upsert must not be wiped by the
    stale-row cleanup. Regression guard for the keep-set logic."""
    tomos1 = [PostProcessedTomogram(id="t1", reconstruction_alignment_id="grp1")]
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        post_processed_tomogram=tomos1,
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()

    tomos2 = [
        PostProcessedTomogram(id="t1", reconstruction_alignment_id="grp1"),
        PostProcessedTomogram(id="t2", reconstruction_alignment_id="grp1"),
    ]
    acq_file2 = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        post_processed_tomogram=tomos2,
    )
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(
        session, r2, extras=[], run_id="run-2", now=_NOW
    )
    session.commit()

    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "grp1", "t1")
    ) is not None
    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "grp1", "t2")
    ) is not None


def test_upsert_writes_disk_size_bytes(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW, disk_size_bytes=12345
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.disk_size_bytes == 12345


def test_upsert_default_disk_size_bytes_is_null(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.disk_size_bytes is None


def test_upsert_sample_record_with_thumbnail_path(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW,
        thumbnail_path="s/a/t.png",
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.thumbnail_path == "s/a/t.png"


def test_upsert_sample_record_thumbnail_path_default_is_null(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], run_id="run-1", now=_NOW
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.thumbnail_path is None


# ── issue reconciliation (§4.4) ────────────────────────────────────────────


def _outstanding(session, sample_id="s1"):
    return (
        session.execute(
            select(orm.IssueORM)
            .where(orm.IssueORM.sample_id == sample_id)
            .where(orm.IssueORM.resolved_at.is_(None))
        )
        .scalars()
        .all()
    )


def test_reconcile_new_issue_sets_first_seen(session):
    n_new, n_resolved = reconcile_sample_issues(
        session, "run-1", "s1", [_issue(message="m1")], _NOW
    )
    session.commit()
    assert (n_new, n_resolved) == (1, 0)
    rows = session.execute(select(orm.IssueORM)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.first_seen_at == _NOW
    assert row.first_seen_run_id == "run-1"
    assert row.last_seen_at == _NOW
    assert row.last_seen_run_id == "run-1"
    assert row.resolved_at is None


def test_reconcile_persists_md_run_id(session):
    """An md_run-scoped issue's run id round-trips through insert and reopen,
    so the manage page can link the warning row to that run's authoring form."""
    reconcile_sample_issues(
        session,
        "run-1",
        "s1",
        [_issue(file_kind="md_run_toml", md_run_id="run_a", location="md_run[run_a].seed")],
        _NOW,
    )
    session.commit()
    row = _outstanding(session)[0]
    assert row.md_run_id == "run_a"

    # Resolve then recur: the reopened row still carries the run id.
    reconcile_sample_issues(session, "run-2", "s1", [], _NOW + 60.0)
    session.commit()
    reconcile_sample_issues(
        session,
        "run-3",
        "s1",
        [_issue(file_kind="md_run_toml", md_run_id="run_a", location="md_run[run_a].seed")],
        _NOW + 120.0,
    )
    session.commit()
    row = _outstanding(session)[0]
    assert row.md_run_id == "run_a"


def test_reconcile_recurring_preserves_first_seen_bumps_last_seen(session):
    reconcile_sample_issues(session, "run-1", "s1", [_issue()], _NOW)
    session.commit()
    later = _NOW + 3600.0
    n_new, n_resolved = reconcile_sample_issues(
        session, "run-2", "s1", [_issue()], later
    )
    session.commit()
    assert (n_new, n_resolved) == (0, 0)
    row = _outstanding(session)[0]
    assert row.first_seen_at == _NOW
    assert row.first_seen_run_id == "run-1"
    assert row.last_seen_at == later
    assert row.last_seen_run_id == "run-2"


def test_reconcile_fixed_issue_gets_resolved(session):
    reconcile_sample_issues(session, "run-1", "s1", [_issue()], _NOW)
    session.commit()
    later = _NOW + 3600.0
    # Re-evaluated sample no longer emits the issue → resolved.
    n_new, n_resolved = reconcile_sample_issues(session, "run-2", "s1", [], later)
    session.commit()
    assert (n_new, n_resolved) == (0, 1)
    assert _outstanding(session) == []
    row = session.execute(select(orm.IssueORM)).scalars().one()
    assert row.resolved_at == later
    assert row.resolved_run_id == "run-2"


def test_reconcile_message_only_change_preserves_first_seen(session):
    """Fingerprint excludes message — a re-worded message updates the text but
    preserves first_seen (decision §9.4)."""
    reconcile_sample_issues(
        session, "run-1", "s1", [_issue(message="count=1")], _NOW
    )
    session.commit()
    later = _NOW + 60.0
    n_new, n_resolved = reconcile_sample_issues(
        session, "run-2", "s1", [_issue(message="count=2")], later
    )
    session.commit()
    assert (n_new, n_resolved) == (0, 0)
    row = _outstanding(session)[0]
    assert row.first_seen_at == _NOW
    assert row.message == "count=2"


def test_reconcile_resolved_then_recurring_reopens(session):
    reconcile_sample_issues(session, "run-1", "s1", [_issue()], _NOW)
    session.commit()
    reconcile_sample_issues(session, "run-2", "s1", [], _NOW + 60.0)
    session.commit()
    assert _outstanding(session) == []

    later = _NOW + 120.0
    n_new, n_resolved = reconcile_sample_issues(
        session, "run-3", "s1", [_issue()], later
    )
    session.commit()
    # Reopen counts as newly-opened; only one row total (fingerprint UNIQUE).
    assert n_new == 1
    rows = session.execute(select(orm.IssueORM)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.resolved_at is None
    assert row.first_seen_at == _NOW  # preserved across the resolve→recur cycle
    assert row.first_seen_run_id == "run-1"
    assert row.last_seen_at == later
    assert row.last_seen_run_id == "run-3"


def test_reconcile_sample_rename_carries_first_seen_at(session):
    """§08c: a fresh issue under the renamed-to sample_id seeds first_seen_at
    from the matching pre-rename issue under the old sample_id (same
    category/file_kind/location), instead of reading as newly introduced."""
    reconcile_sample_issues(
        session, "run-1", "s_old", [_issue(sample_id="s_old", location="<root>")], _NOW
    )
    session.commit()

    later = _NOW + 3600.0
    n_new, n_resolved = reconcile_sample_issues(
        session,
        "run-2",
        "s_new",
        [_issue(sample_id="s_new", location="<root>")],
        later,
        renamed_from_sample="s_old",
    )
    session.commit()
    assert n_new == 1  # genuinely fresh row for s_new (different fingerprint)
    row = (
        session.execute(
            select(orm.IssueORM).where(orm.IssueORM.sample_id == "s_new")
        )
        .scalars()
        .one()
    )
    assert row.first_seen_at == _NOW
    assert row.first_seen_run_id == "run-1"
    assert row.last_seen_at == later
    assert row.last_seen_run_id == "run-2"

    # The old sample's issue is untouched — reconcile_sample_issues only ever
    # diffs the sample_id it's called for.
    old_row = (
        session.execute(
            select(orm.IssueORM).where(orm.IssueORM.sample_id == "s_old")
        )
        .scalars()
        .one()
    )
    assert old_row.resolved_at is None


def test_reconcile_acquisition_rename_carries_first_seen_at(session):
    """Same continuity, one level down: an acquisition-scope issue survives a
    `renamed_from` on the acquisition (sample unchanged)."""
    reconcile_sample_issues(
        session,
        "run-1",
        "s1",
        [
            _issue(
                sample_id="s1",
                acquisition_id="acq_old",
                scope="acquisition",
                file_kind="acquisition_toml",
                location="<root>",
            )
        ],
        _NOW,
    )
    session.commit()

    later = _NOW + 3600.0
    n_new, n_resolved = reconcile_sample_issues(
        session,
        "run-2",
        "s1",
        [
            _issue(
                sample_id="s1",
                acquisition_id="acq_new",
                scope="acquisition",
                file_kind="acquisition_toml",
                location="<root>",
            )
        ],
        later,
        renamed_acquisitions={"acq_new": "acq_old"},
    )
    session.commit()
    assert n_new == 1
    row = (
        session.execute(
            select(orm.IssueORM).where(orm.IssueORM.acquisition_id == "acq_new")
        )
        .scalars()
        .one()
    )
    assert row.first_seen_at == _NOW
    assert row.first_seen_run_id == "run-1"


def test_reconcile_skipped_sample_leaves_issues_unchanged(session):
    """Skipped sample: the scanner does NOT call reconcile, so issues persist
    with their old last_seen (the skip rule). We simulate by not re-reconciling.
    """
    reconcile_sample_issues(session, "run-1", "s1", [_issue()], _NOW)
    session.commit()
    # Run-2 skips s1 → no reconcile call. Issue stays outstanding, last_seen old.
    row = _outstanding(session)[0]
    assert row.resolved_at is None
    assert row.last_seen_at == _NOW
    assert row.last_seen_run_id == "run-1"


def test_reconcile_failed_sample_adds_assembly_failed_without_resolving(session):
    """Failed sample (resolve_missing=False): adds the assembly_failed error but
    does NOT resolve the sample's other outstanding issues (§4.4)."""
    reconcile_sample_issues(
        session, "run-1", "s1", [_issue(category="extra_field")], _NOW
    )
    session.commit()
    later = _NOW + 60.0
    failed = _issue(
        category="assembly_failed",
        severity="error",
        location="<root>",
        message="boom",
    )
    n_new, n_resolved = reconcile_sample_issues(
        session, "run-2", "s1", [failed], later, resolve_missing=False
    )
    session.commit()
    assert n_resolved == 0
    outstanding = _outstanding(session)
    cats = {row.category for row in outstanding}
    # Both the prior warning and the new error remain outstanding.
    assert cats == {"extra_field", "assembly_failed"}


def test_reconcile_run_issues_replaces_run_scope_set(session):
    run_issue = _issue(
        sample_id=None,
        scope="run",
        category="unknown_md_simulation_subdir",
        location="/data/MdSimulation/Bogus",
        file_kind="filesystem",
    )
    n_new, _ = reconcile_run_issues(session, "run-1", [run_issue], _NOW)
    session.commit()
    assert n_new == 1
    # Next run no longer emits it → resolved.
    _, n_resolved = reconcile_run_issues(session, "run-2", [], _NOW + 60.0)
    session.commit()
    assert n_resolved == 1
    row = session.execute(select(orm.IssueORM)).scalars().one()
    assert row.scope == "run"
    assert row.sample_id is None
    assert row.resolved_at is not None


# ── freshness + thumbnail provenance status (§4.5) ──────────────────────────


def test_sample_scan_status_upsert_sets_last_changed_on_upsert(session):
    upsert_sample_scan_status(
        session, "s1", now=_NOW, outcome="upserted", run_id="run-1", changed=True
    )
    session.commit()
    row = session.get(orm.SampleScanStatusORM, "s1")
    assert row.last_scanned_at == _NOW
    assert row.last_changed_at == _NOW
    assert row.last_outcome == "upserted"
    assert row.last_scan_run_id == "run-1"


def test_sample_scan_status_skip_preserves_last_changed(session):
    upsert_sample_scan_status(
        session, "s1", now=_NOW, outcome="upserted", run_id="run-1", changed=True
    )
    session.commit()
    later = _NOW + 3600.0
    upsert_sample_scan_status(
        session, "s1", now=later, outcome="skipped", run_id="run-2", changed=False
    )
    session.commit()
    row = session.get(orm.SampleScanStatusORM, "s1")
    # last_scanned advances, last_changed stays pinned to the upsert run.
    assert row.last_scanned_at == later
    assert row.last_changed_at == _NOW
    assert row.last_outcome == "skipped"


def test_acquisition_scan_status_thumbnail_transitions(session):
    # ok → records source + generated_at.
    upsert_acquisition_scan_status(
        session, "s1", "acq1", now=_NOW, outcome="upserted", run_id="run-1",
        changed=True, thumbnail_path="s1/acq1.png", thumbnail_source_kind="st",
        thumbnail_source_path="/data/x.st", thumbnail_generated_at=_NOW,
        thumbnail_status="ok",
    )
    session.commit()
    row = session.get(orm.AcquisitionScanStatusORM, ("s1", "acq1"))
    assert row.thumbnail_status == "ok"
    assert row.thumbnail_source_kind == "st"
    assert row.thumbnail_source_path == "/data/x.st"
    assert row.thumbnail_generated_at == _NOW

    # missing_source → status updated; provenance fields preserved from prior
    # (the upsert only overwrites provided non-None values).
    later = _NOW + 60.0
    upsert_acquisition_scan_status(
        session, "s1", "acq1", now=later, outcome="upserted", run_id="run-2",
        changed=True, thumbnail_status="missing_source",
    )
    session.commit()
    row = session.get(orm.AcquisitionScanStatusORM, ("s1", "acq1"))
    assert row.thumbnail_status == "missing_source"
    assert row.last_scanned_at == later


def test_acquisition_scan_status_survives_content_keyed_upsert(session):
    """The status side table is keyed by its own PK and is NOT deleted by the
    content keyed-upsert / stale-child cleanup (§3.2)."""
    acq_file = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    upsert_acquisition_scan_status(
        session, "s1", "acq1", now=_NOW, outcome="upserted", run_id="run-1",
        changed=True,
    )
    session.commit()
    # A second content upsert (same acquisition kept) must not drop the status.
    upsert_sample_record(session, r, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()
    assert session.get(orm.AcquisitionScanStatusORM, ("s1", "acq1")) is not None


# ── orphan prune (§3.2 / §9.10) ─────────────────────────────────────────────


def test_orphan_acquisition_status_and_issues_pruned_on_next_upsert(session):
    r1 = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={
            "acq1": AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1")),
            "acq2": AcquisitionFile(acquisition=Acquisition(acquisition_id="acq2")),
        },
    )
    upsert_sample_record(session, r1, extras=[], run_id="run-1", now=_NOW)
    # Status rows + an acquisition-scope issue for acq2.
    upsert_acquisition_scan_status(
        session, "s1", "acq2", now=_NOW, outcome="upserted", run_id="run-1",
        changed=True,
    )
    reconcile_sample_issues(
        session,
        "run-1",
        "s1",
        [
            _issue(
                scope="acquisition",
                acquisition_id="acq2",
                file_kind="acquisition_toml",
                location="acquisitions.acq2",
            )
        ],
        _NOW,
    )
    session.commit()
    assert session.get(orm.AcquisitionScanStatusORM, ("s1", "acq2")) is not None
    assert len(_outstanding(session)) == 1

    # Re-upsert without acq2 — its status row + acquisition-scope issue pruned.
    r2 = SampleRecord(
        sample=r1.sample,
        acquisitions={
            "acq1": AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
        },
    )
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()
    assert session.get(orm.AcquisitionScanStatusORM, ("s1", "acq2")) is None
    assert _outstanding(session) == []


def _deletion_events(session, sample_id="s1"):
    return (
        session.execute(
            select(orm.DeletionEventORM)
            .where(orm.DeletionEventORM.sample_id == sample_id)
            .order_by(orm.DeletionEventORM.id)
        )
        .scalars()
        .all()
    )


def test_deletion_event_on_stale_acquisition(session):
    acq = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1", path="/data/s1/acq1")
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq},
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()
    assert _deletion_events(session) == []

    r2 = SampleRecord(sample=r.sample, acquisitions={})
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    events = _deletion_events(session)
    assert len(events) == 1
    ev = events[0]
    assert ev.scan_run_id == "run-2"
    assert ev.detected_at == _NOW + 1
    assert ev.entity_type == "acquisition"
    assert ev.sample_id == "s1"
    assert ev.acquisition_id == "acq1"
    assert ev.entity_id is None
    assert ev.last_known_path == "/data/s1/acq1"
    snapshot = json.loads(ev.last_known_json)
    assert snapshot["acquisition_id"] == "acq1"


def test_deletion_event_on_stale_raw_tomogram(session):
    raw = RawTomogram(
        id="t_raw",
        reconstruction_alignment_id="grp1",
        mrc_path="/data/s1/acq1/raw/t_raw.mrc",
    )
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"), raw_tomogram=[raw]
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    acq_file2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    events = _deletion_events(session)
    assert len(events) == 1
    ev = events[0]
    assert ev.entity_type == "raw_tomogram"
    assert ev.acquisition_id == "acq1"
    assert ev.entity_id == "t_raw"
    assert ev.last_known_path == "/data/s1/acq1/raw/t_raw.mrc"


def test_deletion_event_on_stale_post_processed_tomogram(session):
    tomo = PostProcessedTomogram(
        id="t1",
        reconstruction_alignment_id="grp1",
        zarr_path="/data/s1/acq1/post/t1.zarr",
    )
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        post_processed_tomogram=[tomo],
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    acq_file2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    events = _deletion_events(session)
    assert len(events) == 1
    ev = events[0]
    assert ev.entity_type == "post_processed_tomogram"
    assert ev.entity_id == "t1"
    assert ev.last_known_path == "/data/s1/acq1/post/t1.zarr"


def test_deletion_event_on_stale_annotation(session):
    ann = Annotation(id="a1", reconstruction_alignment_id="grp1", files=["x.mrc"])
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"), annotation=[ann]
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    acq_file2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    events = _deletion_events(session)
    assert len(events) == 1
    ev = events[0]
    assert ev.entity_type == "annotation"
    assert ev.entity_id == "a1"
    # Annotation has no path/mrc_path/zarr_path column — no recovery path.
    assert ev.last_known_path is None
    assert json.loads(ev.last_known_json)["files"] == ["x.mrc"]


def test_deletion_event_on_stale_tilt_series(session):
    ts = TiltSeries(
        tilt_series_id="ts_a", zarr_path="/data/s1/acq1/ts/ts_a.zarr"
    )
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"), tilt_series=[ts]
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    acq_file2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    events = _deletion_events(session)
    assert len(events) == 1
    ev = events[0]
    assert ev.entity_type == "tilt_series"
    assert ev.entity_id == "ts_a"
    assert ev.last_known_path == "/data/s1/acq1/ts/ts_a.zarr"


def test_deletion_event_on_stale_md_source(session):
    sample = Sample(
        sample_id="sim1", data_source=DataSource.simulation, project=Project.chromatin
    )
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        md_source=MdSource(md_run_id="run_a", now=_NOW, frame=1),
    )
    r = SampleRecord(
        sample=sample,
        simulation=Simulation(dataset_type=DatasetType.bulk),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    acq_file2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r2 = SampleRecord(sample=sample, simulation=r.simulation, acquisitions={"acq1": acq_file2})
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    events = _deletion_events(session, sample_id="sim1")
    assert len(events) == 1
    ev = events[0]
    assert ev.entity_type == "md_source"
    assert ev.acquisition_id == "acq1"
    assert ev.entity_id is None
    # md_source has no path-like column.
    assert ev.last_known_path is None


def test_no_deletion_event_for_stale_md_run(session):
    """md_run has no §08a entity_type — its cleanup is not logged."""
    sample = Sample(
        sample_id="sim1", data_source=DataSource.simulation, project=Project.chromatin
    )
    r = SampleRecord(
        sample=sample,
        simulation=Simulation(dataset_type=DatasetType.bulk),
        md_run=[MdRun(id="run_a")],
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    r2 = SampleRecord(sample=sample, simulation=r.simulation, md_run=[])
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    assert session.get(orm.MdRunORM, ("sim1", "run_a")) is None
    assert _deletion_events(session, sample_id="sim1") == []


def test_acquisition_and_children_vanish_together_logs_per_child_no_orphan_double_count(
    session,
):
    """Deleting an acquisition + its children in one scan logs one event per
    dropped row (acquisition + each child) but the orphan acquisition-status/
    issue prune (a consequence of the acquisition's own event) is NOT logged
    separately — no double-counting (§08a acceptance criteria)."""
    raw = RawTomogram(id="t_raw", reconstruction_alignment_id="grp1")
    tomo = PostProcessedTomogram(id="t1", reconstruction_alignment_id="grp1")
    ann = Annotation(id="a1", reconstruction_alignment_id="grp1")
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        raw_tomogram=[raw],
        post_processed_tomogram=[tomo],
        annotation=[ann],
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    upsert_acquisition_scan_status(
        session, "s1", "acq1", now=_NOW, outcome="upserted", run_id="run-1",
        changed=True,
    )
    reconcile_sample_issues(
        session,
        "run-1",
        "s1",
        [
            _issue(
                scope="acquisition",
                acquisition_id="acq1",
                file_kind="acquisition_toml",
                location="acquisitions.acq1",
            )
        ],
        _NOW,
    )
    session.commit()

    # Whole acquisition (and its children) vanish in one scan.
    r2 = SampleRecord(sample=r.sample, acquisitions={})
    upsert_sample_record(session, r2, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    events = _deletion_events(session)
    by_type = {ev.entity_type: ev for ev in events}
    # One event for the acquisition + one per child — exactly 4, nothing extra
    # from the orphan status/issue prune.
    assert len(events) == 4
    assert set(by_type) == {
        "acquisition", "raw_tomogram", "post_processed_tomogram", "annotation",
    }
    assert all(ev.scan_run_id == "run-2" for ev in events)
    # The orphan-prune side effects (status row + acquisition-scope issue)
    # still happened, just without their own deletion event.
    assert session.get(orm.AcquisitionScanStatusORM, ("s1", "acq1")) is None
    assert _outstanding(session) == []


def test_soft_deleted_sample_keeps_sample_scan_status(session):
    """Samples are soft-deleted (no row DELETE), so the FK'd sample_scan_status
    row survives (§3.2/§9.10)."""
    r = _make_record()
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    upsert_sample_scan_status(
        session, "s1", now=_NOW, outcome="upserted", run_id="run-1", changed=True
    )
    session.commit()
    # Simulate soft delete.
    session.execute(
        orm.SampleORM.__table__.update()
        .where(orm.SampleORM.sample_id == "s1")
        .values(deleted_at=time.time())
    )
    session.commit()
    assert session.get(orm.SampleScanStatusORM, "s1") is not None


def _record_with_two_groups_sharing_stem() -> SampleRecord:
    """One acquisition, two Reconstructions/{id}/ groups, both holding a
    tomogram/annotation whose file stem is ``"dup"`` — legal because ids are
    only unique within their alignment group."""
    reconstructions = {
        group_id: ReconstructionFile(
            reconstruction_alignment=ReconstructionAlignment(id=group_id),
            raw_tomogram=[RawTomogram(id="dup")],
            post_processed_tomogram=[PostProcessedTomogram(id="dup_dn")],
            annotation=[Annotation(id="dup", files=[f"{group_id}/dup.mrc"])],
        )
        for group_id in ("grp_a", "grp_b")
    }
    return SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={
            "acq1": AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
        },
        reconstructions={"acq1": reconstructions},
    )


def test_same_stem_in_two_groups_persists_as_two_rows(session):
    """Two alignment groups holding the same tomogram stem produce two rows,
    not one overwritten row."""
    r = _record_with_two_groups_sharing_stem()
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()

    raws = session.execute(select(orm.RawTomogramORM)).scalars().all()
    assert len(raws) == 2
    assert {t.reconstruction_alignment_id for t in raws} == {"grp_a", "grp_b"}
    assert {t.tomogram_id for t in raws} == {"dup"}

    anns = session.execute(select(orm.AnnotationORM)).scalars().all()
    assert len(anns) == 2
    assert {a.reconstruction_alignment_id for a in anns} == {"grp_a", "grp_b"}
    assert {a.annotation_id for a in anns} == {"dup"}


def test_reupsert_does_not_prune_group_scoped_rows(session):
    """The keep-set and the prune key must agree on arity, or a second scan
    deletes every row it just wrote."""
    r = _record_with_two_groups_sharing_stem()
    upsert_sample_record(session, r, extras=[], run_id="run-1", now=_NOW)
    session.commit()
    upsert_sample_record(session, r, extras=[], run_id="run-2", now=_NOW + 1)
    session.commit()

    assert len(session.execute(select(orm.RawTomogramORM)).scalars().all()) == 2
    assert (
        len(
            session.execute(select(orm.PostProcessedTomogramORM)).scalars().all()
        )
        == 2
    )
    assert len(session.execute(select(orm.AnnotationORM)).scalars().all()) == 2
    # No row was dropped and re-added: nothing in the §08a deletion feed.
    assert _deletion_events(session) == []
