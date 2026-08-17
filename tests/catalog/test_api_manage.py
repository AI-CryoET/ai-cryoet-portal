"""Tests for the ``/manage/*`` router (plan §4.6).

Covers the summary card, outstanding + recently-resolved issue grouping (incl.
the §9.7 latest_run_id / last_seen behaviour and the resolved-window), the
scan-run history list/detail (404s), per-run logs, and per-run sample outcomes.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from catalog import db, orm
from catalog.api.deps import get_session
from catalog.api.main import create_app
from catalog.api.routes.manage import _group_issues

# Fixed reference clock so window assertions are deterministic.
_NOW = time.time()


_fp_counter = [0]


def _issue(session, **kw):
    _fp_counter[0] += 1
    defaults = dict(
        fingerprint=f"fp-{_fp_counter[0]}",
        severity="warning",
        scope="sample",
        sample_id="sample-1",
        acquisition_id=None,
        file_kind="sample_toml",
        file_path=None,
        location="loc",
        category="cat",
        message="m",
        first_seen_at=_NOW - 1000,
        first_seen_run_id="run-completed",
        last_seen_at=_NOW - 500,
        last_seen_run_id="run-completed",
        resolved_at=None,
        resolved_run_id=None,
    )
    defaults.update(kw)
    session.add(orm.IssueORM(**defaults))


@pytest.fixture
def client(tmp_path):
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

    s = Session()
    try:
        # Three scan runs covering the status matrix.
        s.add(orm.ScanRunORM(
            scan_run_id="run-completed", started_at=_NOW - 300,
            ended_at=_NOW - 250, root="/data", status="completed",
            n_upserted=5, n_skipped=1, n_failed=0,
            n_new_issues=2, n_resolved_issues=1, n_warning_active=3,
            n_error_active=1,
        ))
        s.add(orm.ScanRunORM(
            scan_run_id="run-failed", started_at=_NOW - 200,
            ended_at=_NOW - 180, root="/data", status="failed",
            n_upserted=2, n_skipped=0, n_failed=3,
        ))
        s.add(orm.ScanRunORM(
            scan_run_id="run-running", started_at=_NOW - 10,
            ended_at=None, root="/data", status="running",
        ))

        # sample-1 + its acq1 acquisition have on-disk paths recorded; sample-2
        # has no SampleORM row at all (path lookup must tolerate that).
        s.add(orm.SampleORM(
            sample_id="sample-1", data_source="experimental", project="chromatin",
            path="/data/scratch/sample-1",
        ))
        s.add(orm.AcquisitionORM(
            sample_id="sample-1", acquisition_id="acq1",
            path="/data/scratch/sample-1/acq1",
        ))

        # Outstanding issues:
        #  - sample-1: a warning + an error at the SAME (scope,file_kind) group
        #    so severity=max(error) and 2 issue items appear.
        _issue(s, severity="warning", category="extra_field",
               message="extra field", first_seen_at=_NOW - 1000)
        _issue(s, severity="error", category="assembly_failed",
               message="boom", first_seen_at=_NOW - 2000,
               last_seen_at=_NOW - 300, last_seen_run_id="run-completed")
        #  - sample-2: a warning whose owner was skipped (last_seen on an OLD
        #    run, not the latest completed run) — §9.7.
        _issue(s, sample_id="sample-2", severity="warning",
               category="possible_typo", message="typo",
               file_path="/data/scratch/sample-2/sample.toml",
               last_seen_at=_NOW - 9000, last_seen_run_id="run-ancient")
        #  - acquisition-scope issue for filtering by file_kind.
        _issue(s, sample_id="sample-1", scope="acquisition",
               acquisition_id="acq1", file_kind="acquisition_toml",
               location="acquisitions.acq1", category="undeclared_tomogram_folder",
               message="stray tomo")
        #  - two md_run-scoped issues on the same sample, different runs: must
        #    group separately (md_run_id is part of the group key) so a
        #    manage-page link can target the right run's authoring form.
        _issue(s, sample_id="sample-1", file_kind="md_run_toml",
               md_run_id="run_a", location="md_run[run_a].seed",
               category="unfilled_placeholder", message="run_a placeholder")
        _issue(s, sample_id="sample-1", file_kind="md_run_toml",
               md_run_id="run_b", location="md_run[run_b].seed",
               category="unfilled_placeholder", message="run_b placeholder")

        # Resolved issues: one within 24h (appears), one older (hidden).
        _issue(s, sample_id="sample-3", severity="warning",
               category="resolved_recent", message="fixed recently",
               resolved_at=_NOW - 3600, resolved_run_id="run-completed")
        _issue(s, sample_id="sample-4", severity="warning",
               category="resolved_old", message="fixed long ago",
               resolved_at=_NOW - 3 * 24 * 3600,
               resolved_run_id="run-completed")

        # Log lines for run-completed.
        for seq, (level, sid, msg) in enumerate(
            [
                ("INFO", None, "scanning /data"),
                ("INFO", "sample-1", "[1/2] sample-1"),
                ("WARNING", "sample-1", "missing acquisition.toml"),
                ("INFO", "sample-2", "[2/2] sample-2"),
            ],
            start=1,
        ):
            s.add(orm.ScanLogLineORM(
                scan_run_id="run-completed", seq=seq, ts=_NOW - 260 + seq,
                level=level, sample_id=sid, message=msg,
            ))

        # Per-sample outcomes for run-completed.
        s.add(orm.ScanSampleOutcomeORM(
            scan_run_id="run-completed", sample_id="sample-1", outcome="upserted",
        ))
        s.add(orm.ScanSampleOutcomeORM(
            scan_run_id="run-completed", sample_id="sample-2", outcome="skipped",
        ))
        s.add(orm.ScanSampleOutcomeORM(
            scan_run_id="run-completed", sample_id="ghost", outcome="failed",
            detail="assemble failed",
        ))

        # Deletion events (§08a): two on the latest completed run, one on an
        # older/failed run, and one far outside any within_hours window.
        s.add(orm.DeletionEventORM(
            scan_run_id="run-completed", detected_at=_NOW - 260,
            entity_type="acquisition", sample_id="sample-1",
            acquisition_id="acq1", entity_id=None,
            last_known_path="/data/sample-1/acq1",
            last_known_json='{"acquisition_id": "acq1"}',
        ))
        s.add(orm.DeletionEventORM(
            scan_run_id="run-completed", detected_at=_NOW - 255,
            entity_type="raw_tomogram", sample_id="sample-1",
            acquisition_id="acq1", entity_id="t1",
            last_known_path="/data/sample-1/acq1/raw/t1.mrc",
            last_known_json='{"tomogram_id": "t1"}',
        ))
        s.add(orm.DeletionEventORM(
            scan_run_id="run-failed", detected_at=_NOW - 190,
            entity_type="sample", sample_id="sample-9",
            acquisition_id=None, entity_id=None,
            last_known_path="/data/sample-9",
            last_known_json='{"sample_id": "sample-9"}',
        ))
        s.add(orm.DeletionEventORM(
            scan_run_id="run-completed", detected_at=_NOW - 100_000,
            entity_type="sample", sample_id="sample-old",
            acquisition_id=None, entity_id=None,
            last_known_path=None,
            last_known_json='{"sample_id": "sample-old"}',
        ))

        s.commit()
    finally:
        s.close()

    return TestClient(app)


# ── GET /manage/summary ────────────────────────────────────────────────────


def test_summary_latest_scan_and_counts(client):
    body = client.get("/manage/summary").json()
    ls = body["latest_scan"]
    # Latest = latest completed run.
    assert ls["status"] == "completed"
    assert ls["started_at"] == pytest.approx(_NOW - 300)
    assert ls["ended_at"] == pytest.approx(_NOW - 250)
    assert ls["duration"] == pytest.approx(50.0)
    assert body["cadence_cron"]
    assert body["cadence_tz"]
    # Outstanding counts by severity (resolved excluded).
    assert body["outstanding"]["errors"] == 1
    assert body["outstanding"]["warnings"] == 5
    # Deletion count scoped to the latest *completed* run (3 events logged
    # against run-completed; the run-failed event is excluded).
    assert body["deletions_latest_run"] == 3


# ── GET /manage/issues (outstanding) ───────────────────────────────────────


def test_outstanding_issues_grouping_and_severity_max(client):
    body = client.get("/manage/issues").json()
    # sample-1 sample_toml group merges the warning + error → severity error,
    # 2 issue items.
    g = next(
        x for x in body
        if x["sample_id"] == "sample-1" and x["file_kind"] == "sample_toml"
    )
    assert g["severity"] == "error"
    assert {i["category"] for i in g["issues"]} == {
        "extra_field", "assembly_failed"
    }
    # first_seen_at is the min within the group.
    assert g["first_seen_at"] == pytest.approx(_NOW - 2000)
    # Errors sort first.
    assert body[0]["severity"] == "error"


def test_outstanding_issues_carry_sample_and_acquisition_path(client):
    """Path fields come from a batch join, not the issue row itself — sample-1
    (SampleORM row exists) and its acq1 acquisition both resolve; sample-2
    (no SampleORM row) resolves to null rather than erroring."""
    body = client.get("/manage/issues").json()
    sample_group = next(
        x for x in body
        if x["sample_id"] == "sample-1" and x["file_kind"] == "sample_toml"
    )
    assert sample_group["sample_path"] == "/data/scratch/sample-1"
    assert sample_group["acquisition_path"] is None
    acq_group = next(x for x in body if x["acquisition_id"] == "acq1")
    assert acq_group["sample_path"] == "/data/scratch/sample-1"
    assert acq_group["acquisition_path"] == "/data/scratch/sample-1/acq1"
    no_row = next(x for x in body if x["sample_id"] == "sample-2")
    assert no_row["sample_path"] is None


def test_outstanding_issues_excludes_resolved(client):
    body = client.get("/manage/issues").json()
    cats = {i["category"] for g in body for i in g["issues"]}
    assert "resolved_recent" not in cats
    assert "resolved_old" not in cats


def test_outstanding_latest_run_and_skipped_owner(client):
    """§9.7: each group carries the global latest_run_id + its own last_seen.
    A skipped owner's group has last_seen_run_id != latest_run_id."""
    body = client.get("/manage/issues").json()
    for g in body:
        assert g["latest_run_id"] == "run-completed"
        assert g["latest_scan_at"] == pytest.approx(_NOW - 250)
    skipped = next(x for x in body if x["sample_id"] == "sample-2")
    assert skipped["last_seen_run_id"] == "run-ancient"
    assert skipped["last_seen_run_id"] != skipped["latest_run_id"]


