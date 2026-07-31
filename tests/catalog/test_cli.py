"""CLI exit-code behavior for `python -m catalog scan`.

These focus on the scan command's exit contract and patch out the actual
scan so they stay fast and independent of the fixture data tree:

* per-sample errors are isolated → exit 0 (a k8s Job/CronJob must not be
  marked failed just because one sample errored)
* a genuine whole-scan failure (scan_root raises) → exit 1
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from catalog import cli, scanner


def _run_scan(tmp_path: Path):
    """Invoke `scan <tmp_path> --init` against a throwaway in-memory DB."""
    return cli.main(
        ["scan", str(tmp_path), "--db", "sqlite:///:memory:", "--init"]
    )


def test_per_sample_errors_exit_zero(tmp_path, capsys):
    report = scanner.ScanReport(
        upserted=2,
        errors=["sample_bad: boom"],
        failed_samples=[("sample_bad", "boom")],
    )
    with patch.object(scanner, "scan_root", return_value=report):
        rc = _run_scan(tmp_path)

    assert rc == 0
    err = capsys.readouterr().err
    # The bad sample is still surfaced loudly on stderr.
    assert "sample_bad: boom" in err
    assert "per-sample error" in err


def test_whole_scan_failure_exits_one(tmp_path, capsys):
    with patch.object(
        scanner, "scan_root", side_effect=RuntimeError("db exploded")
    ):
        rc = _run_scan(tmp_path)

    assert rc == 1
    assert "scan failed: db exploded" in capsys.readouterr().err


def test_clean_scan_exits_zero(tmp_path):
    report = scanner.ScanReport(upserted=3)
    with patch.object(scanner, "scan_root", return_value=report):
        rc = _run_scan(tmp_path)

    assert rc == 0


def test_precompute_runs_mrc_pyramid_when_configured(tmp_path):
    """With a cache root set, the scan runs `mrc-pyramid build --from-file` over
    exactly the catalogued tomogram relpaths (not a tree glob)."""
    report = scanner.ScanReport(upserted=1)
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["list"] = Path(cmd[cmd.index("--from-file") + 1]).read_text()
        return subprocess.CompletedProcess(cmd, 0)

    with patch.object(scanner, "scan_root", return_value=report), \
         patch.object(cli, "_tomogram_relpaths", return_value=["s/a1/t1.mrc", "s/a1/t2.mrc"]), \
         patch("shutil.which", return_value="/usr/bin/mrc-pyramid"), \
         patch("subprocess.run", side_effect=fake_run):
        rc = cli.main([
            "scan", str(tmp_path), "--db", "sqlite:///:memory:", "--init",
            "--precompute-cache-root", "/cache",
        ])

    assert rc == 0
    cmd = captured["cmd"]
    assert cmd[:3] == ["mrc-pyramid", "build", "--source-root"]
    assert cmd[3] == str(tmp_path)
    assert cmd[4:6] == ["--cache-root", "/cache"]
    assert "--from-file" in cmd
    # the list file holds exactly the tomogram relpaths, one per line
    assert captured["list"].split() == ["s/a1/t1.mrc", "s/a1/t2.mrc"]


def test_precompute_skipped_when_no_tomograms(tmp_path):
    """An empty catalog ⇒ no relpaths ⇒ mrc-pyramid is never invoked."""
    report = scanner.ScanReport(upserted=1)
    with patch.object(scanner, "scan_root", return_value=report), \
         patch("shutil.which", return_value="/usr/bin/mrc-pyramid"), \
         patch("subprocess.run") as run:
        rc = cli.main([
            "scan", str(tmp_path), "--db", "sqlite:///:memory:", "--init",
            "--precompute-cache-root", "/cache",
        ])

    assert rc == 0
    run.assert_not_called()


def test_precompute_skipped_when_cli_not_on_path(tmp_path):
    """A missing mrc-pyramid does not fail the run (scale 0 still served)."""
    report = scanner.ScanReport(upserted=1)
    with patch.object(scanner, "scan_root", return_value=report), \
         patch("shutil.which", return_value=None), \
         patch("subprocess.run") as run:
        rc = cli.main([
            "scan", str(tmp_path), "--db", "sqlite:///:memory:", "--init",
            "--precompute-cache-root", "/cache",
        ])

    assert rc == 0
    run.assert_not_called()


def test_precompute_skipped_when_unset(tmp_path, monkeypatch):
    """No cache root (arg or $MRCNG_CACHE_ROOT) ⇒ mrc-pyramid is never invoked."""
    monkeypatch.delenv("MRCNG_CACHE_ROOT", raising=False)
    report = scanner.ScanReport(upserted=1)
    with patch.object(scanner, "scan_root", return_value=report), \
         patch("subprocess.run") as run:
        rc = _run_scan(tmp_path)

    assert rc == 0
    run.assert_not_called()
