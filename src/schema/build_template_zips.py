"""Zip the researcher starter-template directories into static downloads.

The canonical starter dirs under ``templates/sample_id_experimental/`` and
``templates/sample_id_simulation/`` are zipped into
``frontend/public/templates/{name}.zip`` and served by the frontend as
"Download template" links on the /data-organization page.

Zips are deterministic (sorted entries, fixed timestamp, ZIP_STORED) so
``tests/test_template_zips.py`` can byte-compare the committed files against a
fresh build and fail the suite on drift.

Usage:
    pixi run template-zips              # rewrite the committed zips
    python -m schema.build_template_zips --check   # exit 1 if out of date
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

# src/schema/build_template_zips.py -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES = _REPO_ROOT / "templates"
_OUT_DIR = _REPO_ROOT / "frontend" / "public" / "templates"

# Fixed DOS timestamp (zip epoch) so output bytes never depend on mtimes.
_FIXED_DT = (1980, 1, 1, 0, 0, 0)

# (source template dir, committed output zip). The zip's top-level folder is
# the source dir name, so unzip yields a renamable starter directory.
ZIP_TARGETS: list[tuple[Path, Path]] = [
    (_TEMPLATES / "sample_id_experimental", _OUT_DIR / "sample_id_experimental.zip"),
    (_TEMPLATES / "sample_id_simulation", _OUT_DIR / "sample_id_simulation.zip"),
]


def build_zip(src_dir: Path) -> bytes:
    """Return a deterministic ZIP_STORED archive of ``src_dir``.

    Entries are sorted and prefixed with ``src_dir.name/``; empty directories
    are preserved as explicit directory entries.
    """
    buf = io.BytesIO()
    prefix = src_dir.name
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for path in sorted(src_dir.rglob("*"), key=lambda p: p.relative_to(src_dir).as_posix()):
            rel = path.relative_to(src_dir).as_posix()
            arcname = f"{prefix}/{rel}"
            if path.is_dir():
                info = zipfile.ZipInfo(arcname + "/", date_time=_FIXED_DT)
                info.external_attr = (0o40755 << 16) | 0x10  # dir + drwxr-xr-x
                zf.writestr(info, b"")
            else:
                info = zipfile.ZipInfo(arcname, date_time=_FIXED_DT)
                info.external_attr = 0o644 << 16
                zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def _stale() -> list[tuple[Path, Path]]:
    out = []
    for src, dest in ZIP_TARGETS:
        if not dest.is_file() or dest.read_bytes() != build_zip(src):
            out.append((src, dest))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any committed zip is out of date; write nothing",
    )
    args = parser.parse_args(argv)

    stale = _stale()
    if args.check:
        if stale:
            for _src, dest in stale:
                print(f"out of date: {dest.relative_to(_REPO_ROOT)}")
            print("run `pixi run template-zips` to regenerate")
            return 1
        print("template zips are in sync")
        return 0

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    for src, dest in ZIP_TARGETS:
        dest.write_bytes(build_zip(src))
        print(f"wrote {dest.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
