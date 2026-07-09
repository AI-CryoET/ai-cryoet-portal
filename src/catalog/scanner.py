"""Scanner orchestrator.

scan_root walks the data root, runs the gating check, dispatches per-sample
to the assembler + persistence layer inside a transaction, and tracks the
overall run via the `scan_runs` table (one row per invocation, status running/
completed/failed) and a per-sample ScanReport returned to the caller.

Issues are reconciled (not delete-then-inserted): each sample's fresh issue set
is diffed against its stored outstanding issues so first-seen survives across
runs and resolution is detected when a re-evaluated sample stops emitting an
issue. Logs are buffered in memory by a synchronous loguru sink and persisted
in a single bulk insert at run end (single-writer SQLite contract).

Single-writer contract: running two scan_root calls against the same
DB simultaneously is undefined. The CLI takes no advisory lock; the operator
is responsible for serializing scans.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

from loguru import logger
from sqlalchemy import Engine, delete, insert, select
from sqlalchemy.orm import sessionmaker

from catalog import assembler, discovery, orm, persistence, state, thumbnails
from catalog.assembler import FieldConflict, ScanIssue


@dataclass
class ScanReport:
    upserted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    # Sample/acquisition-scope issues emitted this run (across all samples).
    issues: list[ScanIssue] = field(default_factory=list)
    # Run-scope issues not tied to a sample (e.g. unknown MdSimulation subdir).
    run_issues: list[ScanIssue] = field(default_factory=list)
    conflicts: list[FieldConflict] = field(default_factory=list)
    soft_deleted: int = 0
    # populated only on prune_dry_run=True
    would_soft_delete: list[str] | None = None
    # Per-sample membership behind the counts above, persisted to
    # scan_sample_outcomes so the run-detail view can list which samples sit
    # behind each tally.
    upserted_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    # (sample_id, error message) — sample-level failures only.
    failed_samples: list[tuple[str, str]] = field(default_factory=list)
    thumbnails_healed: int = 0
    # Issue-churn / outstanding snapshots for the scan_runs row (set at run end).
    n_new_issues: int = 0
    n_resolved_issues: int = 0
    n_warning_active: int | None = None
    n_error_active: int | None = None


def scan_root(
    engine: Engine,
    root: Path,
    *,
    force: bool = False,
    prune: bool = False,
    prune_dry_run: bool = False,
    prune_safety_floor: float = 0.5,
    child_prune_safety_floor: float = 0.5,
    child_prune_min_count: int = 3,
    on_error: Literal["collect", "raise"] = "collect",
    thumbnail_dir: Path | None = None,
) -> ScanReport:
    """Walk ``root``, assemble + persist each sample, return a ScanReport.

    Mtime gating: a sample is skipped if every parse-target file's mtime is
    unchanged AND the parse-target set is unchanged AND the sample is not
    soft-deleted. ``force=True`` bypasses the gate.

    ``prune=True`` runs ``soft_delete_missing_samples`` after the per-sample
    loop. ``prune_dry_run=True`` reports what would be deleted without writing.
    ``prune_safety_floor`` (0..1.0) caps the fraction of live samples that may
    be deleted in one run; raise PruneSafetyFloorExceeded otherwise.

    ``child_prune_safety_floor``/``child_prune_min_count`` (§08b) are the same
    guard one level down: per sample, per guarded child type (acquisitions,
    md_source, raw/post tomograms, annotations, tilt series), abort that
    sample's upsert with ``ChildPruneSafetyFloorExceeded`` if the fraction
    dropped exceeds the floor and at least the min count existed. Threaded
    through to ``persistence.upsert_sample_record`` via ``_scan_one_sample``.

    ``on_error='collect'`` records sample-level exceptions to ``report.errors``
    and continues. ``'raise'`` propagates the first exception.
    """
    SessionFactory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    report = ScanReport()
    scan_run_id = uuid4().hex

    # ── Log sink (§4.3/§9.11): synchronous, buffers records in memory ────────
    log_buffer: list[dict] = []
    _seq = [0]
    db_level = os.environ.get("SCAN_LOG_DB_LEVEL", "INFO")

    def _sink(message) -> None:
        record = message.record
        _seq[0] += 1
        log_buffer.append(
            {
                "scan_run_id": scan_run_id,
                "seq": _seq[0],
                "ts": record["time"].timestamp(),
                "level": record["level"].name,
                "sample_id": record["extra"].get("sample_id"),
                "message": record["message"],
            }
        )

    sink_id = logger.add(_sink, level=db_level, enqueue=False)

    session = SessionFactory()
    run_now: float | None = None
    try:
        # Open scan_run + catalog_meta in their own transaction so they're
        # visible to subsequent transactions. start_scan returns the run-level
        # `now` we thread through everything (§9.6).
        with session.begin():
            run_now = state.start_scan(session, scan_run_id, root)

        # One SELECT before the loop for soft-deleted ids.
        with session.begin():
            soft_deleted_ids = state.load_soft_deleted_ids(session)

        sample_locs = list(discovery.iter_samples(root))
        total = len(sample_locs)
        logger.info(
            "scanning {} — {} sample(s) discovered (force={}, thumbnails={})",
            root,
            total,
            force,
            "on" if thumbnail_dir is not None else "off",
        )
        run_started = time.perf_counter()

        fs_sample_ids: set[str] = set()
        # §08c: old sample ids named via renamed_from by some sample scanned
        # this run — exempted from soft_delete_missing_samples's deletion
        # event + floor below (populated across the whole loop since that
        # call happens once, after every sample has been scanned).
        sample_renames_exempt: set[str] = set()
        for idx, sample_loc in enumerate(sample_locs, start=1):
            fs_sample_ids.add(sample_loc.sample_id)
            with logger.contextualize(sample_id=sample_loc.sample_id):
                logger.info("[{}/{}] {}", idx, total, sample_loc.sample_id)

                # Per-sample work in its own transaction
                try:
                    old_sample_id = _scan_one_sample(
                        session,
                        sample_loc,
                        force=force,
                        soft_deleted_ids=soft_deleted_ids,
                        scan_run_id=scan_run_id,
                        now=run_now,
                        report=report,
                        thumbnail_dir=thumbnail_dir,
                        child_prune_safety_floor=child_prune_safety_floor,
                        child_prune_min_count=child_prune_min_count,
                    )
                    if old_sample_id is not None:
                        sample_renames_exempt.add(old_sample_id)
                except Exception as e:  # noqa: BLE001
                    # Make sure no partial transaction is left dangling.
                    if session.in_transaction():
                        session.rollback()
                    report.errors.append(f"{sample_loc.sample_id}: {e}")
                    report.failed_samples.append((sample_loc.sample_id, str(e)))
                    if on_error == "raise":
                        raise

        # Run-level issues: subdirs under MdSimulation/ that aren't one of the
        # four dataset-type dirs hold no cataloguable sample and were skipped by
        # discovery; samples outside the recognized top-level arms are never
        # discovered. Surface both so operators see misplaced data.
        run_issues = [
            ScanIssue(
                severity="warning",
                scope="run",
                category="unknown_md_simulation_subdir",
                location=str(subdir),
                file_kind="filesystem",
                file_path=str(subdir),
                message=(
                    f"'{subdir.name}' is not a recognized MdSimulation "
                    "dataset-type directory (expected one of Bulk, "
                    "SingleMolecule, Slab); any samples under "
                    "it were skipped."
                ),
            )
            for subdir in discovery.iter_unknown_md_subdirs(root)
        ]
        run_issues.extend(
            ScanIssue(
                severity="warning",
                scope="run",
                category="sample_outside_arm",
                location=str(sample_dir),
                file_kind="filesystem",
                file_path=str(sample_dir),
                message=(
                    f"sample '{sample_dir.name}' is not under a recognized "
                    "top-level arm (expected Experimental/ or MdSimulation/); "
                    "it was skipped and not catalogued."
                ),
            )
            for sample_dir in discovery.iter_misplaced_samples(root)
        )
        report.run_issues.extend(run_issues)

        # After the loop: optional prune
        if prune or prune_dry_run:
            with session.begin():
                try:
                    persistence.soft_delete_missing_samples(
                        session,
                        fs_sample_ids,
                        run_id=scan_run_id,
                        now=run_now,
                        dry_run=prune_dry_run,
                        safety_floor=prune_safety_floor,
                        report=report,
                        renamed_exempt=frozenset(sample_renames_exempt),
                    )
                except persistence.PruneSafetyFloorExceeded as exc:
                    report.errors.append(
                        f"prune aborted: would soft-delete {len(exc.missing)} "
                        f"samples ({exc.ratio:.1%} > floor "
                        f"{exc.threshold:.1%}); missing={exc.missing}"
                    )
                    raise

        # Run-scope issue reconciliation — ONLY on the completed path (§9.6).
        with session.begin():
            n_new, n_resolved = persistence.reconcile_run_issues(
                session, scan_run_id, run_issues, run_now
            )
            report.n_new_issues += n_new
            report.n_resolved_issues += n_resolved

        # Outstanding-issue snapshot for the scan_runs row.
        with session.begin():
            report.n_warning_active, report.n_error_active = (
                _count_active_issues(session)
            )

        with session.begin():
            state.finish_scan(
                session,
                scan_run_id,
                status="completed",
                report=report,
                now=run_now,
            )
        logger.info(
            "scan complete in {:.1f}s — upserted={}, skipped={}, "
            "healed={}, issues={}, errors={}",
            time.perf_counter() - run_started,
            report.upserted,
            report.skipped,
            report.thumbnails_healed,
            len(report.issues),
            len(report.errors),
        )
    except Exception:
        # Mark the scan failed; let the exception propagate per on_error
        # semantics. Do NOT reconcile run-scope issues (§9.6).
        try:
            if session.in_transaction():
                session.rollback()
            with session.begin():
                state.finish_scan(
                    session,
                    scan_run_id,
                    status="failed",
                    report=report,
                    now=run_now if run_now is not None else time.time(),
                )
        except Exception:
            pass  # don't mask the original
        raise
    finally:
        # Persist the buffered log + run retention, then drop the sink. Done in
        # the finally so a crashed scan still records its partial log.
        logger.remove(sink_id)
        try:
            _persist_logs_and_prune(SessionFactory, log_buffer)
        except Exception as e:  # noqa: BLE001
            # Logging is best-effort; never mask the scan outcome.
            logger.warning("failed to persist scan logs: {}", e)
        session.close()

    return report


def _count_active_issues(session) -> tuple[int, int]:
    """Return (n_warning_active, n_error_active) over outstanding issues."""
    rows = session.execute(
        select(orm.IssueORM.severity).where(orm.IssueORM.resolved_at.is_(None))
    ).scalars().all()
    n_warning = sum(1 for s in rows if s == "warning")
    n_error = sum(1 for s in rows if s == "error")
    return n_warning, n_error


def _persist_logs_and_prune(SessionFactory, log_buffer: list[dict]) -> None:
    """Bulk-insert the buffered log lines, then prune old runs' log lines.

    A fresh short transaction is used for the bulk insert. Retention keeps
    ``scan_log_lines`` only for the most recent ``SCAN_LOG_RETENTION_RUNS``
    runs (default 720); older runs keep their ``scan_runs`` row but lose their
    log lines.
    """
    log_session = SessionFactory()
    try:
        if log_buffer:
            with log_session.begin():
                log_session.execute(
                    insert(orm.ScanLogLineORM), log_buffer
                )

        retention = int(os.environ.get("SCAN_LOG_RETENTION_RUNS", "720"))
        with log_session.begin():
            keep_ids = (
                log_session.execute(
                    select(orm.ScanRunORM.scan_run_id)
                    .order_by(orm.ScanRunORM.started_at.desc())
                    .limit(retention)
                )
                .scalars()
                .all()
            )
            if keep_ids:
                result = log_session.execute(
                    delete(orm.ScanLogLineORM).where(
                        orm.ScanLogLineORM.scan_run_id.notin_(keep_ids)
                    )
                )
                pruned = result.rowcount or 0
                if pruned:
                    logger.info(
                        "pruned {} scan_log_lines beyond the most-recent {} runs",
                        pruned,
                        retention,
                    )
    finally:
        log_session.close()


def _scan_one_sample(
    session,
    sample_loc,
    *,
    force: bool,
    soft_deleted_ids: set[str],
    scan_run_id: str,
    now: float,
    report: ScanReport,
    thumbnail_dir: Path | None,
    child_prune_safety_floor: float = 0.5,
    child_prune_min_count: int = 3,
) -> str | None:
    """Per-sample scan inside its own transaction. Mutates ``report`` in place.

    Returns the old sample id if this sample was persisted as a §08c rename
    target (``record.sample.renamed_from`` was set), else ``None`` — the
    caller accumulates these across the run to exempt them from
    ``soft_delete_missing_samples``'s deletion event + floor (continuity
    stamps for the sample/acquisition levels are handled inline, below, using
    ``upsert_sample_record``'s full rename-info return value).
    """
    parse_targets = discovery.parse_targets_for_sample(sample_loc)

    # Gating check (read state in its own short transaction)
    with session.begin():
        sample_state = state.load_sample_state(session, sample_loc.sample_id)

    is_soft_deleted = sample_loc.sample_id in soft_deleted_ids
    if (
        not force
        and not is_soft_deleted
        and not state.parse_target_set_changed(sample_state, parse_targets)
        and not any(state.is_file_changed(sample_state, p) for p in parse_targets)
    ):
        # Skipped: do NOT reconcile issues (they persist; last_seen unchanged),
        # but DO stamp freshness so the sample records last_scanned_at this run.
        with session.begin():
            # Optional thumbnail heal.
            if thumbnail_dir is not None:
                stored = session.get(orm.SampleORM, sample_loc.sample_id)
                rel = stored.thumbnail_path if stored else None
                if stored is not None and rel and not (thumbnail_dir / rel).is_file():
                    logger.info(
                        "  thumbnail missing on disk — re-generating for {}",
                        sample_loc.sample_id,
                    )
                    thumb_result = thumbnails.generate_thumbnails(
                        sample_loc.sample_id,
                        thumbnails.refs_from_db(session, sample_loc.sample_id),
                        thumbnail_dir,
                        skip_existing=True,
                    )
                    stored.thumbnail_path = thumb_result.representative
                    session.add(stored)
                    report.thumbnails_healed += 1
                    # Record the re-derived provenance for healed acquisitions.
                    for acq_res in thumb_result.per_acq:
                        persistence.upsert_acquisition_scan_status(
                            session,
                            sample_loc.sample_id,
                            acq_res.acquisition_id,
                            now=now,
                            outcome="skipped",
                            run_id=scan_run_id,
                            changed=False,
                            thumbnail_path=acq_res.relpath,
                            thumbnail_source_kind=acq_res.source_kind,
                            thumbnail_source_path=acq_res.source_path,
                            thumbnail_generated_at=(
                                now if acq_res.status == "ok" else None
                            ),
                            thumbnail_status=acq_res.status,
                        )

            persistence.upsert_sample_scan_status(
                session,
                sample_loc.sample_id,
                now=now,
                outcome="skipped",
                run_id=scan_run_id,
                changed=False,
            )
            # Stamp last_scanned_at on each known acquisition (no thumbnail
            # provenance change). Read the acquisitions from the DB.
            for acq in session.execute(
                select(orm.AcquisitionORM.acquisition_id).where(
                    orm.AcquisitionORM.sample_id == sample_loc.sample_id
                )
            ).scalars():
                persistence.upsert_acquisition_scan_status(
                    session,
                    sample_loc.sample_id,
                    acq,
                    now=now,
                    outcome="skipped",
                    run_id=scan_run_id,
                    changed=False,
                )
        logger.debug("  skipped (unchanged): {}", sample_loc.sample_id)
        report.skipped += 1
        report.skipped_ids.append(sample_loc.sample_id)
        return None

    # Assemble + persist in one transaction
    with session.begin():
        result = assembler.assemble_sample(sample_loc)
        report.issues.extend(result.warnings)
        report.conflicts.extend(result.conflicts)

        if result.record is None:
            report.errors.extend(
                f"{sample_loc.sample_id}: {e}" for e in result.errors
            )
            report.failed_samples.append(
                (sample_loc.sample_id, "; ".join(result.errors))
            )
            # Failed sample: reconcile ONLY the assembly_failed error issue(s);
            # do NOT resolve the sample's other outstanding issues.
            failed_issues = [
                i
                for i in result.warnings
                if i.category == "assembly_failed"
            ]
            n_new, n_resolved = persistence.reconcile_sample_issues(
                session,
                scan_run_id,
                sample_loc.sample_id,
                failed_issues,
                now,
                resolve_missing=False,
            )
            report.n_new_issues += n_new
            report.n_resolved_issues += n_resolved
            persistence.upsert_sample_scan_status(
                session,
                sample_loc.sample_id,
                now=now,
                outcome="failed",
                run_id=scan_run_id,
                changed=False,
            )
            return None
        for e in result.errors:
            report.errors.append(f"{sample_loc.sample_id}: {e}")

        disk_size = discovery.dir_size_bytes(sample_loc.path)
        thumb_result: thumbnails.ThumbnailRunResult | None = None
        thumb_rel = None
        if thumbnail_dir is not None:
            n_acqs = len(result.record.acquisitions)
            logger.info(
                "  generating thumbnails for {} acquisition(s)…", n_acqs
            )
            thumb_started = time.perf_counter()
            thumb_result = thumbnails.generate_thumbnails(
                sample_loc.sample_id,
                thumbnails.refs_from_record(result.record),
                thumbnail_dir,
                skip_existing=False,
            )
            thumb_rel = thumb_result.representative
            logger.info(
                "  thumbnails done in {:.1f}s (representative={})",
                time.perf_counter() - thumb_started,
                thumb_rel or "none",
            )
        # §08c: derive rename hints via `persistence.derive_rename_hints` —
        # the same helper `upsert_sample_record` uses internally — rather
        # than reading its return value, so both the acquisition
        # status-continuity snapshot AND issue reconciliation happen BEFORE
        # upsert_sample_record runs. That call's own
        # `_prune_orphan_acquisition_status` step deletes the old
        # (sample_id, acquisition_id) status row *and* its acquisition-scope
        # issues in the same transaction (the old acquisition_id is no longer
        # in keep_acq_pks) — reading/matching against them *after* the call
        # would find them already gone. Sample-level continuity has no such
        # hazard (upsert_sample_record never touches sample_scan_status, and
        # can't delete a *different* sample's issues), but deriving it here
        # too keeps both levels symmetric.
        pre_renamed_sample_id, pre_acq_renames = persistence.derive_rename_hints(
            result.record
        )
        carried_acq_last_changed_by_new_id: dict[str, float] = {}
        for acq_id, old_acq_id in pre_acq_renames.items():
            lookup_sample_id = pre_renamed_sample_id or sample_loc.sample_id
            old_acq_status = session.get(
                orm.AcquisitionScanStatusORM, (lookup_sample_id, old_acq_id)
            )
            if old_acq_status is not None:
                carried_acq_last_changed_by_new_id[acq_id] = (
                    old_acq_status.last_changed_at
                )

        # Reconcile this sample's fresh issue set against its outstanding set
        # — BEFORE upsert_sample_record, for the reason above.
        n_new, n_resolved = persistence.reconcile_sample_issues(
            session,
            scan_run_id,
            sample_loc.sample_id,
            list(result.warnings),
            now,
            renamed_from_sample=pre_renamed_sample_id,
            renamed_acquisitions=pre_acq_renames,
        )
        report.n_new_issues += n_new
        report.n_resolved_issues += n_resolved

        rename_info = persistence.upsert_sample_record(
            session,
            result.record,
            extras=result.extras,
            run_id=scan_run_id,
            now=now,
            disk_size_bytes=disk_size,
            thumbnail_path=thumb_rel,
            child_prune_safety_floor=child_prune_safety_floor,
            child_prune_min_count=child_prune_min_count,
        )
        old_sample_id: str | None = rename_info.sample

        # §08c: carry sample_scan_status.last_changed_at from the old row on
        # a rename, so it doesn't read as freshly changed. `old_sample_id`'s
        # own status row (if any) is untouched by this scan — it belongs to a
        # directory that no longer exists on disk.
        carried_sample_last_changed = None
        if old_sample_id is not None:
            old_sample_status = session.get(
                orm.SampleScanStatusORM, old_sample_id
            )
            if old_sample_status is not None:
                carried_sample_last_changed = old_sample_status.last_changed_at

        # Freshness + thumbnail provenance status (upserted ⇒ changed=True).
        persistence.upsert_sample_scan_status(
            session,
            sample_loc.sample_id,
            now=now,
            outcome="upserted",
            run_id=scan_run_id,
            changed=True,
            carried_last_changed_at=carried_sample_last_changed,
        )
        thumb_by_acq = (
            {r.acquisition_id: r for r in thumb_result.per_acq}
            if thumb_result is not None
            else {}
        )
        for acq_id in result.record.acquisitions:
            acq_res = thumb_by_acq.get(acq_id)
            # §08c: carried_acq_last_changed_by_new_id was snapshotted BEFORE
            # upsert_sample_record ran (see comment above) — reusing it here
            # rather than re-querying (the old row is already gone by now).
            carried_acq_last_changed = carried_acq_last_changed_by_new_id.get(
                acq_id
            )
            persistence.upsert_acquisition_scan_status(
                session,
                sample_loc.sample_id,
                acq_id,
                now=now,
                outcome="upserted",
                run_id=scan_run_id,
                changed=True,
                thumbnail_path=acq_res.relpath if acq_res else None,
                thumbnail_source_kind=acq_res.source_kind if acq_res else None,
                thumbnail_source_path=acq_res.source_path if acq_res else None,
                thumbnail_generated_at=(
                    now if acq_res and acq_res.status == "ok" else None
                ),
                thumbnail_status=acq_res.status if acq_res else None,
                carried_last_changed_at=carried_acq_last_changed,
            )

        # Update mtime state for every parse target.
        for p in parse_targets:
            try:
                mtime = p.stat().st_mtime
            except FileNotFoundError:
                continue  # file disappeared between discovery and stat — skip
            state.record_file_scan(session, p, sample_loc.sample_id, mtime)
        # Prune scan_state rows for files that are no longer parse targets.
        state.prune_missing(
            session, sample_loc.sample_id, kept_paths=set(parse_targets)
        )
        report.upserted += 1
        report.upserted_ids.append(sample_loc.sample_id)
        return old_sample_id


__all__ = ["ScanReport", "scan_root"]
