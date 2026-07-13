#!/usr/bin/env python3
"""Migrate on-disk Reconstructions from the OLD per-id-folder layout to the NEW
file-based layout, across both data arms.

OLD (both arms)::

    {acq}/Reconstructions/Tomograms/{tid}/<arbitrary files>
    {acq}/Reconstructions/Annotations/{aid}/<arbitrary files>

The id is the *folder* name; the files inside are named arbitrarily.

NEW::

    Experimental:
        {acq}/Reconstructions/{tilt_series_id}/Tomograms/{tid}.<ext>
        {acq}/Reconstructions/{tilt_series_id}/Annotations/{aid}.<ext>
    Simulation (flat, no tilt-series level):
        {acq}/Reconstructions/Tomograms/{tid}.<ext>
        {acq}/Reconstructions/Annotations/{aid}.<ext>

Each moved file is RENAMED so its stem == the old folder id (``{tid}.<ext>`` /
``{aid}.<ext>``), so ids survive into ``derived_from`` / ``target_tomogram`` /
DB PKs. The real extension is preserved, including multi-suffix ``.ome.zarr``.

For experimental data the destination tilt-series folder is the tomogram's
authored ``tilt_series_id`` (read from ``acquisition.toml``); an annotation
routes through its ``target_tomogram``'s tilt series. Anything whose target
tilt series can't be resolved is LEFT in place and warned about. Same-extension
collisions inside one id-folder are also left + warned.

By default this also strips the now-derived ``tilt_series_id = ...`` line from
every ``[raw_tomogram]`` / ``[[post_processed_tomogram]]`` block (disable with
``--no-strip-toml``).

**Dry-run by default** — writes the plan to a CSV (default ``./reorg_plan.csv``,
override with ``--csv``) and touches nothing. Pass ``--apply`` to perform the
moves, toml edits, and empty-dir cleanup. Idempotent: it acts only on
OLD-layout subFOLDERS, so a second run over migrated data is a no-op.

Usage
-----
    # dry run against $CATALOG_DATA_ROOT (writes ./reorg_plan.csv, changes nothing)
    ./reorg_reconstructions.py

    # dry run against a specific root, custom CSV path
    ./reorg_reconstructions.py --root /path/to/data --csv /tmp/plan.csv

    # actually perform the migration
    ./reorg_reconstructions.py --root /path/to/data --apply

    # apply without stripping tilt_series_id from the tomls
    ./reorg_reconstructions.py --root /path/to/data --apply --no-strip-toml
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from schema.layout import (
    TOP_LEVEL_EXPERIMENTAL,
    TOP_LEVEL_MD_SIMULATION,
    entity_id_from_path,
    infer_arm,
    is_zarr_dir,
)
from schema.schema import DataSource

# Line-level matcher for the derived ``tilt_series_id`` key. tomllib is
# read-only and the tomls are comment-heavy, so we edit lines. The key is
# unambiguous: [[tilt_series]] blocks use ``id`` (not ``tilt_series_id``) and
# annotations use ``target_tomogram``, so any ``tilt_series_id =`` line belongs
# to a [raw_tomogram] / [[post_processed_tomogram]] block.
_TILT_SERIES_ID_RE = re.compile(r"^\s*tilt_series_id\s*=")


@dataclass
class ReorgPlan:
    """A pure description of the migration — no filesystem side effects."""

    moves: list[tuple[Path, Path]] = field(default_factory=list)  # (src, dst)
    toml_edits: list[Path] = field(default_factory=list)  # acquisition.toml to strip
    dirs_to_remove: list[Path] = field(default_factory=list)  # remove only if empty
    warnings: list[str] = field(default_factory=list)


def _suffix_of(path: Path) -> str:
    """Return ``path``'s extension, including a multi-suffix ``.ome.zarr``.

    Complements ``entity_id_from_path`` (which returns the stem): the suffix is
    whatever the stem does not cover, so ``y.mrc`` -> ``.mrc`` and
    ``y.ome.zarr`` -> ``.ome.zarr``.
    """
    return path.name[len(entity_id_from_path(path)) :]


def _read_toml_maps(toml_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(tomogram_id -> tilt_series_id, annotation_id -> target_tomogram)``.

    Only tomograms with an authored ``tilt_series_id`` land in the first map;
    only annotations with a ``target_tomogram`` land in the second. A missing or
    unparseable toml yields two empty maps (callers then warn per entity).
    """
    tomo_ts: dict[str, str] = {}
    ann_target: dict[str, str] = {}
    if not toml_path.is_file():
        return tomo_ts, ann_target
    try:
        data = tomllib.loads(toml_path.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return tomo_ts, ann_target

    raw = data.get("raw_tomogram")
    tomo_blocks = [raw] if isinstance(raw, dict) else []
    tomo_blocks += [
        b for b in data.get("post_processed_tomogram", []) if isinstance(b, dict)
    ]
    for block in tomo_blocks:
        tid = block.get("id")
        ts_id = block.get("tilt_series_id")
        if tid is not None and ts_id is not None:
            tomo_ts[str(tid)] = str(ts_id)

    for block in data.get("annotation", []):
        if not isinstance(block, dict):
            continue
        aid = block.get("id")
        target = block.get("target_tomogram")
        if aid is not None and target is not None:
            ann_target[str(aid)] = str(target)

    return tomo_ts, ann_target


def _old_id_folders(parent: Path) -> list[Path]:
    """OLD-layout id subfolders directly under ``parent`` (Tomograms/Annotations).

    Only real directories that are NOT zarr stores count — this is what makes
    the migration idempotent. New-layout entities are files (``{id}.mrc``) or
    zarr dirs (``{id}.ome.zarr``); neither is an OLD id-folder, so a re-run over
    migrated data finds nothing to move.
    """
    if not parent.is_dir():
        return []
    return sorted(
        c for c in parent.iterdir() if c.is_dir() and not is_zarr_dir(c)
    )


def _entity_children(id_folder: Path) -> list[Path]:
    """Files and zarr-dirs directly inside an OLD id-folder (the things to move)."""
    out: list[Path] = []
    for child in sorted(id_folder.iterdir()):
        if child.is_file() or (child.is_dir() and is_zarr_dir(child)):
            out.append(child)
    return out


def _plan_id_folder(
    id_folder: Path, dest_dir: Path, kind: str, plan: ReorgPlan
) -> bool:
    """Plan renaming every child of ``id_folder`` to ``{id}.<ext>`` in ``dest_dir``.

    ``kind`` is ``"tomogram"`` / ``"annotation"`` (for warning text). A
    same-extension collision inside the folder (e.g. two ``.mrc``) leaves the
    whole entity in place with a warning — as does a planned destination that
    already exists on disk (never silently overwrite real data). A leftover
    non-zarr subdirectory only warns; the files still move (never lose data).

    Returns True iff every child was queued for a move (so ``id_folder`` will
    be emptied by ``apply_reorg``); False if the entity was left in place.
    """
    entity_id = id_folder.name
    children = _entity_children(id_folder)
    residue = sorted(
        c for c in id_folder.iterdir() if c.is_dir() and not is_zarr_dir(c)
    )
    if residue:
        names = ", ".join(r.name for r in residue)
        plan.warnings.append(
            f"{id_folder}: {kind} '{entity_id}' has leftover non-zarr "
            f"subdirector{'y' if len(residue) == 1 else 'ies'} ({names}) that will "
            f"not be moved and will strand the OLD id-folder on disk."
        )
    if not children:
        return False
    suffixes = [_suffix_of(c) for c in children]
    if len(set(suffixes)) != len(suffixes):
        counts = Counter(suffixes)
        dup_suffix = next(s for s, n in counts.items() if n > 1)
        plan.warnings.append(
            f"{id_folder}: {kind} '{entity_id}' has multiple files with the same "
            f"extension — would collide on '{entity_id}{dup_suffix}'; left in place."
        )
        return False
    dsts = [dest_dir / f"{entity_id}{suffix}" for suffix in suffixes]
    existing_dst = next((d for d in dsts if d.exists()), None)
    if existing_dst is not None:
        plan.warnings.append(
            f"{id_folder}: {kind} '{entity_id}' destination already exists, "
            f"skipping to avoid overwrite: {existing_dst}"
        )
        return False
    for child, dst in zip(children, dsts):
        plan.moves.append((child, dst))
    plan.dirs_to_remove.append(id_folder)  # emptied by the moves above
    return True


def _plan_acquisition(
    acq_dir: Path,
    sample_dir: Path,
    strip_tilt_series_id: bool,
    plan: ReorgPlan,
) -> None:
    recon = acq_dir / "Reconstructions"
    if not recon.is_dir():
        return
    data_source, _ = infer_arm(sample_dir)
    is_experimental = data_source == DataSource.experimental

    tomo_ts, ann_target = _read_toml_maps(acq_dir / "acquisition.toml")

    old_tomo = recon / "Tomograms"
    queued_tomo_folders: set[Path] = set()
    for folder in _old_id_folders(old_tomo):
        tid = folder.name
        if is_experimental:
            ts_id = tomo_ts.get(tid)
            if not ts_id:
                plan.warnings.append(
                    f"{folder}: tomogram '{tid}' has no authored tilt_series_id "
                    f"(ambiguous target tilt series); left in place."
                )
                continue
            dest_dir = recon / ts_id / "Tomograms"
        else:
            dest_dir = recon / "Tomograms"  # flat
        if _plan_id_folder(folder, dest_dir, "tomogram", plan):
            queued_tomo_folders.add(folder)

    old_ann = recon / "Annotations"
    queued_ann_folders: set[Path] = set()
    for folder in _old_id_folders(old_ann):
        aid = folder.name
        if is_experimental:
            target = ann_target.get(aid)
            if target is None:
                plan.warnings.append(
                    f"{folder}: annotation '{aid}' has no resolvable target_tomogram "
                    f"(no matching [[annotation]] block); left in place."
                )
                continue
            ts_id = tomo_ts.get(target)
            if not ts_id:
                plan.warnings.append(
                    f"{folder}: annotation '{aid}' target_tomogram '{target}' has no "
                    f"authored tilt_series_id; left in place."
                )
                continue
            dest_dir = recon / ts_id / "Annotations"
        else:
            dest_dir = recon / "Annotations"  # flat
        if _plan_id_folder(folder, dest_dir, "annotation", plan):
            queued_ann_folders.add(folder)

    # Attempt to remove the emptied OLD parent dirs — but only when this run
    # actually leaves them with nothing behind: every current child must be one
    # of the id-folders we just queued to move out. At plan time ``iterdir()``
    # still sees the OLD id-folders (the moves haven't run yet), so for
    # simulation (flat) the old dir IS queued here too; it survives in practice
    # only because ``apply_reorg`` uses ``os.rmdir``, which refuses to remove it
    # once the moved-in files have repopulated it as a non-empty dir. Any
    # id-folder left in place (unresolvable target, collision, etc.) still
    # correctly excludes the parent from this set.
    for old_dir, queued in (
        (old_tomo, queued_tomo_folders),
        (old_ann, queued_ann_folders),
    ):
        if old_dir.is_dir():
            children = list(old_dir.iterdir())
            if children and all(c in queued for c in children):
                plan.dirs_to_remove.append(old_dir)

    # Strip the now-derived tilt_series_id from the toml, if any such line exists.
    if strip_tilt_series_id:
        toml_path = acq_dir / "acquisition.toml"
        if toml_path.is_file():
            text = toml_path.read_text()
            if _strip_tilt_series_id_lines(text) != text:
                plan.toml_edits.append(toml_path)


def _iter_acquisitions(root: Path) -> list[tuple[Path, Path]]:
    """Yield ``(acq_dir, sample_dir)`` for both arms under ``root``."""
    out: list[tuple[Path, Path]] = []

    exp_root = root / TOP_LEVEL_EXPERIMENTAL
    if exp_root.is_dir():
        for sample_dir in sorted(p for p in exp_root.iterdir() if p.is_dir()):
            for acq_dir in sorted(p for p in sample_dir.iterdir() if p.is_dir()):
                out.append((acq_dir, sample_dir))

    sim_root = root / TOP_LEVEL_MD_SIMULATION
    if sim_root.is_dir():
        for sub_dir in sorted(p for p in sim_root.iterdir() if p.is_dir()):
            for sample_dir in sorted(p for p in sub_dir.iterdir() if p.is_dir()):
                synthetic = sample_dir / "SyntheticCryoET"
                if not synthetic.is_dir():
                    continue
                for acq_dir in sorted(
                    p for p in synthetic.iterdir() if p.is_dir()
                ):
                    out.append((acq_dir, sample_dir))

    return out


def plan_reorg(root: Path, strip_tilt_series_id: bool = True) -> ReorgPlan:
    """Walk ``root`` and return a :class:`ReorgPlan`. Performs NO FS mutation."""
    plan = ReorgPlan()
    for acq_dir, sample_dir in _iter_acquisitions(root):
        _plan_acquisition(acq_dir, sample_dir, strip_tilt_series_id, plan)
    return plan


def _strip_tilt_series_id_lines(text: str) -> str:
    """Return ``text`` with every ``tilt_series_id = ...`` line removed."""
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not _TILT_SERIES_ID_RE.match(line)
    )