def test_outstanding_filter_by_severity(client):
    body = client.get("/manage/issues", params={"severity": "error"}).json()
    # Only groups containing an error remain; here just sample-1 sample_toml.
    assert all(g["severity"] == "error" for g in body)
    assert len(body) == 1


def _bare_issue(**kw):
    """A standalone (unsaved) IssueORM row for exercising ``_group_issues``
    directly — its severity-rollup logic doesn't touch the DB."""
    defaults = dict(
        scope="sample",
        sample_id="s",
        acquisition_id=None,
        md_run_id=None,
        file_kind="sample_toml",
        file_path=None,
        category="cat",
        message="m",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        last_seen_run_id="run-completed",
        resolved_at=None,
        resolved_run_id=None,
    )
    defaults.update(kw)
    return orm.IssueORM(**defaults)


def test_group_severity_rollup_is_error_over_warning_over_info():
    """A group's severity is the max across its rows, ranked
    error > warning > info — not just an error/warning binary."""
    warning_and_info = _group_issues(
        [_bare_issue(severity="warning"), _bare_issue(severity="info")],
        latest_run_id=None, latest_scan_at=None, resolved=False,
    )
    assert warning_and_info[0].severity == "warning"

    info_only = _group_issues(
        [_bare_issue(severity="info")],
        latest_run_id=None, latest_scan_at=None, resolved=False,
    )
    assert info_only[0].severity == "info"


