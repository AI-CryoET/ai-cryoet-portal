"""Command-line entry point for the catalog scanner.

Usage::

    python -m catalog scan <root>
        [--db sqlite:///path.db] [--force] [--init]
        [--prune] [--prune-dry-run] [--prune-safety-floor 0.5]
        [--child-prune-safety-floor 0.5] [--child-prune-min-count 3]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from loguru import logger

from catalog import db, scanner


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m catalog")
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser(
        "scan", help="Scan a data root and ingest into the catalog DB."
    )
    scan.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=None,
        help="path to data root (defaults to $CATALOG_DATA_ROOT)",
    )
    scan.add_argument(
        "--db",
        default=os.environ.get("CATALOG_DB_URL", db.DEFAULT_DB_URL),
        help="SQLAlchemy URL (defaults to $CATALOG_DB_URL, else sqlite:///catalog.db)",
    )
    scan.add_argument(
        "--force", action="store_true", help="bypass mtime gating"
    )
    scan.add_argument(
        "--init", action="store_true", help="create tables on a fresh DB"
    )
    scan.add_argument(
        "--prune",
        action="store_true",
        help="soft-delete samples missing from disk",
    )
    scan.add_argument(
        "--prune-dry-run",
        action="store_true",
        help="report would-be soft-deletes without writing",
    )
    scan.add_argument(
        "--prune-safety-floor",
        type=float,
        default=0.5,
        help=(
            "abort prune if fraction of live samples to delete exceeds this "
            "(default 0.5)"
        ),
    )
    scan.add_argument(
        "--child-prune-safety-floor",
        type=float,
        default=0.5,
        help=(
            "abort a sample's upsert if the fraction dropped for a guarded "
            "child type (acquisitions, md_source, raw/post tomograms, "
            "annotations, tilt series) exceeds this (default 0.5)"
        ),
    )
    scan.add_argument(
        "--child-prune-min-count",
        type=int,
        default=3,
        help=(
            "only enforce --child-prune-safety-floor when at least this many "
            "rows existed for the child type (default 3)"
        ),
    )
    scan.add_argument(
        "--thumbnail-dir",
        default=os.environ.get("CATALOG_THUMBNAIL_DIR"),
        help="directory for pre-generated thumbnail cache (defaults to $CATALOG_THUMBNAIL_DIR)",
    )
    scan.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="emit DEBUG logging (per-acquisition detail)",
    )
    scan.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress per-sample progress; only warnings and errors",
    )
    return p


def _configure_logging(args) -> None:
    """Send progress to stderr via loguru. Default INFO (per-sample);
    -v DEBUG (per-acquisition); -q WARNING only."""
    level = "INFO"
    if getattr(args, "verbose", False):
        level = "DEBUG"
    elif getattr(args, "quiet", False):
        level = "WARNING"
    logger.remove()  # drop loguru's default handler before installing ours
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:HH:mm:ss}</green> <level>{level: <7}</level> "
            "<level>{message}</level>"
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return _cmd_scan(args)
    return 2


def _cmd_scan(args) -> int:
    _configure_logging(args)
    root = args.root
    if root is None:
        env_root = os.environ.get("CATALOG_DATA_ROOT")
        if not env_root:
            print(
                "error: no root provided and CATALOG_DATA_ROOT is not set",
                file=sys.stderr,
            )
            return 2
        root = Path(env_root)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    args.root = root

    engine = db.make_engine(args.db)
    if args.init:
        db.init_schema(engine)

    thumbnail_dir = None
    if args.thumbnail_dir:
        thumbnail_dir = Path(args.thumbnail_dir)
        thumbnail_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = scanner.scan_root(
            engine,
            args.root.resolve(),
            force=args.force,
            prune=args.prune,
            prune_dry_run=args.prune_dry_run,
            prune_safety_floor=args.prune_safety_floor,
            child_prune_safety_floor=args.child_prune_safety_floor,
            child_prune_min_count=args.child_prune_min_count,
            thumbnail_dir=thumbnail_dir,
        )
    except Exception as e:  # noqa: BLE001
        print(f"scan failed: {e}", file=sys.stderr)
        return 1

    print(f"upserted: {report.upserted}")
    print(f"skipped:  {report.skipped}")
    if report.thumbnails_healed:
        print(f"thumbnails_healed: {report.thumbnails_healed}")
    print(f"issues: {len(report.issues)}")
    if report.run_issues:
        print(f"run-level issues: {len(report.run_issues)}")
        for w in report.run_issues[:10]:
            print(f"  {w.category}: {w.location}", file=sys.stderr)
    print(f"errors:   {len(report.errors)}")
    if report.conflicts:
        print(f"conflicts: {len(report.conflicts)}")
    if report.would_soft_delete is not None:
        print(f"would soft-delete: {report.would_soft_delete}")
    elif report.soft_deleted:
        print(f"soft-deleted: {report.soft_deleted}")

    if report.errors:
        for e in report.errors[:10]:
            print(f"  error: {e}", file=sys.stderr)
        if len(report.errors) > 10:
            print(f"  (+ {len(report.errors) - 10} more)", file=sys.stderr)
        # Per-sample errors are isolated: the scan rolled them back and
        # catalogued every other sample, so the run as a whole succeeded.
        # Exit 0 so the k8s Job/CronJob isn't marked failed over one bad
        # sample. Genuine whole-scan failures raise out of scan_root and are
        # caught above (return 1).
        print(
            f"scan completed with {len(report.errors)} per-sample error(s); "
            "see above. Exiting 0 — the run as a whole succeeded.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
