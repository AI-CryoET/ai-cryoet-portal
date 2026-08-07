"""End-to-end scanner tests against the fixture sample tree."""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from catalog import db, discovery, orm, scanner

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine():
    eng = db.make_engine("sqlite:///:memory:")
    db.init_schema(eng)
    return eng


def _session(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _write_minimal_sample(parent: Path, sample_id: str) -> Path:
    """Write the smallest legal sample.toml under the Experimental arm of
    ``parent`` (i.e. ``parent/Experimental/sample_id``).

    Centralised so a schema rev to ``[sample]`` only touches one place. The
    sample lives under ``Experimental/`` so the two-arm discovery walk finds it
    and ``infer_arm`` assigns ``data_source=experimental``.
    """
    d = parent / "Experimental" / sample_id
    d.mkdir(parents=True)
    (d / "sample.toml").write_text(
        '[sample]\ndata_source = "experimental"\nproject = "chromatin"\n'
    )
    return d


def test_scan_fixture_root_happy_path(engine):
    report = scanner.scan_root(engine, FIXTURES)
    assert report.upserted == 2  # sample_chromatin + sample_simulation
    assert report.skipped == 0
    assert report.errors == []

    s = _session(engine)
    try:
        # Both sample rows present
        sample_ids = {
            row[0] for row in s.execute(select(orm.SampleORM.sample_id)).all()
        }
        assert sample_ids == {"sample_chromatin", "SingleMolecule_sample_simulation"}

        # Position_86 + Position_87 acquisitions present
        acqs = (
            s.execute(
                select(orm.AcquisitionORM).where(
                    orm.AcquisitionORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        assert {a.acquisition_id for a in acqs} == {"Position_86", "Position_87"}

        # Raw tomogram row written (sample_chromatin fixture uses [raw_tomogram])
        # with MRC + zarr-derived dimensions populated by the assembler.
        tomos = (
            s.execute(
                select(orm.RawTomogramORM).where(
                    orm.RawTomogramORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        assert {t.tomogram_id for t in tomos} == {"bp_3dctf_bin4"}
        tomo = tomos[0]
        assert tomo.image_size_x == 4
        assert tomo.mrc_path is not None
        assert tomo.zarr_path is not None

        # Annotation row populated with discovered files
        anns = (
            s.execute(
                select(orm.AnnotationORM).where(
                    orm.AnnotationORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        assert len(anns) == 1
        assert any(p.endswith("membrain_seg_v10.mrc") for p in anns[0].files)

        # scan_runs row written, status='completed'
        scans = s.execute(select(orm.ScanRunORM)).scalars().all()
        assert len(scans) == 1
        assert scans[0].status == "completed"
        assert scans[0].n_upserted == 2

        # catalog_meta row reflects the root we just scanned
        meta = s.get(orm.CatalogMetaORM, 1)
        assert meta is not None
        assert meta.data_root == str(FIXTURES.resolve())

        # issues: at least one outstanding for Position_87 (missing_acquisition_toml)
        issues = (
            s.execute(
                select(orm.IssueORM).where(
                    orm.IssueORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        categories = {w.category for w in issues}
        assert "missing_acquisition_toml" in categories
        # Reconciled this run: first/last-seen run ids match the single run.
        run_ids = {w.first_seen_run_id for w in issues} | {
            w.last_seen_run_id for w in issues
        }
        assert run_ids == {scans[0].scan_run_id}
        # All freshly-seen issues are outstanding (resolved_at IS NULL).
        assert all(w.resolved_at is None for w in issues)
    finally:
        s.close()


def test_second_scan_skips_unchanged_samples(engine):
    scanner.scan_root(engine, FIXTURES)
    report2 = scanner.scan_root(engine, FIXTURES)
    assert report2.upserted == 0
    assert report2.skipped == 2
    assert report2.errors == []


def test_force_bypasses_gate(engine):
    scanner.scan_root(engine, FIXTURES)
    report = scanner.scan_root(engine, FIXTURES, force=True)
    assert report.upserted == 2
    assert report.skipped == 0


def test_touched_file_triggers_reassemble(engine):
    scanner.scan_root(engine, FIXTURES)
    target = FIXTURES / "Experimental" / "sample_chromatin" / "sample.toml"
    original_mtime = target.stat().st_mtime
    new_mtime = original_mtime + 100
    os.utime(target, (new_mtime, new_mtime))
    try:
        report = scanner.scan_root(engine, FIXTURES)
        # sample_chromatin should be re-assembled, sample_simulation skipped
        assert report.upserted >= 1
        assert report.skipped >= 1
    finally:
        # Restore mtime so other tests aren't affected
        os.utime(target, (original_mtime, original_mtime))


def test_two_scans_make_two_scan_runs_rows(engine):
    scanner.scan_root(engine, FIXTURES)
    scanner.scan_root(engine, FIXTURES)
    s = _session(engine)
    try:
        scans = s.execute(select(orm.ScanRunORM)).scalars().all()
        assert len(scans) == 2
        assert all(sc.status == "completed" for sc in scans)
    finally:
        s.close()


def test_skipped_sample_leaves_issues_outstanding(engine):
    """A sample skipped on the second scan keeps its outstanding issues with an
    unchanged last_seen (the scanner does NOT reconcile a skipped sample, §4.4)."""
    scanner.scan_root(engine, FIXTURES)
    s = _session(engine)
    try:
        issues = (
            s.execute(
                select(orm.IssueORM).where(
                    orm.IssueORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        assert issues
        first_run_ids = {w.last_seen_run_id for w in issues}
    finally:
        s.close()

    # Second scan skips everything (nothing changed on disk).
    report2 = scanner.scan_root(engine, FIXTURES)
    assert report2.skipped == 2

    s = _session(engine)
    try:
        issues = (
            s.execute(
                select(orm.IssueORM).where(
                    orm.IssueORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        # Still outstanding, and last_seen still points at the FIRST run (the
        # skipped sample was not re-evaluated).
        assert all(w.resolved_at is None for w in issues)
        assert {w.last_seen_run_id for w in issues} == first_run_ids
    finally:
        s.close()


def test_freshness_status_written_on_upsert_and_skip(engine):
    """sample_scan_status records last_changed on upsert; a later skip advances
    last_scanned but preserves last_changed (§4.5)."""
    scanner.scan_root(engine, FIXTURES)
    s = _session(engine)
    try:
        row = s.get(orm.SampleScanStatusORM, "sample_chromatin")
        assert row is not None
        assert row.last_outcome == "upserted"
        assert row.last_changed_at is not None
        first_changed = row.last_changed_at
        first_scanned = row.last_scanned_at
    finally:
        s.close()

    scanner.scan_root(engine, FIXTURES)  # skip
    s = _session(engine)
    try:
        row = s.get(orm.SampleScanStatusORM, "sample_chromatin")
        assert row.last_outcome == "skipped"
        assert row.last_changed_at == first_changed  # preserved
        assert row.last_scanned_at >= first_scanned  # advanced (or equal)
    finally:
        s.close()


def test_prune_dry_run_reports_without_writing(engine, tmp_path):
    _write_minimal_sample(tmp_path, "sample_a")
    sample_b = _write_minimal_sample(tmp_path, "sample_b")

    scanner.scan_root(engine, tmp_path)

    # Now remove sample_b on disk
    (sample_b / "sample.toml").unlink()
    sample_b.rmdir()

    # Dry run prune
    report = scanner.scan_root(
        engine,
        tmp_path,
        prune=False,
        prune_dry_run=True,
        prune_safety_floor=1.0,
    )
    assert report.would_soft_delete == ["sample_b"]

    # sample_b is NOT actually soft-deleted yet
    s = _session(engine)
    try:
        b = s.get(orm.SampleORM, "sample_b")
        assert b is not None
        assert b.deleted_at is None
    finally:
        s.close()


def test_prune_actually_soft_deletes(engine, tmp_path):
    _write_minimal_sample(tmp_path, "sample_a")
    sample_b = _write_minimal_sample(tmp_path, "sample_b")

    scanner.scan_root(engine, tmp_path)

    # Remove sample_b
    (sample_b / "sample.toml").unlink()
    sample_b.rmdir()

    report = scanner.scan_root(
        engine, tmp_path, prune=True, prune_safety_floor=1.0
    )
    assert report.soft_deleted == 1

    s = _session(engine)
    try:
        b = s.get(orm.SampleORM, "sample_b")
        assert b is not None
        assert b.deleted_at is not None
    finally:
        s.close()


def test_resurrected_sample_reassembled_even_if_unchanged(engine, tmp_path):
    _write_minimal_sample(tmp_path, "sample_a")

    # First scan
    scanner.scan_root(engine, tmp_path)

    # Mark soft-deleted manually (simulates a prior prune)
    s = _session(engine)
    try:
        s.execute(
            orm.SampleORM.__table__.update()
            .where(orm.SampleORM.sample_id == "sample_a")
            .values(deleted_at=time.time())
        )
        s.commit()
    finally:
        s.close()

    # Re-scan: file is unchanged on disk so the gate would normally skip,
    # but soft-deleted samples must be re-assembled to clear the tombstone.
    report = scanner.scan_root(engine, tmp_path)
    assert report.upserted == 1
    assert report.skipped == 0

    s = _session(engine)
    try:
        a = s.get(orm.SampleORM, "sample_a")
        assert a is not None
        assert a.deleted_at is None  # resurrected
    finally:
        s.close()


def test_failed_scan_marks_status_failed(engine, tmp_path):
    sample_a = _write_minimal_sample(tmp_path, "sample_a")

    # First scan succeeds.
    scanner.scan_root(engine, tmp_path)

    # Rename the sample dir so the on-disk sample_id changes; the original
    # sample_a row in the DB now has no fs match. With safety_floor=0.0 the
    # prune step will exceed the floor and raise.
    sample_a.rename(tmp_path / "renamed_a")

    with pytest.raises(Exception):
        scanner.scan_root(
            engine, tmp_path, prune=True, prune_safety_floor=0.0
        )

    s = _session(engine)
    try:
        scans = (
            s.execute(
                select(orm.ScanRunORM).order_by(orm.ScanRunORM.started_at.desc())
            )
            .scalars()
            .all()
        )
        # Most recent scan should be 'failed'
        assert scans[0].status == "failed"
    finally:
        s.close()


def test_crashed_run_does_not_resolve_run_scope_issues(engine, tmp_path):
    """A run that ends non-`completed` must NOT resolve run-scope issues (§9.6):
    the crashed run may not have finished discovery."""
    # First scan: a bogus MdSimulation subdir emits a run-scope issue.
    bogus = tmp_path / "MdSimulation" / "NotADatasetType" / "s1"
    bogus.mkdir(parents=True)
    (bogus / "sample.toml").write_text(
        '[sample]\ndata_source = "simulation"\nproject = "chromatin"\n'
    )
    _write_minimal_sample(tmp_path, "exp1")
    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        run_issues = (
            s.execute(
                select(orm.IssueORM).where(orm.IssueORM.scope == "run")
            )
            .scalars()
            .all()
        )
        assert len(run_issues) == 1
        assert run_issues[0].resolved_at is None
    finally:
        s.close()

    # Second scan crashes (prune floor exceeded) BEFORE the run-scope reconcile.
    sample_a = tmp_path / "Experimental" / "exp1"
    sample_a.rename(tmp_path / "Experimental" / "renamed")
    with pytest.raises(Exception):
        scanner.scan_root(engine, tmp_path, prune=True, prune_safety_floor=0.0)

    s = _session(engine)
    try:
        # The run-scope issue is still outstanding — a crashed run leaves it be.
        run_issues = (
            s.execute(
                select(orm.IssueORM).where(orm.IssueORM.scope == "run")
            )
            .scalars()
            .all()
        )
        assert len(run_issues) == 1
        assert run_issues[0].resolved_at is None
    finally:
        s.close()


def test_scan_populates_disk_size_bytes(engine, tmp_path):
    sample_dir = _write_minimal_sample(tmp_path, "sample_a")
    # Add a file with a known size so dir_size_bytes returns something non-zero.
    (sample_dir / "data.bin").write_bytes(b"x" * 1024)

    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        assert row.disk_size_bytes is not None
        assert row.disk_size_bytes == discovery.dir_size_bytes(sample_dir)
    finally:
        s.close()


def test_skip_preserves_disk_size_bytes(engine, tmp_path):
    sample_dir = _write_minimal_sample(tmp_path, "sample_a")
    (sample_dir / "data.bin").write_bytes(b"x" * 1024)

    # First scan: populates disk_size_bytes.
    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        original_size = row.disk_size_bytes
        assert original_size is not None
    finally:
        s.close()

    # Second scan: nothing changed on disk, so the mtime gate skips the sample.
    report2 = scanner.scan_root(engine, tmp_path)
    assert report2.skipped >= 1

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        assert row.disk_size_bytes == original_size
    finally:
        s.close()


def test_force_recomputes_disk_size_bytes(engine, tmp_path):
    sample_dir = _write_minimal_sample(tmp_path, "sample_a")
    (sample_dir / "data.bin").write_bytes(b"x" * 1024)

    # First scan.
    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        first_size = row.disk_size_bytes
        assert first_size is not None
    finally:
        s.close()

    # Add a new file to increase the on-disk size.
    extra_file = sample_dir / "extra.bin"
    extra_file.write_bytes(b"y" * 512)
    extra_bytes = extra_file.stat().st_size

    # Re-scan with force=True so it re-assembles and recomputes size.
    scanner.scan_root(engine, tmp_path, force=True)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        assert row.disk_size_bytes is not None
        assert row.disk_size_bytes >= first_size + extra_bytes
    finally:
        s.close()


# ── thumbnail tests ───────────────────────────────────────────────────────────

_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _fake_render_one(ref, dest: Path):
    """Patch target: writes fake PNG bytes to dest and returns the new
    ``(ok, source_kind, source_path)`` triple (§4.5)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_FAKE_PNG)
    kind = "zarr" if ref.zarr_path else "st" if ref.st_path else "frames"
    path = ref.zarr_path or ref.st_path or ref.frames_dir
    return True, kind, path


def test_scan_with_thumbnail_dir_populates_thumbnail_path(engine, tmp_path):
    sample_dir = _write_minimal_sample(tmp_path, "sample_a")
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()

    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one):
        scanner.scan_root(engine, tmp_path, thumbnail_dir=thumb_dir)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        # No tomograms in the minimal sample, so thumbnail_path may be None —
        # but the column must exist and not error. If somehow a relpath was
        # generated it must also exist on disk.
        if row.thumbnail_path is not None:
            assert (thumb_dir / row.thumbnail_path).is_file()
    finally:
        s.close()


def test_scan_without_thumbnail_dir_leaves_thumbnail_path_null(engine, tmp_path):
    _write_minimal_sample(tmp_path, "sample_a")

    scanner.scan_root(engine, tmp_path, thumbnail_dir=None)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        assert row.thumbnail_path is None
    finally:
        s.close()

    # No PNG files written anywhere under tmp_path
    png_files = list(tmp_path.rglob("*.png"))
    assert png_files == []


def test_scan_with_thumbnail_dir_fixture_tree_writes_file(engine, tmp_path):
    """Scan the fixture tree (has real MRC data) with a thumbnail_dir.

    Patches _render_one so no real MRC rendering is needed.
    """
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()

    FIXTURES = Path(__file__).parent / "fixtures"

    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one):
        report = scanner.scan_root(engine, FIXTURES, thumbnail_dir=thumb_dir)

    assert report.errors == []

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_chromatin")
        assert row is not None
        # sample_chromatin has a raw tomogram so a thumbnail should be generated.
        assert row.thumbnail_path is not None
        assert (thumb_dir / row.thumbnail_path).is_file()
    finally:
        s.close()


def test_scan_force_rerenders_thumbnails(engine, tmp_path):
    """Force re-scan calls _render_one again even when thumbnail already exists."""
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()

    FIXTURES = Path(__file__).parent / "fixtures"

    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one) as mock_render:
        scanner.scan_root(engine, FIXTURES, thumbnail_dir=thumb_dir)
        first_call_count = mock_render.call_count

    # Force re-scan — should re-render (skip_existing=False on upsert path).
    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one) as mock_render2:
        scanner.scan_root(engine, FIXTURES, thumbnail_dir=thumb_dir, force=True)
        second_call_count = mock_render2.call_count

    # Both scans should have called render (force bypasses skip_existing).
    assert first_call_count > 0
    assert second_call_count > 0


def test_auto_heal_on_skip(engine, tmp_path):
    """If thumbnail file is deleted and the sample is skipped, it is re-created."""
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()

    FIXTURES = Path(__file__).parent / "fixtures"

    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one):
        scanner.scan_root(engine, FIXTURES, thumbnail_dir=thumb_dir)

    # Confirm a thumbnail was stored.
    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_chromatin")
        assert row is not None
        rel = row.thumbnail_path
        assert rel is not None
    finally:
        s.close()

    # Delete the thumbnail file from disk.
    thumb_file = thumb_dir / rel
    assert thumb_file.is_file()
    thumb_file.unlink()
    assert not thumb_file.exists()

    # Re-scan without force — mtime gate skips, but auto-heal restores file.
    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one):
        report = scanner.scan_root(engine, FIXTURES, thumbnail_dir=thumb_dir)

    assert report.thumbnails_healed >= 1
    assert thumb_file.is_file()


def test_scan_records_thumbnail_provenance_in_acq_status(engine, tmp_path):
    """On upsert the scanner writes the rendered source provenance + status to
    acquisition_scan_status (§4.5)."""
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()

    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one):
        scanner.scan_root(engine, FIXTURES, thumbnail_dir=thumb_dir)

    s = _session(engine)
    try:
        # sample_chromatin/Position_86 renders from its Frames/ dir.
        row = s.get(
            orm.AcquisitionScanStatusORM, ("sample_chromatin", "Position_86")
        )
        assert row is not None
        assert row.last_outcome == "upserted"
        assert row.thumbnail_status == "ok"
        assert row.thumbnail_source_kind in {"zarr", "st", "frames"}
        assert row.thumbnail_source_path is not None
        assert row.thumbnail_generated_at is not None
    finally:
        s.close()


def test_skip_no_heal_when_file_present(engine, tmp_path):
    """Second scan that skips should not re-render if thumbnail file is present."""
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()

    FIXTURES = Path(__file__).parent / "fixtures"

    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one):
        scanner.scan_root(engine, FIXTURES, thumbnail_dir=thumb_dir)

    # Second scan — nothing changed, thumbnail file still present.
    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one) as mock_render:
        report = scanner.scan_root(engine, FIXTURES, thumbnail_dir=thumb_dir)

    assert report.thumbnails_healed == 0
    mock_render.assert_not_called()


def test_scan_emits_and_persists_run_level_issue(engine, tmp_path):
    # A sample dropped under an unrecognized MdSimulation/ subdir is skipped by
    # discovery; the scanner surfaces it as a run-scope issue and persists it
    # to the issues table (scope='run', no owning sample).
    bogus = tmp_path / "MdSimulation" / "NotADatasetType" / "s1"
    bogus.mkdir(parents=True)
    (bogus / "sample.toml").write_text(
        '[sample]\ndata_source = "simulation"\nproject = "chromatin"\n'
    )
    # A legitimate sample so the scan has real work too.
    _write_minimal_sample(tmp_path, "exp1")

    report = scanner.scan_root(engine, tmp_path)

    # The bogus subdir never becomes a sample.
    assert report.upserted == 1
    assert [w.category for w in report.run_issues] == [
        "unknown_md_simulation_subdir"
    ]
    assert "NotADatasetType" in report.run_issues[0].location

    s = _session(engine)
    try:
        rows = (
            s.execute(select(orm.IssueORM).where(orm.IssueORM.scope == "run"))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.category == "unknown_md_simulation_subdir"
        assert "NotADatasetType" in row.location
        assert row.sample_id is None
        assert row.file_kind == "filesystem"
        assert row.resolved_at is None
        # Tied to a real scan run.
        scan_ids = {
            r[0] for r in s.execute(select(orm.ScanRunORM.scan_run_id)).all()
        }
        assert row.last_seen_run_id in scan_ids
    finally:
        s.close()


def test_scan_emits_run_issue_for_sample_outside_arm(engine, tmp_path):
    # A sample placed under a non-arm top-level dir (root/{other}/{sample}/) is
    # never discovered; the scanner surfaces and persists a run-scope issue.
    misplaced = tmp_path / "Experiemntal" / "s1"  # typo'd arm name
    misplaced.mkdir(parents=True)
    (misplaced / "sample.toml").write_text(
        '[sample]\nproject = "chromatin"\n'
    )
    # A legitimate sample so the scan has real work too.
    _write_minimal_sample(tmp_path, "exp1")

    report = scanner.scan_root(engine, tmp_path)

    # The misplaced sample never becomes a catalogued sample.
    assert report.upserted == 1
    assert [w.category for w in report.run_issues] == ["sample_outside_arm"]
    assert "s1" in report.run_issues[0].location

    s = _session(engine)
    try:
        rows = (
            s.execute(select(orm.IssueORM).where(orm.IssueORM.scope == "run"))
            .scalars()
            .all()
        )
        assert [r.category for r in rows] == ["sample_outside_arm"]
        assert "s1" in rows[0].location
    finally:
        s.close()


def test_scan_clean_root_has_no_run_issues(engine):
    report = scanner.scan_root(engine, FIXTURES)
    assert report.run_issues == []
    s = _session(engine)
    try:
        rows = (
            s.execute(select(orm.IssueORM).where(orm.IssueORM.scope == "run"))
            .scalars()
            .all()
        )
        assert rows == []
    finally:
        s.close()


# ── log capture (§4.3 / §9.11) ──────────────────────────────────────────────


def test_scan_persists_log_lines_with_sample_context_and_seq(engine, tmp_path):
    """Log lines are bulk-inserted once at run end, carry sample_id context for
    per-sample lines, and have a monotonic seq."""
    _write_minimal_sample(tmp_path, "exp1")
    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        rows = (
            s.execute(
                select(orm.ScanLogLineORM).order_by(orm.ScanLogLineORM.seq)
            )
            .scalars()
            .all()
        )
        assert rows, "expected persisted log lines"
        # Monotonic, strictly increasing seq.
        seqs = [r.seq for r in rows]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
        # All lines belong to the single run.
        run_ids = {r.scan_run_id for r in rows}
        assert len(run_ids) == 1
        # The per-sample "[1/1] exp1" line carries sample_id context.
        per_sample = [r for r in rows if r.sample_id == "exp1"]
        assert per_sample, "expected at least one line bound to sample_id=exp1"
    finally:
        s.close()


def test_scan_log_retention_prunes_old_runs(engine, tmp_path, monkeypatch):
    """SCAN_LOG_RETENTION_RUNS bounds how many runs keep their log lines; older
    runs keep their scan_runs row but lose their log lines."""
    _write_minimal_sample(tmp_path, "exp1")
    monkeypatch.setenv("SCAN_LOG_RETENTION_RUNS", "1")

    scanner.scan_root(engine, tmp_path)  # run 1
    scanner.scan_root(engine, tmp_path, force=True)  # run 2

    s = _session(engine)
    try:
        # Two scan_runs rows survive; only the most-recent run's log lines remain.
        scan_runs = s.execute(select(orm.ScanRunORM)).scalars().all()
        assert len(scan_runs) == 2
        log_run_ids = {
            r[0]
            for r in s.execute(
                select(orm.ScanLogLineORM.scan_run_id).distinct()
            ).all()
        }
        assert len(log_run_ids) == 1
    finally:
        s.close()


def test_crashed_scan_persists_partial_log_and_failed_status(engine, tmp_path):
    """A crashed scan still records its buffered partial log + failed status via
    the except path (§9.11)."""
    _write_minimal_sample(tmp_path, "exp1")
    scanner.scan_root(engine, tmp_path)
    # Force a crash by renaming the only sample and pruning with floor 0.
    (tmp_path / "Experimental" / "exp1").rename(tmp_path / "Experimental" / "gone")
    with pytest.raises(Exception):
        scanner.scan_root(engine, tmp_path, prune=True, prune_safety_floor=0.0)

    s = _session(engine)
    try:
        latest = (
            s.execute(
                select(orm.ScanRunORM).order_by(orm.ScanRunORM.started_at.desc())
            )
            .scalars()
            .first()
        )
        assert latest.status == "failed"
        # Partial log lines from the crashed run were still persisted.
        rows = (
            s.execute(
                select(orm.ScanLogLineORM).where(
                    orm.ScanLogLineORM.scan_run_id == latest.scan_run_id
                )
            )
            .scalars()
            .all()
        )
        assert rows, "expected partial log lines for the crashed run"
    finally:
        s.close()


def _write_acquisition(sample_dir: Path, acq_id: str) -> Path:
    """Write the smallest legal acquisition.toml under ``sample_dir / acq_id``."""
    d = sample_dir / acq_id
    d.mkdir(parents=True)
    (d / "acquisition.toml").write_text('[acquisition]\nmicroscope = "Krios"\n')
    return d


def test_child_prune_safety_floor_fails_only_that_sample(engine, tmp_path):
    """§08b: a sample that loses most of its acquisitions in one scan aborts
    *that sample's* upsert with ChildPruneSafetyFloorExceeded — recorded
    failed, no rows deleted for it — while an unrelated healthy sample in the
    same run still upserts normally (the failure's blast radius is one
    sample, not the whole run)."""
    sample_a = _write_minimal_sample(tmp_path, "sample_a")
    for acq_id in ("acq1", "acq2", "acq3", "acq4"):
        _write_acquisition(sample_a, acq_id)
    _write_minimal_sample(tmp_path, "sample_b")

    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        assert (
            len(
                s.execute(
                    select(orm.AcquisitionORM).where(
                        orm.AcquisitionORM.sample_id == "sample_a"
                    )
                )
                .scalars()
                .all()
            )
            == 4
        )
    finally:
        s.close()

    # Drop 3 of 4 acquisitions on disk: 75% > the default 50% floor, and 4 >=
    # the default min-count of 3, so this must trip.
    import shutil

    shutil.rmtree(sample_a / "acq2")
    shutil.rmtree(sample_a / "acq3")
    shutil.rmtree(sample_a / "acq4")

    report = scanner.scan_root(engine, tmp_path, force=True)

    assert [sid for sid, _ in report.failed_samples] == ["sample_a"]
    assert "sample_b" in report.upserted_ids

    s = _session(engine)
    try:
        acqs = (
            s.execute(
                select(orm.AcquisitionORM).where(
                    orm.AcquisitionORM.sample_id == "sample_a"
                )
            )
            .scalars()
            .all()
        )
        assert len(acqs) == 4, "the failed sample's transaction must roll back"
        assert (
            s.execute(select(orm.DeletionEventORM)).scalars().all() == []
        ), "no deletion events for a floor-aborted upsert"
        latest = (
            s.execute(
                select(orm.ScanRunORM).order_by(orm.ScanRunORM.started_at.desc())
            )
            .scalars()
            .first()
        )
        # Per-sample failures are isolated — the run as a whole still completes.
        assert latest.status == "completed"
    finally:
        s.close()


def test_child_prune_safety_floor_configurable_from_cli_kwargs(engine, tmp_path):
    """Relaxing --child-prune-safety-floor / --child-prune-min-count lets a
    scan that would otherwise trip the default floor go through."""
    sample_a = _write_minimal_sample(tmp_path, "sample_a")
    for acq_id in ("acq1", "acq2", "acq3", "acq4"):
        _write_acquisition(sample_a, acq_id)
    scanner.scan_root(engine, tmp_path)

    import shutil

    shutil.rmtree(sample_a / "acq2")
    shutil.rmtree(sample_a / "acq3")
    shutil.rmtree(sample_a / "acq4")

    report = scanner.scan_root(
        engine,
        tmp_path,
        force=True,
        child_prune_safety_floor=0.9,
    )
    assert report.failed_samples == []
    assert "sample_a" in report.upserted_ids

    s = _session(engine)
    try:
        acqs = (
            s.execute(
                select(orm.AcquisitionORM).where(
                    orm.AcquisitionORM.sample_id == "sample_a"
                )
            )
            .scalars()
            .all()
        )
        assert len(acqs) == 1
    finally:
        s.close()


# ─── §08c `renamed_from` hint (end-to-end via scan_root) ──────────────────────


def test_sample_rename_hint_suppresses_deletion_and_carries_continuity(
    engine, tmp_path
):
    """Renaming a sample directory and authoring `renamed_from` in the new
    sample.toml suppresses the old id's ordinary §08a deletion event (a
    rename event is recorded instead) and carries
    sample_scan_status.last_changed_at from the old row onto the new one —
    the continuity-stamp wiring only scanner.py has enough context to do
    (upsert_sample_record's rename-info return value threaded through)."""
    import shutil

    sample_a = _write_minimal_sample(tmp_path, "sample_a")
    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        old_status = s.get(orm.SampleScanStatusORM, "sample_a")
        assert old_status is not None
        old_last_changed = old_status.last_changed_at
    finally:
        s.close()

    renamed_dir = tmp_path / "Experimental" / "sample_a_renamed"
    shutil.move(str(sample_a), str(renamed_dir))
    (renamed_dir / "sample.toml").write_text(
        '[sample]\ndata_source = "experimental"\nproject = "chromatin"\n'
        'renamed_from = "sample_a"\n'
    )

    report = scanner.scan_root(engine, tmp_path, prune=True)
    assert "sample_a_renamed" in report.upserted_ids
    assert report.errors == []

    s = _session(engine)
    try:
        # Old row still soft-deletes as usual — no PK rewrite.
        old_sample = s.get(orm.SampleORM, "sample_a")
        assert old_sample is not None and old_sample.deleted_at is not None
        new_sample = s.get(orm.SampleORM, "sample_a_renamed")
        assert new_sample is not None and new_sample.deleted_at is None

        events = s.execute(select(orm.DeletionEventORM)).scalars().all()
        assert len(events) == 1, "no ordinary deletion event for sample_a"
        assert events[0].kind == "rename"
        assert events[0].entity_type == "sample"
        assert events[0].sample_id == "sample_a_renamed"

        new_status = s.get(orm.SampleScanStatusORM, "sample_a_renamed")
        assert new_status is not None
        assert new_status.last_changed_at == old_last_changed
    finally:
        s.close()


def test_acquisition_rename_hint_carries_scan_status_continuity(engine, tmp_path):
    """Same as the sample-level test, one level down: renaming an
    acquisition directory + `renamed_from` in acquisition.toml suppresses the
    old acquisition's deletion event, records a rename event, and carries
    acquisition_scan_status.last_changed_at forward."""
    import shutil

    sample_a = _write_minimal_sample(tmp_path, "sample_a")
    _write_acquisition(sample_a, "acq1")
    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        old_status = s.get(orm.AcquisitionScanStatusORM, ("sample_a", "acq1"))
        assert old_status is not None
        old_last_changed = old_status.last_changed_at
    finally:
        s.close()

    shutil.move(str(sample_a / "acq1"), str(sample_a / "acq1_renamed"))
    (sample_a / "acq1_renamed" / "acquisition.toml").write_text(
        '[acquisition]\nmicroscope = "Krios"\nrenamed_from = "acq1"\n'
    )

    report = scanner.scan_root(engine, tmp_path, force=True)
    assert "sample_a" in report.upserted_ids
    assert report.errors == []

    s = _session(engine)
    try:
        acq_ids = {
            a.acquisition_id
            for a in s.execute(
                select(orm.AcquisitionORM).where(
                    orm.AcquisitionORM.sample_id == "sample_a"
                )
            )
            .scalars()
            .all()
        }
        assert acq_ids == {"acq1_renamed"}

        events = s.execute(select(orm.DeletionEventORM)).scalars().all()
        assert len(events) == 1, "no ordinary deletion event for acq1"
        assert events[0].kind == "rename"
        assert events[0].entity_type == "acquisition"
        assert events[0].acquisition_id == "acq1_renamed"

        new_status = s.get(
            orm.AcquisitionScanStatusORM, ("sample_a", "acq1_renamed")
        )
        assert new_status is not None
        assert new_status.last_changed_at == old_last_changed
    finally:
        s.close()


# ── MD-run OVITO previews ─────────────────────────────────────────────────────
# The OVITO render is patched out (it needs the heavy ``ovito`` dependency, only
# present in the ``catalog`` pixi feature); these assert the scanner → md_previews
# → persistence wiring end-to-end. Samples under MdSimulation/SingleMolecule/ get
# a dataset-type-prefixed sample_id ("SingleMolecule_<folder>"), so preview paths
# and MdRun PKs are keyed by that prefixed id.

# Patch target: the lazily-imported renderer inside md_previews._render_one.
_MD_RENDER_TARGET = "catalog.imaging._md_render.render_md_dump_preview"


def _fake_md_render(dump_path, output_path: Path, **kwargs) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_FAKE_PNG)
    return output_path


def _write_simulation_md_sample(
    parent: Path, folder: str, run_id: str = "run_001"
) -> str:
    """Write a simulation sample with one MD run carrying a Trajectories dump.

    Layout: ``MdSimulation/SingleMolecule/{folder}/MdRuns/{run}/Trajectories/dna.dump``.
    Returns the *discovered* sample_id ("SingleMolecule_{folder}").
    """
    sample_dir = parent / "MdSimulation" / "SingleMolecule" / folder
    traj = sample_dir / "MdRuns" / run_id / "Trajectories"
    traj.mkdir(parents=True)
    (sample_dir / "sample.toml").write_text(
        '[sample]\ndata_source = "simulation"\nproject = "chromatin"\n'
    )
    (sample_dir / "MdRuns" / run_id / "md_run.toml").write_text("seed = 1\n")
    (traj / "dna.dump").write_text("ITEM: ATOMS id type xu yu zu\n")
    return f"SingleMolecule_{folder}"


def test_scan_with_md_preview_dir_populates_preview_path(engine, tmp_path):
    sample_id = _write_simulation_md_sample(tmp_path, "sim_a", "run_001")
    preview_dir = tmp_path / "md_previews"

    with patch(_MD_RENDER_TARGET, side_effect=_fake_md_render):
        scanner.scan_root(engine, tmp_path, md_preview_dir=preview_dir)

    s = _session(engine)
    try:
        row = s.get(orm.MdRunORM, (sample_id, "run_001"))
        assert row is not None
        assert row.preview_path == f"{sample_id}/run_001.png"
    finally:
        s.close()
    # Preview PNG written at the persisted relpath (what /md-previews serves).
    assert (preview_dir / sample_id / "run_001.png").is_file()


def test_scan_without_md_preview_dir_leaves_preview_path_null(engine, tmp_path):
    sample_id = _write_simulation_md_sample(tmp_path, "sim_a", "run_001")

    scanner.scan_root(engine, tmp_path, md_preview_dir=None)

    s = _session(engine)
    try:
        row = s.get(orm.MdRunORM, (sample_id, "run_001"))
        assert row is not None
        assert row.preview_path is None
    finally:
        s.close()
    assert list(tmp_path.rglob("*.png")) == []


def test_scan_heals_missing_md_preview_on_skip(engine, tmp_path):
    sample_id = _write_simulation_md_sample(tmp_path, "sim_a", "run_001")
    preview_dir = tmp_path / "md_previews"

    with patch(_MD_RENDER_TARGET, side_effect=_fake_md_render):
        scanner.scan_root(engine, tmp_path, md_preview_dir=preview_dir)
    preview = preview_dir / sample_id / "run_001.png"
    assert preview.is_file()

    # Delete the PNG; a second (unchanged → skipped) scan should heal it.
    preview.unlink()
    with patch(_MD_RENDER_TARGET, side_effect=_fake_md_render):
        report = scanner.scan_root(engine, tmp_path, md_preview_dir=preview_dir)

    assert report.skipped == 1
    assert report.md_previews_healed == 1
    assert preview.is_file()


def test_skip_no_md_heal_when_preview_present(engine, tmp_path):
    _write_simulation_md_sample(tmp_path, "sim_a", "run_001")
    preview_dir = tmp_path / "md_previews"

    with patch(_MD_RENDER_TARGET, side_effect=_fake_md_render):
        scanner.scan_root(engine, tmp_path, md_preview_dir=preview_dir)

    # Second scan — nothing changed, preview still present → no re-render.
    with patch(_MD_RENDER_TARGET, side_effect=_fake_md_render) as mock_render:
        report = scanner.scan_root(engine, tmp_path, md_preview_dir=preview_dir)

    assert report.md_previews_healed == 0
    mock_render.assert_not_called()
