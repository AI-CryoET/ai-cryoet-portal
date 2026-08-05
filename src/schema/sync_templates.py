"""Sync the starter-directory template copies from the canonical templates.

There are multiple on-disk copies of each researcher template:

- the standalone copies under ``templates/`` (canonical), and
- the starter-directory copies under ``templates/sample_id_experimental/``
  and ``templates/sample_id_simulation/`` that a researcher copies
  wholesale to begin a new sample. The two skeletons differ in their
  empty-directory layout (experimental has ``Frames/``/``Gains/``/
  ``Alignments/``; simulation has ``MdRuns/`` and wraps acquisitions in
  ``SyntheticCryoET/``) — the file contents are identical across both, so
  each canonical template fans out to both skeletons. ``reconstruction.toml``
  fans out to the ``Reconstructions/reconstruction_alignment_id/`` folder
  inside each skeleton's acquisition directory.

All copies must stay identical to their canonical source. This script
regenerates the starter copies from the canonical ones.
``tests/test_repo_consistency.py`` asserts they match, so a forgotten sync
fails the test suite.

Usage:
    pixi run sync-templates          # rewrite the starter copies
    python -m schema.sync_templates --check   # exit 1 if out of date
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# src/schema/sync_templates.py -> repo root is three parents up
# (src/schema -> src -> repo root), where templates/ lives.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# canonical (source) -> starter copy (generated). Keep these paths in sync
# with the directory layout documented in README.md. Each canonical template
# fans out to both the experimental and simulation starter skeletons; the
# simulation skeleton nests acquisitions under SyntheticCryoET/.
_TEMPLATES = _REPO_ROOT / "templates"

TEMPLATE_PAIRS: list[tuple[Path, Path]] = [
    (
        _TEMPLATES / "sample.toml",
        _TEMPLATES / "sample_id_experimental" / "sample.toml",
    ),
    (
        _TEMPLATES / "acquisition.toml",
        _TEMPLATES / "sample_id_experimental" / "acquisition_id" / "acquisition.toml",
    ),
    (
        _TEMPLATES / "sample.toml",
        _TEMPLATES / "sample_id_simulation" / "sample.toml",
    ),
    (
        _TEMPLATES / "acquisition.toml",
        _TEMPLATES / "sample_id_simulation" / "SyntheticCryoET" / "acquisition_id" / "acquisition.toml",
    ),
    (
        _TEMPLATES / "md_run.toml",
        _TEMPLATES / "sample_id_simulation" / "MdRuns" / "md_run_id" / "md_run.toml",
    ),
    (
        _TEMPLATES / "reconstruction.toml",
        _TEMPLATES / "sample_id_experimental" / "acquisition_id" / "Reconstructions"
        / "reconstruction_alignment_id" / "reconstruction.toml",
    ),
    (
        _TEMPLATES / "reconstruction.toml",
        _TEMPLATES / "sample_id_simulation" / "SyntheticCryoET" / "acquisition_id"
        / "Reconstructions" / "reconstruction_alignment_id" / "reconstruction.toml",
    ),
]


def _out_of_sync() -> list[tuple[Path, Path]]:
    """Return (canonical, copy) pairs whose copy differs from the canonical."""
    stale: list[tuple[Path, Path]] = []
    for canonical, copy in TEMPLATE_PAIRS:
        canonical_text = canonical.read_text()
        if not copy.is_file() or copy.read_text() != canonical_text:
            stale.append((canonical, copy))
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any starter copy is out of date; write nothing",
    )
    args = parser.parse_args(argv)

    stale = _out_of_sync()

    if args.check:
        if stale:
            for _canonical, copy in stale:
                print(f"out of date: {copy.relative_to(_REPO_ROOT)}")
            print("run `pixi run sync-templates` to regenerate")
            return 1
        print("starter templates are in sync")
        return 0

    for canonical, copy in stale:
        copy.write_text(canonical.read_text())
        print(f"wrote {copy.relative_to(_REPO_ROOT)}")
    if not stale:
        print("starter templates already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