def apply_reorg(plan: ReorgPlan) -> None:
    """Perform the planned moves, toml edits, and empty-dir cleanup.

    Never deletes non-empty data: directory removal uses ``os.rmdir`` (which
    refuses non-empty dirs) and swallows the resulting error, so an id-folder
    that was left in place — or a flat simulation parent still holding files —
    survives untouched.
    """
    for src, dst in plan.moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)  # same filesystem — atomic; works for zarr dirs too

    for toml_path in plan.toml_edits:
        text = toml_path.read_text()
        new_text = _strip_tilt_series_id_lines(text)
        if new_text != text:
            toml_path.write_text(new_text)

    # Deepest first so an id-folder is removed before its parent Tomograms/ dir.
    for directory in sorted(
        plan.dirs_to_remove, key=lambda p: len(p.parts), reverse=True
    ):
        try:
            os.rmdir(directory)
        except OSError:
            pass  # non-empty or already gone — leave it


def _write_plan_csv(plan: ReorgPlan, csv_path: Path) -> None:
    """Write the dry-run plan (moves, toml edits, warnings) as CSV rows."""
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["action", "src", "dst", "note"])
        for src, dst in plan.moves:
            writer.writerow(["move", src, dst, ""])
        for toml_path in plan.toml_edits:
            writer.writerow(["toml_edit", toml_path, "", ""])
        for warning in plan.warnings:
            writer.writerow(["warning", "", "", warning])


