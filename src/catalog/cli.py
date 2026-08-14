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
        help=(
            "directory for pre-generated thumbnail cache (defaults to "
            "$CATALOG_THUMBNAIL_DIR, else ./data/.thumbnail-cache in the cwd — "
            "kept out of the shared data root so concurrent devs don't race "
            "on the same cache files)"
        ),
    )
    scan.add_argument(
        "--md-preview-dir",
        default=os.environ.get("CATALOG_MD_PREVIEW_DIR"),
        help=(
            "directory for the OVITO MD-preview cache, served by the API's "
            "/md-previews route (defaults to $CATALOG_MD_PREVIEW_DIR, else "
            "./data/.md-preview-cache in the cwd). Requires the OVITO "
            "dependency (pixi 'catalog' feature)."
        ),
    )
    scan.add_argument(
        "--precompute-cache-root",
        default=os.environ.get("MRCNG_CACHE_ROOT"),
        help=(
            "build the Neuroglancer precomputed pyramid cache here after "
            "scanning, via `mrc-pyramid build` (defaults to $MRCNG_CACHE_ROOT; "
            "skipped if unset)"
        ),
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

    thumbnail_dir = (
        Path(args.thumbnail_dir)
        if args.thumbnail_dir
        else Path.cwd() / "data" / ".thumbnail-cache"
    )
    thumbnail_dir.mkdir(parents=True, exist_ok=True)

    md_preview_dir = (
        Path(args.md_preview_dir)
        if args.md_preview_dir
        else Path.cwd() / "data" / ".md-preview-cache"
    )
    md_preview_dir.mkdir(parents=True, exist_ok=True)

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
            md_preview_dir=md_preview_dir,
        )
    except Exception as e:  # noqa: BLE001
        print(f"scan failed: {e}", file=sys.stderr)
        return 1

    print(f"upserted: {report.upserted}")
    print(f"skipped:  {report.skipped}")
    if report.thumbnails_healed:
        print(f"thumbnails_healed: {report.thumbnails_healed}")
    if report.md_previews_healed:
        print(f"md_previews_healed: {report.md_previews_healed}")
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

    if args.precompute_cache_root:
        _run_precompute(engine, args.root, args.precompute_cache_root)

    return 0


def _tomogram_relpaths(engine, root: Path) -> list[str]:
    """Relpaths (under ``root``) of every catalogued tomogram's MRC.

    Read from the tomogram tables after the scan has committed. These are the
    only volumes the API ever builds Neuroglancer links for, so precomputing
    exactly this set avoids wasting cache on sibling ``.mrc`` files (gain
    references, etc.) that a whole-tree glob would sweep in. Paths outside
    ``root`` are skipped (defensive — the scanner records paths under the data
    root the API validates against).
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from catalog import orm

    root = root.resolve()
    seen: set[str] = set()
    out: list[str] = []
    with Session(engine) as session:
        for model in (orm.PostProcessedTomogramORM, orm.RawTomogramORM):
            rows = session.execute(
                select(model.mrc_path).where(model.mrc_path.is_not(None))
            )
            for (mrc_path,) in rows:
                p = Path(mrc_path)
                abs_p = p if p.is_absolute() else (root / p)
                try:
                    rel = abs_p.resolve().relative_to(root).as_posix()
                except ValueError:
                    continue  # stored path outside the scan root
                if rel not in seen:
                    seen.add(rel)
                    out.append(rel)
    return out


def _run_precompute(engine, root: Path, cache_root: str) -> None:
    """Build the Neuroglancer precomputed pyramid cache for the catalogued tomograms.

    Runs `mrc-pyramid build` (from the mrc-ng-server dependency) over exactly the
    tomogram MRCs in the catalog — fed as a `--from-file` list, not a tree glob,
    so sibling non-tomogram `.mrc` files are never built. The command is
    idempotent and incremental (it fingerprint-skips volumes already up to date),
    and runs here after scan_root has committed, so the heavy per-volume I/O is
    outside every DB transaction.

    A build failure does NOT fail the run: mrc-ng-server still serves scale 0
    directly from the MRC, so Neuroglancer links keep working; only downsampled
    zoom-out is missing until the cache is rebuilt. So this warns and returns
    rather than raising.
    """
    import os
    import shutil
    import subprocess
    import tempfile

    if shutil.which("mrc-pyramid") is None:
        logger.warning(
            "precompute: `mrc-pyramid` not on PATH — is mrc-ng-server "
            "installed? Skipping cache build (scale 0 still served)."
        )
        return

    relpaths = _tomogram_relpaths(engine, root)
    if not relpaths:
        logger.info("precompute: no catalogued tomograms to build; skipping")
        return

    fd, list_path = tempfile.mkstemp(prefix="mrcng-build-", suffix=".txt")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(relpaths) + "\n")
        cmd = [
            "mrc-pyramid", "build",
            "--source-root", str(root),
            "--cache-root", cache_root,
            "--from-file", list_path,
        ]
        logger.info("precompute: building {} tomogram pyramid(s)", len(relpaths))
        result = subprocess.run(cmd)  # noqa: S603 — fixed argv, no shell
        if result.returncode != 0:
            logger.warning(
                "precompute: `mrc-pyramid build` exited {} — some pyramids may "
                "be missing (scale 0 still served from the MRC).",
                result.returncode,
            )
        else:
            logger.info("precompute: cache build complete")
    finally:
        os.unlink(list_path)


if __name__ == "__main__":
    sys.exit(main())
