"""Manage-page endpoints — scan run history + outstanding/resolved issues.

Replaces the old per-scan-run ``/scans`` router. The model splits run history
(``scan_runs``, ``scan_log_lines``, ``scan_sample_outcomes``) from current state
(``issues``); these endpoints serve the redesigned Manage page (plan §4.6):

  GET /manage/summary                       -> ManageSummary
  GET /manage/issues                        -> list[IssueGroup]   (outstanding)
  GET /manage/issues/resolved               -> list[IssueGroup]   (recently resolved)
  GET /manage/deletions                     -> list[DeletionEvent] (append-only feed, §08a)
  GET /manage/scans                         -> list[ScanRun]
  GET /manage/scans/{id}                    -> ScanRun
  GET /manage/scans/{id}/logs               -> list[ScanLogLine]
  GET /manage/scans/{id}/samples            -> list[ScanSampleOutcomeOut]
"""
from __future__ import annotations

import os
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.schemas import (
    DeletionEvent,
    IssueGroup,
    IssueItem,
    LatestScanInfo,
    ManageSummary,
    OutstandingCounts,
    ScanLogLine,
    ScanRun,
    ScanSampleOutcomeOut,
)

router = APIRouter()

Outcome = Literal["upserted", "skipped", "failed"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
Severity = Literal["error", "warning", "info"]
# Priority order for a group's rollup severity (max-wins) and default sort.
_SEVERITY_ORDER = ("error", "warning", "info")


def _enum_val(v):
    """Coerce a possibly-enum value to its string value."""
    return v.value if hasattr(v, "value") else v


def _latest_completed_run(session: Session) -> orm.ScanRunORM | None:
    """The most recent completed scan run (by ended_at), or None."""
    return session.execute(
        select(orm.ScanRunORM)
        .where(orm.ScanRunORM.status == "completed")
        .order_by(orm.ScanRunORM.ended_at.desc())
        .limit(1)
    ).scalars().first()


def _scan_run_to_out(row: orm.ScanRunORM) -> ScanRun:
    return ScanRun(
        scan_run_id=row.scan_run_id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        status=_enum_val(row.status),
        root=row.root,
        n_upserted=row.n_upserted,
        n_skipped=row.n_skipped,
        n_failed=row.n_failed,
        n_new_issues=row.n_new_issues,
        n_resolved_issues=row.n_resolved_issues,
        n_warning_active=row.n_warning_active,
        n_error_active=row.n_error_active,
        n_info_active=row.n_info_active,
    )


def _path_lookups(
    session: Session, rows: list[orm.IssueORM]
) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Batch-fetch on-disk directory paths for the samples/acquisitions named
    in ``rows``, so the warnings page gets them in one response instead of a
    per-sample follow-up fetch. Acquisition ids aren't unique across samples,
    so acquisitions are looked up by (sample_id, acquisition_id).
    """
    sample_ids = {r.sample_id for r in rows if r.sample_id}
    if not sample_ids:
        return {}, {}
    sample_paths = {
        s: p
        for s, p in session.execute(
            select(orm.SampleORM.sample_id, orm.SampleORM.path).where(
                orm.SampleORM.sample_id.in_(sample_ids)
            )
        ).all()
        if p is not None
    }
    acquisition_paths = {
        (s, a): p
        for s, a, p in session.execute(
            select(
                orm.AcquisitionORM.sample_id,
                orm.AcquisitionORM.acquisition_id,
                orm.AcquisitionORM.path,
            ).where(orm.AcquisitionORM.sample_id.in_(sample_ids))
        ).all()
        if p is not None
    }
    return sample_paths, acquisition_paths


def _group_issues(
    rows: list[orm.IssueORM],
    *,
    latest_run_id: str | None,
    latest_scan_at: float | None,
    resolved: bool,
    sample_paths: dict[str, str] = {},
    acquisition_paths: dict[tuple[str, str], str] = {},
) -> list[IssueGroup]:
    """Group issue rows by (scope, sample_id, acquisition_id, md_run_id, file_kind).

    Mirrors the old ``scans._scan_warnings`` Python-grouping style. ``severity``
    is the max within the group (error wins over warning wins over info). When
    ``resolved`` is True, the group also carries ``resolved_at`` (max) + its
    ``resolved_run_id``.
    """
    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (
            _enum_val(r.scope),
            r.sample_id,
            r.acquisition_id,
            r.md_run_id,
            _enum_val(r.file_kind),
        )
        g = groups.get(key)
        if g is None:
            g = {
                "scope": _enum_val(r.scope),
                "sample_id": r.sample_id,
                "acquisition_id": r.acquisition_id,
                "md_run_id": r.md_run_id,
                "file_kind": _enum_val(r.file_kind),
                "file_path": r.file_path,
                "severity_rank": len(_SEVERITY_ORDER) - 1,
                "issues": [],
                "first_seen_at": r.first_seen_at,
                "last_seen_at": r.last_seen_at,
                "last_seen_run_id": r.last_seen_run_id,
                "resolved_at": r.resolved_at,
                "resolved_run_id": r.resolved_run_id,
            }
            groups[key] = g

        rank = _SEVERITY_ORDER.index(_enum_val(r.severity))
        if rank < g["severity_rank"]:
            g["severity_rank"] = rank
        g["issues"].append(IssueItem(category=r.category, message=r.message))

        if r.first_seen_at < g["first_seen_at"]:
            g["first_seen_at"] = r.first_seen_at
        if r.last_seen_at > g["last_seen_at"]:
            g["last_seen_at"] = r.last_seen_at
            g["last_seen_run_id"] = r.last_seen_run_id
        if resolved and r.resolved_at is not None and (
            g["resolved_at"] is None or r.resolved_at > g["resolved_at"]
        ):
            g["resolved_at"] = r.resolved_at
            g["resolved_run_id"] = r.resolved_run_id
        # ``file_path`` is take-first-non-null within the group.
        if g["file_path"] is None and r.file_path is not None:
            g["file_path"] = r.file_path

    out = [
        IssueGroup(
            scope=g["scope"],
            sample_id=g["sample_id"],
            acquisition_id=g["acquisition_id"],
            md_run_id=g["md_run_id"],
            file_kind=g["file_kind"],
            file_path=g["file_path"],
            sample_path=sample_paths.get(g["sample_id"]) if g["sample_id"] else None,
            acquisition_path=(
                acquisition_paths.get((g["sample_id"], g["acquisition_id"]))
                if g["sample_id"] and g["acquisition_id"]
                else None
            ),
            severity=_SEVERITY_ORDER[g["severity_rank"]],
            issues=g["issues"],
            first_seen_at=g["first_seen_at"],
            last_seen_at=g["last_seen_at"],
            last_seen_run_id=g["last_seen_run_id"],
            latest_run_id=latest_run_id,
            latest_scan_at=latest_scan_at,
            resolved_at=g["resolved_at"] if resolved else None,
            resolved_run_id=g["resolved_run_id"] if resolved else None,
        )
        for g in groups.values()
    ]
    # Sort by severity (errors first, then warnings, then info) then sample_id.
    out.sort(key=lambda gr: (_SEVERITY_ORDER.index(gr.severity), gr.sample_id or ""))
    return out


# ── Summary ──────────────────────────────────────────────────────────────


@router.get("/summary", response_model=ManageSummary)
def get_summary(session: Session = Depends(get_session)):
    """Status/cadence card: latest scan, configured cadence, outstanding counts."""
    # Latest scan = latest completed run; fall back to latest run of any status.
    completed_run = _latest_completed_run(session)
    run = completed_run
    if run is None:
        run = session.execute(
            select(orm.ScanRunORM)
            .order_by(orm.ScanRunORM.started_at.desc())
            .limit(1)
        ).scalars().first()

    latest_scan: LatestScanInfo | None = None
    if run is not None:
        duration = (
            run.ended_at - run.started_at
            if run.ended_at is not None
            else None
        )
        latest_scan = LatestScanInfo(
            started_at=run.started_at,
            ended_at=run.ended_at,
            status=_enum_val(run.status),
            duration=duration,
        )

    # Outstanding live counts by severity.
    counts = dict(
        session.execute(
            select(orm.IssueORM.severity, func.count())
            .where(orm.IssueORM.resolved_at.is_(None))
            .group_by(orm.IssueORM.severity)
        ).all()
    )
    outstanding = OutstandingCounts(
        errors=counts.get("error", 0),
        warnings=counts.get("warning", 0),
        infos=counts.get("info", 0),
    )

    # Deletion events from the latest completed run (badge count, §08a).
    deletions_latest_run = 0
    if completed_run is not None:
        deletions_latest_run = session.execute(
            select(func.count())
            .select_from(orm.DeletionEventORM)
            .where(orm.DeletionEventORM.scan_run_id == completed_run.scan_run_id)
        ).scalar_one()

    return ManageSummary(
        latest_scan=latest_scan,
        cadence_cron=os.environ.get("SCAN_CADENCE_CRON", "0 * * * *"),
        cadence_tz=os.environ.get("SCAN_CADENCE_TZ", "UTC"),
        outstanding=outstanding,
        deletions_latest_run=deletions_latest_run,
    )


# ── Issues ───────────────────────────────────────────────────────────────


@router.get("/issues", response_model=list[IssueGroup])
def get_outstanding_issues(
    severity: Severity | None = Query(None),
    file_kind: str | None = Query(None),
    q: str | None = Query(None),
    session: Session = Depends(get_session),
):
    """Outstanding issues (resolved_at IS NULL), grouped by entity + file_kind."""
    stmt = select(orm.IssueORM).where(orm.IssueORM.resolved_at.is_(None))
    if severity is not None:
        stmt = stmt.where(orm.IssueORM.severity == severity)
    if file_kind is not None:
        stmt = stmt.where(orm.IssueORM.file_kind == file_kind)
    if q:
        # Each whitespace-separated term must match some field (AND across
        # terms, OR across fields) so "sample-1 acq1" narrows to that
        # acquisition — acquisition ids aren't unique across samples.
        for term in q.lower().split():
            like = f"%{term}%"
            stmt = stmt.where(
                func.lower(orm.IssueORM.message).like(like)
                | func.lower(orm.IssueORM.location).like(like)
                | func.lower(func.coalesce(orm.IssueORM.file_path, "")).like(like)
                | func.lower(func.coalesce(orm.IssueORM.sample_id, "")).like(like)
                | func.lower(
                    func.coalesce(orm.IssueORM.acquisition_id, "")
                ).like(like)
            )
    rows = session.execute(stmt).scalars().all()

    run = _latest_completed_run(session)
    latest_run_id = run.scan_run_id if run else None
    latest_scan_at = (run.ended_at or run.started_at) if run else None
    sample_paths, acquisition_paths = _path_lookups(session, rows)

    return _group_issues(
        rows,
        latest_run_id=latest_run_id,
        latest_scan_at=latest_scan_at,
        resolved=False,
        sample_paths=sample_paths,
        acquisition_paths=acquisition_paths,
    )


@router.get("/issues/resolved", response_model=list[IssueGroup])
def get_resolved_issues(
    within_hours: float = Query(24.0, gt=0),
    session: Session = Depends(get_session),
):
    """Issues resolved within the last ``within_hours`` hours, same grouping."""
    cutoff = time.time() - within_hours * 3600.0
    rows = session.execute(
        select(orm.IssueORM)
        .where(orm.IssueORM.resolved_at.is_not(None))
        .where(orm.IssueORM.resolved_at >= cutoff)
    ).scalars().all()

    run = _latest_completed_run(session)
    latest_run_id = run.scan_run_id if run else None
    latest_scan_at = (run.ended_at or run.started_at) if run else None
    sample_paths, acquisition_paths = _path_lookups(session, rows)

    return _group_issues(
        rows,
        latest_run_id=latest_run_id,
        latest_scan_at=latest_scan_at,
        resolved=True,
        sample_paths=sample_paths,
        acquisition_paths=acquisition_paths,
    )


# ── Deletion audit feed (§08a) ──────────────────────────────────────────────


@router.get("/deletions", response_model=list[DeletionEvent])
def get_deletions(
    entity_type: str | None = Query(None),
    sample_id: str | None = Query(None),
    within_hours: float | None = Query(None, gt=0),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """Append-only deletion feed, newest-first. No resolve/dismiss — every
    scan-detected disappearance stays in the feed (§08a)."""
    stmt = select(orm.DeletionEventORM)
    if entity_type is not None:
        stmt = stmt.where(orm.DeletionEventORM.entity_type == entity_type)
    if sample_id is not None:
        stmt = stmt.where(orm.DeletionEventORM.sample_id == sample_id)
    if within_hours is not None:
        cutoff = time.time() - within_hours * 3600.0
        stmt = stmt.where(orm.DeletionEventORM.detected_at >= cutoff)
    stmt = (
        stmt.order_by(orm.DeletionEventORM.detected_at.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = session.execute(stmt).scalars().all()
    return [
        DeletionEvent(
            id=r.id,
            scan_run_id=r.scan_run_id,
            detected_at=r.detected_at,
            entity_type=_enum_val(r.entity_type),
            kind=_enum_val(r.kind),
            sample_id=r.sample_id,
            acquisition_id=r.acquisition_id,
            entity_id=r.entity_id,
            last_known_path=r.last_known_path,
            last_known_json=r.last_known_json,
        )
        for r in rows
    ]


# ── Scan runs ──────────────────────────────────────────────────────────────


@router.get("/scans", response_model=list[ScanRun])
def list_scans(session: Session = Depends(get_session)):
    rows = session.execute(
        select(orm.ScanRunORM).order_by(orm.ScanRunORM.started_at.desc())
    ).scalars().all()
    return [_scan_run_to_out(r) for r in rows]


# NOTE: the ``/scans/{id}`` routes must be declared after every literal
# ``/scans`` path — FastAPI matches in registration order, and a bare
# path-param route would otherwise swallow a literal segment. (No literal
# child paths exist today, but keep the discipline mirroring the old scans.py.)
@router.get("/scans/{scan_run_id}", response_model=ScanRun)
def get_scan(scan_run_id: str, session: Session = Depends(get_session)):
    row = session.get(orm.ScanRunORM, scan_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return _scan_run_to_out(row)


@router.get("/scans/{scan_run_id}/logs", response_model=list[ScanLogLine])
def get_scan_logs(
    scan_run_id: str,
    level: LogLevel | None = Query(None),
    q: str | None = Query(None),
    session: Session = Depends(get_session),
):
    """Log lines for one run, ordered by seq. 404 if the run is unknown."""
    if session.get(orm.ScanRunORM, scan_run_id) is None:
        raise HTTPException(status_code=404, detail="scan not found")

    stmt = (
        select(orm.ScanLogLineORM)
        .where(orm.ScanLogLineORM.scan_run_id == scan_run_id)
    )
    if level is not None:
        stmt = stmt.where(orm.ScanLogLineORM.level == level)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(orm.ScanLogLineORM.message).like(like))
    stmt = stmt.order_by(orm.ScanLogLineORM.seq)

    rows = session.execute(stmt).scalars().all()
    return [
        ScanLogLine(
            id=r.id,
            seq=r.seq,
            ts=r.ts,
            level=_enum_val(r.level),
            sample_id=r.sample_id,
            message=r.message,
        )
        for r in rows
    ]


@router.get("/scans/{scan_run_id}/samples", response_model=list[ScanSampleOutcomeOut])
def get_scan_samples(
    scan_run_id: str,
    outcome: Outcome | None = Query(None),
    session: Session = Depends(get_session),
):
    """Per-sample outcomes for one run (optional outcome filter). 404 if unknown."""
    if session.get(orm.ScanRunORM, scan_run_id) is None:
        raise HTTPException(status_code=404, detail="scan not found")

    stmt = (
        select(orm.ScanSampleOutcomeORM)
        .where(orm.ScanSampleOutcomeORM.scan_run_id == scan_run_id)
    )
    if outcome is not None:
        stmt = stmt.where(orm.ScanSampleOutcomeORM.outcome == outcome)
    stmt = stmt.order_by(orm.ScanSampleOutcomeORM.sample_id)

    rows = session.execute(stmt).scalars().all()
    return [
        ScanSampleOutcomeOut(
            sample_id=r.sample_id,
            outcome=_enum_val(r.outcome),
            detail=r.detail,
        )
        for r in rows
    ]