def _print_plan(plan: ReorgPlan, *, applied: bool) -> None:
    tag = "✓" if applied else "-"
    if plan.moves:
        print(f"\n{'Moved' if applied else 'Planned moves'} ({len(plan.moves)}):")
        for src, dst in plan.moves:
            print(f"  {tag}  {src}\n        ->  {dst}")
    else:
        print("\nNo moves.")

    if plan.toml_edits:
        verb = "Stripped" if applied else "Would strip"
        print(f"\n{verb} tilt_series_id from ({len(plan.toml_edits)}):")
        for toml_path in plan.toml_edits:
            print(f"  {tag}  {toml_path}")

    if plan.warnings:
        print(f"\nWarnings / skipped ({len(plan.warnings)}):", file=sys.stderr)
        for warning in plan.warnings:
            print(f"  ! {warning}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Migrate Reconstructions from the old per-id-folder layout "
        "to the new file-based layout. Dry-run by default; pass --apply to move.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    default_root = os.environ.get("CATALOG_DATA_ROOT")
    ap.add_argument(
        "--root",
        type=Path,
        default=Path(default_root) if default_root else None,
        required=default_root is None,
        help="Data root to migrate (default: $CATALOG_DATA_ROOT).",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Perform the migration. Without this the script is a dry run.",
    )
    ap.add_argument(
        "--no-strip-toml",
        dest="strip_toml",
        action="store_false",
        help="Do NOT strip the derived tilt_series_id line from the tomls "
        "(default: strip it).",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=Path("reorg_plan.csv"),
        help="Where to write the dry-run plan as CSV (default: ./reorg_plan.csv). "
        "Ignored with --apply.",
    )
    args = ap.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Root is not a directory: {root}")

    plan = plan_reorg(root, strip_tilt_series_id=args.strip_toml)

    print(f"Root: {root}   ({'APPLY' if args.apply else 'DRY RUN'})")
    if args.apply:
        apply_reorg(plan)
        _print_plan(plan, applied=True)
        print("\nDone.")
    else:
        _write_plan_csv(plan, args.csv)
        print(f"Wrote plan to {args.csv}")
        if plan.warnings:
            print(f"Warnings / skipped: {len(plan.warnings)} (see CSV)", file=sys.stderr)
        print(
            "\nDry run — nothing changed. Re-run with --apply to perform the migration."
        )


if __name__ == "__main__":
    main()
