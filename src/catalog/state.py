"""DB helpers for mtime gating and scan tracking (per §4.5 of the plan).

Pure path → mtime comparison and small SQL upserts; no orchestration logic
lives here. The orchestrator (scanner.py) loads the per-sample state once, then
walks parse targets through ``is_file_changed`` in Python.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from catalog.orm import (
    CatalogMetaORM,
    SampleORM,
    ScanRunORM,
    ScanSampleOutcomeORM,
    ScanStateORM,
)


# Files at or below this size are content-hashed as a fallback to the mtime
# gate; larger files stay mtime-only. Hand-authored metadata (.toml/.mdoc/
# .zattrs) sits far below this; derived binaries (mrc, raw frames) sit far
# above. Those binaries are written once and never get same-mtime edits, so
# hashing them every scan would cost a lot for no benefit.
HASH_MAX_BYTES = 1 << 20  # 1 MiB


def _content_hash(path: Path) -> str | None:
    """SHA-256 hex digest of ``path``'s bytes, or None if too large to hash.

    This backstops the mtime gate: a rewrite that preserves mtime (an
    mtime-preserving sync/restore like ``rsync -t``/``cp -p``, or an editor
    that resets the timestamp) is invisible to mtime comparison. Returns None
    for oversized/unreadable files so those fall back to mtime-only gating.
    """
    try:
        if path.stat().st_size > HASH_MAX_BYTES:
            return None
        with path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    except OSError:
        return None


def load_sample_state(
    session: Session, sample_id: str
) -> dict[Path, tuple[float, str | None]]:
    """Return ``{Path: (mtime, content_hash)}`` for this sample's scan_state.

    Implemented as one indexed SELECT (sample_id is indexed in the ORM).
    ``content_hash`` is None for files too large to hash (see ``_content_hash``)
    or rows written before content hashing was populated.
    """
    rows = session.execute(
        select(
            ScanStateORM.path, ScanStateORM.mtime, ScanStateORM.content_hash
        ).where(ScanStateORM.sample_id == sample_id)
    ).all()
    return {Path(p): (m, h) for p, m, h in rows}


def is_file_changed(
    state: dict[Path, tuple[float, str | None]], path: Path
) -> bool:
    """Decide whether ``path`` changed since its recorded scan_state.

    Returns True if the path is missing from state (first-seen), missing on
    disk (orchestrator will re-assemble; pruning drops the stale row), or its
    mtime differs. When mtime matches but a content hash was recorded, the
    file is re-hashed and compared — so a same-mtime rewrite is still caught.
    """
    try:
        current = path.stat().st_mtime
    except FileNotFoundError:
        return True
    prev = state.get(path)
    if prev is None:
        return True
    prev_mtime, prev_hash = prev
    if prev_mtime != current:
        return True
    # mtime unchanged: verify content for files we recorded a hash for.
    if prev_hash is not None:
        return _content_hash(path) != prev_hash
    return False


def record_file_scan(
    session: Session, path: Path, sample_id: str, mtime: float
) -> None:
    """Upsert ``scan_state(path, sample_id, mtime, content_hash, last_scanned)``."""
    now = time.time()
    content_hash = _content_hash(path)
    existing = session.get(ScanStateORM, str(path))
    if existing is None:
        session.add(
            ScanStateORM(
                path=str(path),
                sample_id=sample_id,
                mtime=mtime,
                last_scanned=now,
                content_hash=content_hash,
            )
        )
    else:
        existing.mtime = mtime
        existing.last_scanned = now
        existing.sample_id = sample_id  # in case of moves
        existing.content_hash = content_hash


def parse_target_set_changed(
    state: dict[Path, tuple[float, str | None]], parse_targets: list[Path]
) -> bool:
    """True iff ``set(parse_targets) != set(state.keys())``.

    Detects files added or removed since the last scan; mtime drift on
    individual files is handled by ``is_file_changed``.
    """
    return set(parse_targets) != set(state.keys())


def prune_missing(
    session: Session, sample_id: str, kept_paths: set[Path]
) -> int:
    """Delete every ``scan_state`` row for this sample whose path is not in
    ``kept_paths``. Returns the count of rows deleted.
    """
    kept_str = {str(p) for p in kept_paths}
    rows = (
        session.execute(
            select(ScanStateORM.path).where(ScanStateORM.sample_id == sample_id)
        )
        .scalars()
        .all()
    )
    to_delete = [p for p in rows if p not in kept_str]
    if not to_delete:
        return 0
    result = session.execute(
        delete(ScanStateORM)
        .where(ScanStateORM.sample_id == sample_id)
        .where(ScanStateORM.path.in_(to_delete))
    )
    return result.rowcount or 0


def load_soft_deleted_ids(session: Session) -> set[str]:
    """Return the set of sample_ids currently soft-deleted.

    Called once at the top of ``scan_root`` so the per-sample gating loop can
    force re-assembly for any soft-deleted sample whose dir has reappeared on
    disk — without this, mtime-unchanged files would skip gating and leave
    ``deleted_at`` set forever.
    """
    rows = (
        session.execute(
            select(SampleORM.sample_id).where(SampleORM.deleted_at.is_not(None))
        )
        .scalars()
        .all()
    )
    return set(rows)


def start_scan(
    session: Session,
    scan_run_id: str,
    root: Path,
) -> float:
    """Insert a ``scan_runs`` row (status running) and upsert ``catalog_meta``.

    Returns the run-level ``started_at`` so the orchestrator can thread a single
    ``now`` value through reconciliation, the per-sample upsert, the status
    upserts, and ``finish_scan`` (decision §9.6 — one timestamp per run).

    The ``catalog_meta`` upsert lives here (rather than in ``finish_scan``)
    so the table reflects what root *was being scanned* even if the scan
    crashes before completing.
    """
    now = time.time()
    session.add(
        ScanRunORM(
            scan_run_id=scan_run_id,
            started_at=now,
            ended_at=None,
            root=str(root),
            status="running",
        )
    )
    existing = session.get(CatalogMetaORM, 1)
    if existing is None:
        session.add(
            CatalogMetaORM(id=1, data_root=str(root), updated_at=now)
        )
    else:
        existing.data_root = str(root)
        existing.updated_at = now
    return now


def finish_scan(
    session: Session,
    scan_run_id: str,
    *,
    status: str,
    report: Any,
    now: float,
) -> None:
    """Mark a scan run as finished and record the per-sample outcomes.

    Updates the ``scan_runs`` row with ``ended_at=now``, ``status``, the
    upserted/skipped/failed tallies, and (best-effort, when the report carries
    them) the issue-churn + outstanding-issue snapshot counts. Then writes the
    per-sample outcome rows.

    ``report`` is duck-typed: any object with ``upserted``, ``skipped``, and
    ``errors`` attributes works. ``getattr`` with safe defaults lets an
    early-failure caller call this with a stub.
    """
    upserted = getattr(report, "upserted", 0) or 0
    skipped = getattr(report, "skipped", 0) or 0
    failed = len(getattr(report, "failed_samples", []) or [])
    values: dict[str, Any] = {
        "ended_at": now,
        "status": status,
        "n_upserted": upserted,
        "n_skipped": skipped,
        "n_failed": failed,
    }
    # Best-effort issue-churn / outstanding snapshots (left null if absent).
    for attr in (
        "n_new_issues",
        "n_resolved_issues",
        "n_warning_active",
        "n_error_active",
        "n_info_active",
    ):
        v = getattr(report, attr, None)
        if v is not None:
            values[attr] = v
    session.execute(
        update(ScanRunORM)
        .where(ScanRunORM.scan_run_id == scan_run_id)
        .values(**values)
    )
    _record_scan_membership(session, scan_run_id, report)


def _record_scan_membership(
    session: Session, scan_run_id: str, report: Any
) -> None:
    """Persist which samples were upserted/skipped/failed for this run.

    Idempotent: clears any prior rows for ``scan_run_id`` first, so the
    failure path (``finish_scan`` called twice) doesn't double-insert.
    A sample appears at most once (the Unique(scan_run_id, sample_id)
    constraint): failed wins over skipped wins over upserted, and failed
    samples are deduplicated by ``sample_id``.
    """
    session.execute(
        delete(ScanSampleOutcomeORM).where(
            ScanSampleOutcomeORM.scan_run_id == scan_run_id
        )
    )

    seen: set[str] = set()

    # Failed first so it wins the unique (scan_run_id, sample_id) slot.
    for sample_id, detail in getattr(report, "failed_samples", []) or []:
        if sample_id in seen:
            continue
        seen.add(sample_id)
        session.add(
            ScanSampleOutcomeORM(
                scan_run_id=scan_run_id,
                sample_id=sample_id,
                outcome="failed",
                detail=detail or None,
            )
        )
    for sample_id in getattr(report, "upserted_ids", []) or []:
        if sample_id in seen:
            continue
        seen.add(sample_id)
        session.add(
            ScanSampleOutcomeORM(
                scan_run_id=scan_run_id, sample_id=sample_id, outcome="upserted"
            )
        )
    for sample_id in getattr(report, "skipped_ids", []) or []:
        if sample_id in seen:
            continue
        seen.add(sample_id)
        session.add(
            ScanSampleOutcomeORM(
                scan_run_id=scan_run_id, sample_id=sample_id, outcome="skipped"
            )
        )