def test_outstanding_filter_by_file_kind(client):
    body = client.get(
        "/manage/issues", params={"file_kind": "acquisition_toml"}
    ).json()
    assert len(body) == 1
    assert body[0]["scope"] == "acquisition"
    assert body[0]["acquisition_id"] == "acq1"


def test_outstanding_groups_by_md_run_id(client):
    """Two md_run_toml issues on the same sample but different runs surface as
    two groups, each exposing its own md_run_id."""
    body = client.get(
        "/manage/issues", params={"file_kind": "md_run_toml"}
    ).json()
    assert {g["md_run_id"] for g in body} == {"run_a", "run_b"}
    assert all(g["sample_id"] == "sample-1" for g in body)


def test_outstanding_text_query(client):
    body = client.get("/manage/issues", params={"q": "typo"}).json()
    assert len(body) == 1
    assert body[0]["sample_id"] == "sample-2"


def test_outstanding_text_query_matches_acquisition_id(client):
    body = client.get("/manage/issues", params={"q": "acq1"}).json()
    assert len(body) == 1
    assert body[0]["acquisition_id"] == "acq1"


def test_outstanding_text_query_matches_file_path(client):
    # A term only present in file_path (not message/location/ids) still hits.
    body = client.get("/manage/issues", params={"q": "scratch"}).json()
    assert len(body) == 1
    assert body[0]["sample_id"] == "sample-2"


def test_outstanding_text_query_all_terms_must_match(client):
    # "sample-1 acq1": both terms must match, narrowing to the acq1 group even
    # though sample-1 also has sample-scope issues (which lack "acq1").
    body = client.get("/manage/issues", params={"q": "sample-1 acq1"}).json()
    assert len(body) == 1
    assert body[0]["acquisition_id"] == "acq1"


# ── GET /manage/issues/resolved (recently resolved, §9.3) ──────────────────


def test_resolved_default_window_24h(client):
    body = client.get("/manage/issues/resolved").json()
    cats = {i["category"] for g in body for i in g["issues"]}
    assert "resolved_recent" in cats   # resolved 1h ago
    assert "resolved_old" not in cats  # resolved 3 days ago
    g = next(g for g in body if any(
        i["category"] == "resolved_recent" for i in g["issues"]
    ))
    assert g["resolved_at"] is not None
    assert g["resolved_run_id"] == "run-completed"


def test_resolved_window_widens(client):
    body = client.get(
        "/manage/issues/resolved", params={"within_hours": 24 * 7}
    ).json()
    cats = {i["category"] for g in body for i in g["issues"]}
    assert "resolved_recent" in cats
    assert "resolved_old" in cats


def test_resolved_shape_matches_outstanding_plus_resolved(client):
    body = client.get("/manage/issues/resolved").json()
    g = body[0]
    # Same grouping shape as outstanding, plus resolved_at / resolved_run_id.
    for key in (
        "scope", "sample_id", "file_kind", "severity", "issues",
        "first_seen_at", "last_seen_at", "resolved_at", "resolved_run_id",
    ):
        assert key in g


# ── GET /manage/scans ──────────────────────────────────────────────────────


def test_list_scans_descending_by_start(client):
    body = client.get("/manage/scans").json()
    ids = [r["scan_run_id"] for r in body]
    assert ids == ["run-running", "run-failed", "run-completed"]


def test_get_scan_by_id_full_payload(client):
    body = client.get("/manage/scans/run-completed").json()
    assert body["status"] == "completed"
    assert body["n_upserted"] == 5
    assert body["n_warning_active"] == 3
    assert body["n_error_active"] == 1


def test_get_scan_running_has_null_fields(client):
    body = client.get("/manage/scans/run-running").json()
    assert body["ended_at"] is None
    assert body["n_upserted"] is None


def test_get_scan_404(client):
    assert client.get("/manage/scans/nope").status_code == 404


# ── GET /manage/scans/{id}/logs ────────────────────────────────────────────


def test_scan_logs_ordered_by_seq(client):
    body = client.get("/manage/scans/run-completed/logs").json()
    assert [r["seq"] for r in body] == [1, 2, 3, 4]
    # sample_id context preserved per line.
    assert body[0]["sample_id"] is None
    assert body[1]["sample_id"] == "sample-1"


def test_scan_logs_filter_by_level(client):
    body = client.get(
        "/manage/scans/run-completed/logs", params={"level": "WARNING"}
    ).json()
    assert len(body) == 1
    assert body[0]["level"] == "WARNING"


def test_scan_logs_filter_by_query(client):
    body = client.get(
        "/manage/scans/run-completed/logs", params={"q": "missing"}
    ).json()
    assert len(body) == 1
    assert "missing" in body[0]["message"]


def test_scan_logs_404_for_unknown_run(client):
    assert client.get("/manage/scans/nope/logs").status_code == 404


# ── GET /manage/scans/{id}/samples ─────────────────────────────────────────


def test_scan_samples_all(client):
    body = client.get("/manage/scans/run-completed/samples").json()
    by_sample = {r["sample_id"]: r for r in body}
    assert by_sample["sample-1"]["outcome"] == "upserted"
    assert by_sample["sample-2"]["outcome"] == "skipped"
    assert by_sample["ghost"]["outcome"] == "failed"
    assert by_sample["ghost"]["detail"] == "assemble failed"


def test_scan_samples_filter_by_outcome(client):
    body = client.get(
        "/manage/scans/run-completed/samples", params={"outcome": "failed"}
    ).json()
    assert [r["sample_id"] for r in body] == ["ghost"]


def test_scan_samples_rejects_unknown_outcome(client):
    r = client.get(
        "/manage/scans/run-completed/samples", params={"outcome": "bogus"}
    )
    assert r.status_code == 422


def test_scan_samples_404_for_unknown_run(client):
    assert client.get("/manage/scans/nope/samples").status_code == 404


# ── GET /manage/deletions (§08a) ────────────────────────────────────────────


def test_deletions_newest_first(client):
    body = client.get("/manage/deletions").json()
    detected = [r["detected_at"] for r in body]
    assert detected == sorted(detected, reverse=True)
    assert len(body) == 4


def test_deletions_filter_by_entity_type(client):
    body = client.get(
        "/manage/deletions", params={"entity_type": "raw_tomogram"}
    ).json()
    assert len(body) == 1
    assert body[0]["sample_id"] == "sample-1"
    assert body[0]["entity_id"] == "t1"
    assert body[0]["last_known_path"] == "/data/sample-1/acq1/raw/t1.mrc"
    # §08c: ordinary deletion events (no `kind` set at insert) default to
    # "deletion" — the fixture rows above never pass `kind` explicitly.
    assert body[0]["kind"] == "deletion"


def test_deletions_filter_by_sample_id(client):
    body = client.get(
        "/manage/deletions", params={"sample_id": "sample-9"}
    ).json()
    assert len(body) == 1
    assert body[0]["entity_type"] == "sample"
    assert body[0]["scan_run_id"] == "run-failed"


def test_deletions_filter_by_within_hours(client):
    # 1h window excludes the sample-old event (100_000s ≈ 27.8h ago) while
    # comfortably including the recent events. A tighter (e.g. 300s) window
    # races the suite runtime: fixtures are stamped relative to _NOW at import
    # time, but the endpoint's cutoff uses time.time() at request time, so a
    # slow CI run ages the ~260s-old sample-1 events past the boundary.
    body = client.get(
        "/manage/deletions", params={"within_hours": 1.0}
    ).json()
    sample_ids = {r["sample_id"] for r in body}
    assert "sample-old" not in sample_ids
    assert sample_ids == {"sample-1", "sample-9"}


def test_deletions_pagination(client):
    page1 = client.get("/manage/deletions", params={"limit": 2}).json()
    page2 = client.get(
        "/manage/deletions", params={"limit": 2, "offset": 2}
    ).json()
    assert len(page1) == 2
    assert len(page2) == 2
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})


def test_deletions_no_dismiss_endpoint(client):
    """The feed is append-only — no PATCH/DELETE surface (§08a non-goal)."""
    assert client.patch("/manage/deletions/1").status_code in (404, 405)
    assert client.delete("/manage/deletions/1").status_code in (404, 405)
