#!/usr/bin/env python3
"""Reorganize Janelia cryoET facility microscope output into the ai-cryoet
portal ingestion layout.

The Janelia cryoET facility acquires imaging data with two softwares, each
writing a flat folder of files per session. The data is identified by its
acquisition style — Tomo5 vs SerialEM — not by which lab the sample came from.
As a rule of thumb, Tomo5 is typically used for Gouaux-lab samples and SerialEM
for Rosen-lab samples, but that is only a convention: the script detects the
style from the folder contents and lets you confirm (or override) the lab.

  * Tomo5 style (Thermo Fisher Tomography software; typically Gouaux samples)
      - per-acquisition frames  : <prefix>_<NNN>_<angle>_<YYYYMMDD>_<HHMMSS>_EER.eer
      - per-acquisition mdoc     : <prefix>.mdoc   (already a series-level mdoc
                                   with a global header + [ZValue = N] sections)
      - per-acquisition tiltstack: <prefix>.mrc    (initial tilt series)
      - one shared gain reference: *.gain

  * SerialEM style (typically Rosen samples)
      - per-acquisition frames   : <prefix>_<NNN>_<angle>_<MonDD>_<HH.MM.SS>.eer
      - per-FRAME mdoc           : <frame>.eer.mdoc  (one [FrameSet = 0] each)
      - one shared gain reference: *.gain
    The per-frame mdocs must be COMBINED into one series-level <prefix>.mdoc
    (global header + one [ZValue = N] per tilt, in acquisition order). See
    /groups/cryoet/cryoet/data/rosenlab/example_30bp/mdocs/ for the target shape.

For each acquisition the script lays down the experimental sample-directory
template and populates it:

    {DEST}/{sample_id}/
        sample.toml
        {acquisition_id}/                 <- acquisition_id == common frame prefix
            acquisition.toml             <- [[tilt_series]] block authored for the raw series
            Frames/      <- all .eer frames + the (combined) <acq>.mdoc
            Gains/       <- a copy of the shared *.gain
            Reconstructions/ ...
            TiltSeries/                   <- one folder per tilt series
                raw/                      <- the initial .mrc (Gouaux only);
                    stack/                   id from --tilt-series-id (default "raw")
                        <acq>.mrc
                    alignment/            <- (empty; populated when aligned)

The acquisition.toml's [[tilt_series]] block is filled in to match: a raw,
unaligned series (id = the --tilt-series-id, derived_from = "Frames",
is_aligned = false). The template's placeholder TiltSeries/tilt_series_id/
folder is renamed to that same id so folder and metadata agree.

Placement modes
---------------
Frames are large (hundreds of GB per session), so by DEFAULT the script
*symlinks* every frame/mdoc/mrc/gain into the layout — instant, no extra disk,
and trivial to discard. This is meant for test runs: stage the layout, inspect
it, delete it. The more expensive modes must be opted into explicitly:

    --symlink   (default) link into place; instant, breaks if source moves
    --copy      duplicate bytes; EXPENSIVE, leaves source untouched
    --move      relocate out of source; instant, consumes the source
    --hardlink  link by inode; instant, same-filesystem only

Usage
-----
    # dry run (prints planned actions, touches nothing)
    ./reorg_facility_to_portal.py SOURCE_DIR --dry-run

    # default: symlink everything into place (fast test layout)
    ./reorg_facility_to_portal.py SOURCE_DIR

    # real run that consumes the source, with an explicit sample id
    ./reorg_facility_to_portal.py SOURCE_DIR --sample-id my_sample --move

    # real run that preserves the source by copying every byte (slow)
    ./reorg_facility_to_portal.py SOURCE_DIR --copy

Examples
--------
    ./reorg_facility_to_portal.py \\
        /groups/cryoet/cryoet/data/cryoet-facility/Gouaux_JK3-4_data_collected_by_Tomo5 --dry-run

    ./reorg_facility_to_portal.py \\
        /groups/cryoet/cryoet/data/cryoet-facility/Rosen_JP1-grid4_data_collected_by_Serialem

On each run the script reports the detected acquisition style (tomo5 / serialem)
and the lab it implies (gouaux / rosen), then asks you to confirm or override
the lab before writing it into sample.toml's ``lab_name`` field. Pass
``--lab-name`` to set the lab non-interactively and skip the prompt.
"""
from __future__ import annotations

import argparse
import errno
import os
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Configuration — these paths will move over time; change them here.
# Both can also be overridden per-run with --template / --dest.
# ─────────────────────────────────────────────────────────────────────────────
TEMPLATE_DIR = Path(
    "/groups/cryoet/cryoet/data/scratch/templates/sample_id_experimental"
)
DEST_ROOT = Path("/groups/cryoet/cryoet/data/Experimental")

# ─────────────────────────────────────────────────────────────────────────────
# Frame-name patterns. The acquisition_id is the common prefix that precedes
# the per-tilt suffix (_<NNN>_<angle>_...). The prefix is captured greedily but
# the suffix is fully anchored, so e.g. "Position_10_2_001_..." -> "Position_10_2".
# ─────────────────────────────────────────────────────────────────────────────
TOMO5_FRAME_RE = re.compile(
    r"^(?P<prefix>.+)_(?P<index>\d{3})_-?\d+\.\d+_\d{8}_\d{6}_EER\.eer$"
)
SERIALEM_FRAME_RE = re.compile(
    r"^(?P<prefix>.+)_(?P<index>\d{3})_-?\d+\.\d+_[A-Za-z]{3}\d+_\d{2}\.\d{2}\.\d{2}\.eer$"
)

# ─────────────────────────────────────────────────────────────────────────────
# Acquisition style → lab convention. The acquisition style is what we detect
# from the folder; the lab is what the portal records in sample.toml's
# ``lab_name``. Tomo5 is typically Gouaux-lab data and SerialEM typically
# Rosen-lab data, but the user confirms (and may override) the lab per run.
# ─────────────────────────────────────────────────────────────────────────────
LAB_NAMES = ("gouaux", "rosen", "villa")
LAB_BY_STYLE = {"tomo5": "gouaux", "serialem": "rosen"}
# Each lab works on one project; used to fill sample.toml's ``project`` field.
# Labs absent here leave the <FILL IN> placeholder for the researcher.
PROJECT_BY_LAB = {"gouaux": "synapse", "rosen": "chromatin"}


@dataclass
class Acquisition:
    """One tilt-series acquisition, keyed by its common frame prefix."""

    acq_id: str
    frames: list[Path] = field(default_factory=list)  # sorted by tilt index
    frame_mdocs: list[Path] = field(default_factory=list)  # Rosen: per-frame
    series_mdoc: Path | None = None  # Gouaux: existing combined mdoc
    mrc: Path | None = None  # Gouaux: initial tilt series


# ─────────────────────────────────────────────────────────────────────────────
# Acquisition-style detection + acquisition discovery
# ─────────────────────────────────────────────────────────────────────────────
def detect_style(src: Path) -> str:
    """Return the acquisition style ('serialem' or 'tomo5') for ``src``.

    SerialEM data is recognised by per-frame ``*.eer.mdoc`` files; Tomo5 data
    by a series-level ``*.mdoc`` paired with an initial-tilt-series ``*.mrc``.
    """
    names = [p.name for p in src.iterdir() if p.is_file()]
    if any(n.endswith(".eer.mdoc") for n in names):
        return "serialem"
    has_mdoc = any(n.endswith(".mdoc") for n in names)
    has_mrc = any(n.endswith(".mrc") for n in names)
    if has_mdoc and has_mrc:
        return "tomo5"
    raise SystemExit(
        f"Cannot auto-detect acquisition style for {src}: found neither "
        f"SerialEM-style *.eer.mdoc files nor Tomo5-style *.mdoc + *.mrc pairs. "
        f"Use --style to set it explicitly."
    )


def find_gain(src: Path) -> Path:
    gains = sorted(src.glob("*.gain"))
    if not gains:
        raise SystemExit(f"No *.gain file found in {src}")
    if len(gains) > 1:
        raise SystemExit(
            f"Expected exactly one *.gain in {src}, found {len(gains)}: "
            + ", ".join(g.name for g in gains)
        )
    return gains[0]


def discover(src: Path, style: str) -> dict[str, Acquisition]:
    """Group all frames (and their mdocs/mrc) by acquisition prefix."""
    frame_re = SERIALEM_FRAME_RE if style == "serialem" else TOMO5_FRAME_RE
    acqs: dict[str, Acquisition] = defaultdict(lambda: Acquisition(acq_id=""))

    # Frames + their tilt index (for ordering).
    indexed: dict[str, list[tuple[int, Path]]] = defaultdict(list)
    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue
        m = frame_re.match(p.name)
        if not m:
            continue
        prefix = m.group("prefix")
        indexed[prefix].append((int(m.group("index")), p))

    if not indexed:
        raise SystemExit(
            f"No {style}-style frame files matched in {src}. "
            f"Check that --style is correct."
        )

    for prefix, items in indexed.items():
        items.sort(key=lambda t: t[0])
        acq = Acquisition(acq_id=prefix, frames=[p for _, p in items])
        acqs[prefix] = acq

    # Attach mdocs / mrc.
    if style == "serialem":
        for acq in acqs.values():
            for frame in acq.frames:
                mdoc = frame.with_name(frame.name + ".mdoc")
                if mdoc.is_file():
                    acq.frame_mdocs.append(mdoc)
            missing = len(acq.frames) - len(acq.frame_mdocs)
            if missing:
                print(
                    f"  WARNING: {acq.acq_id}: {missing} frame(s) have no "
                    f".eer.mdoc; combined mdoc will be missing those tilts.",
                    file=sys.stderr,
                )
    else:  # tomo5
        for acq in acqs.values():
            mdoc = src / f"{acq.acq_id}.mdoc"
            mrc = src / f"{acq.acq_id}.mrc"
            acq.series_mdoc = mdoc if mdoc.is_file() else None
            acq.mrc = mrc if mrc.is_file() else None
            if acq.series_mdoc is None:
                print(
                    f"  WARNING: {acq.acq_id}: no {acq.acq_id}.mdoc found.",
                    file=sys.stderr,
                )

    return dict(sorted(acqs.items()))


# ─────────────────────────────────────────────────────────────────────────────
# SerialEM mdoc combination: per-frame [FrameSet = 0] -> one [ZValue = N] series mdoc
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# ExposureDose handling for SerialEM combined mdocs.
#
# The SerialEM per-frame mdocs record  ExposureDose = 0  and instead
# carry  DoseRate (e/Å²/s)  and  ExposureTime (s). The portal sums ExposureDose
# across tilts to get total dose, so a literal copy yields total_dose = 0.
#
# We synthesize  ExposureDose = DoseRate * ExposureTime  per tilt.
# This was confirmed by the Rosen Lab to be okay.
# ─────────────────────────────────────────────────────────────────────────────
RECOMPUTE_EXPOSURE_DOSE = True


def _recompute_exposure_dose(body: list[str]) -> list[str]:
    """Return ``body`` with ExposureDose set to DoseRate * ExposureTime.

    Only rewrites when both DoseRate and ExposureTime are present and numeric;
    otherwise the original lines are left untouched.
    """
    if not RECOMPUTE_EXPOSURE_DOSE:
        return body

    def _num(key: str) -> float | None:
        for line in body:
            k, sep, v = line.partition("=")
            if sep and k.strip() == key:
                try:
                    return float(v.strip())
                except ValueError:
                    return None
        return None

    dose_rate = _num("DoseRate")
    exposure_time = _num("ExposureTime")
    if dose_rate is None or exposure_time is None:
        return body

    dose = dose_rate * exposure_time
    dose_str = f"{dose:.4f}".rstrip("0").rstrip(".")

    out: list[str] = []
    replaced = False
    for line in body:
        k, sep, _ = line.partition("=")
        if sep and k.strip() == "ExposureDose":
            out.append(f"ExposureDose = {dose_str}")
            replaced = True
        else:
            out.append(line)
    if not replaced:  # no ExposureDose line in source — add one
        out.append(f"ExposureDose = {dose_str}")
    return out


def _split_frame_mdoc(text: str) -> tuple[list[str], list[str]]:
    """Split a per-frame mdoc into (global header lines, frameset body lines).

    Everything before the first ``[...]`` section is global; everything after
    the ``[FrameSet ...]`` marker (up to the next section / EOF) is the body.
    """
    globals_lines: list[str] = []
    body_lines: list[str] = []
    in_body = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("[") and line.endswith("]"):
            in_body = line[1:-1].strip().lower().startswith("frameset")
            continue
        if in_body:
            body_lines.append(line)
        else:
            globals_lines.append(line)
    return globals_lines, body_lines


def build_combined_mdoc(acq: Acquisition) -> str:
    """Build a series-level mdoc string from SerialEM per-frame mdocs (in order)."""
    title = None
    voltage = None
    pixel_spacing = None
    bodies: list[list[str]] = []

    for mdoc in acq.frame_mdocs:
        glob_lines, body = _split_frame_mdoc(mdoc.read_text())
        for line in glob_lines:
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key == "T" and title is None:
                title = val
            elif key == "Voltage" and voltage is None:
                voltage = val
        if pixel_spacing is None:
            for line in body:
                if line.startswith("PixelSpacing"):
                    pixel_spacing = line.partition("=")[2].strip()
                    break
        # Drop trailing blank lines from each body for tidy output.
        while body and not body[-1].strip():
            body.pop()
        # Synthesize per-tilt ExposureDose (see CHECK THIS note above).
        body = _recompute_exposure_dose(body)
        bodies.append(body)

    out: list[str] = []
    if pixel_spacing is not None:
        out.append(f"PixelSpacing = {pixel_spacing}")
    if voltage is not None:
        out.append(f"Voltage = {voltage}")
    out.append(f"ImageFile = {acq.acq_id}.mrc")
    out.append("")
    if title is not None:
        out.append(f"[T = {title}]")
        out.append("")
    for z, body in enumerate(bodies):
        out.append(f"[ZValue = {z}]")
        out.extend(body)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# Lab confirmation + sample.toml rendering
# ─────────────────────────────────────────────────────────────────────────────
LAB_NAME_RE = re.compile(r'^(?P<pre>\s*lab_name\s*=\s*)"[^"]*"')
PROJECT_RE = re.compile(r'^(?P<pre>\s*project\s*=\s*)"[^"]*"')


def confirm_lab(style: str, explicit: str | None) -> str:
    """Resolve the sample's ``lab_name``, confirming the detected default.

    The acquisition style implies a lab (Tomo5 → gouaux, SerialEM → rosen). We
    show that default and let the user accept it (Enter) or type a different
    lab. ``--lab-name`` supplies the value non-interactively and skips the
    prompt. Values outside the known enum are allowed but warned about.
    """
    default = LAB_BY_STYLE.get(style)

    if explicit is not None:
        lab = explicit.strip()
    elif not sys.stdin.isatty():
        # Non-interactive (piped) and no --lab-name: fall back to the default.
        if default is None:
            raise SystemExit(
                f"Cannot infer lab for style {style!r} and no --lab-name given "
                f"on a non-interactive run. Re-run with --lab-name."
            )
        print(
            f"  (non-interactive) using lab '{default}' inferred from "
            f"{style} acquisition style."
        )
        lab = default
    else:
        prompt = (
            f"Detected {style} acquisition style → lab '{default}'.\n"
            f"  Press Enter to accept, or type a lab name "
            f"({' | '.join(LAB_NAMES)}): "
            if default
            else (
                f"Detected {style} acquisition style (no default lab).\n"
                f"  Type a lab name ({' | '.join(LAB_NAMES)}): "
            )
        )
        try:
            reply = input(prompt).strip()
        except EOFError:
            reply = ""
        lab = reply or (default or "")
        while not lab:
            try:
                lab = input("  A lab_name is required. Type a lab name: ").strip()
            except EOFError:
                raise SystemExit("No lab_name provided; aborting.")

    if lab not in LAB_NAMES:
        print(
            f"  WARNING: lab_name '{lab}' is not one of the known labs "
            f"({', '.join(LAB_NAMES)}); writing it anyway.",
            file=sys.stderr,
        )
    return lab


# A "# ── …" section divider in sample.toml; ``_strip_section`` uses these to
# delimit the project-specific block it removes.
_SECTION_DIVIDER_RE = re.compile(r"^#\s*─")


def _strip_section(lines: list[str], keyword: str) -> list[str]:
    """Drop the divider-delimited section whose header mentions ``keyword``.

    The section runs from its ``# ── <keyword>…`` divider up to (but not
    including) the next ``# ── …`` divider — taking the live table (e.g.
    ``[chromatin]``) and its commented fields with it.
    """
    out: list[str] = []
    skipping = False
    for line in lines:
        is_divider = bool(_SECTION_DIVIDER_RE.match(line))
        if is_divider and keyword.lower() in line.lower():
            skipping = True
            continue
        if skipping:
            if is_divider:  # next section begins — stop skipping, keep this line
                skipping = False
            else:
                continue
        out.append(line)
    return out


def render_sample_toml(
    template_text: str, lab_name: str, project: str | None
) -> str:
    """Return ``template_text`` with ``lab_name`` (and ``project``) filled in.

    Only the values are replaced; the trailing enum comments are preserved.
    ``project`` is derived from the lab (see ``PROJECT_BY_LAB``); when it is
    None (an unmapped lab) the ``<FILL IN>`` placeholder is left untouched.

    The template ships a live ``[chromatin]`` block; the validator rejects it
    for non-chromatin projects, so it is stripped unless ``project`` is
    ``"chromatin"``.
    """
    lab_done = False
    project_done = False
    out: list[str] = []
    for line in template_text.splitlines():
        if not lab_done and LAB_NAME_RE.match(line):
            out.append(LAB_NAME_RE.sub(rf'\g<pre>"{lab_name}"', line))
            lab_done = True
        elif project is not None and not project_done and PROJECT_RE.match(line):
            out.append(PROJECT_RE.sub(rf'\g<pre>"{project}"', line))
            project_done = True
        else:
            out.append(line)
    if project is not None and project != "chromatin":
        out = _strip_section(out, "chromatin")
    if not lab_done:
        print(
            "  WARNING: no lab_name field found in sample.toml template; "
            "left as-is.",
            file=sys.stderr,
        )
    if project is not None and not project_done:
        print(
            "  WARNING: no project field found in sample.toml template; "
            "left as-is.",
            file=sys.stderr,
        )
    return "\n".join(out) + ("\n" if template_text.endswith("\n") else "")


# ─────────────────────────────────────────────────────────────────────────────
# acquisition.toml authoring — fill in the [[tilt_series]] block for the raw
# (unaligned) series this script lays down under TiltSeries/{ts_id}/.
# ─────────────────────────────────────────────────────────────────────────────
# Name of the template's placeholder tilt-series folder
# (templates/.../TiltSeries/tilt_series_id/). We rename it to the real id.
TILT_SERIES_PLACEHOLDER_DIR = "tilt_series_id"

# Other "<x>_id" placeholder leaf dirs the template ships under Reconstructions/.
# Nothing populates them at reorg time (researchers add reconstructions later),
# so we drop them rather than leave empty template placeholders behind. The
# acquisition_id and tilt_series_id placeholders are handled elsewhere (consumed
# by copytree / renamed by rename_dir).
PLACEHOLDER_DIRS = (
    "Reconstructions/Annotations/annotation_id",
    "Reconstructions/Tomograms/tomogram_id",
)

# Matches the template's commented "# [[tilt_series]]" header and its commented
# "# key = ..." field lines, so we can swap the whole block for a live one.
_TS_HEADER_RE = re.compile(r"^#\s*\[\[tilt_series\]\]\s*$")
_TS_FIELD_RE = re.compile(r"^#\s*\w+\s*=")


def render_acquisition_toml(template_text: str, tilt_series_id: str) -> str:
    """Return ``template_text`` with a live ``[[tilt_series]]`` block filled in.

    The template ships the block commented out with ``<FILL IN>`` placeholders.
    We replace that commented block with an authored one for the initial tilt
    series (``derived_from = "Frames"``, ``is_aligned = false``). The alignment
    fields stay commented — the series is raw/unaligned, so the researcher fills
    them in only when they add an aligned series. If no commented template block
    is found, the authored block is appended instead.
    """
    authored = [
        "[[tilt_series]]",
        f'id                  = "{tilt_series_id}"   # text, tilt series id == folder name under TiltSeries/',
        'derived_from        = "Frames"   # text, raw series reconstructed straight from the frames',
        "is_aligned          = false   # boolean, the initial tilt series is not yet aligned",
        '# alignment_software  = "<FILL IN>"   # text, e.g. "IMOD 4.12", "AreTomo3" (fill in for an aligned series)',
        "# alignment_method    = \"<FILL IN>\"   # text, e.g. fiducial | patch_tracking | feature_tracking (fill in for an aligned series)",
    ]

    lines = template_text.splitlines()
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        if not replaced and _TS_HEADER_RE.match(lines[i]):
            out.extend(authored)
            i += 1
            # Drop the commented "# key = ..." field lines that follow.
            while i < len(lines) and _TS_FIELD_RE.match(lines[i]):
                i += 1
            replaced = True
            continue
        out.append(lines[i])
        i += 1

    if not replaced:
        print(
            "  WARNING: no commented [[tilt_series]] block found in "
            "acquisition.toml template; appending an authored block.",
            file=sys.stderr,
        )
        out.extend(["", *authored])

    return "\n".join(out) + ("\n" if template_text.endswith("\n") else "")


# ─────────────────────────────────────────────────────────────────────────────
# Execution
# ─────────────────────────────────────────────────────────────────────────────
# Placement modes for the bulk data (frames, mdocs, mrc, gain). The default is
# the cheapest, safest-to-discard option — symlink — so a test run stages the
# full layout instantly without duplicating hundreds of GB. copy/move/hardlink
# must be opted into explicitly (see argparse). Note: symlink/hardlink require
# source and dest on the same filesystem to be useful; over NFS within one
# export both work, but reflink is unsupported.
PLACEMENT_MODES = ("symlink", "copy", "move", "hardlink")


class Runner:
    """Performs (or, in dry-run mode, prints) filesystem actions."""

    def __init__(self, dry_run: bool, mode: str):
        self.dry_run = dry_run
        self.mode = mode  # one of PLACEMENT_MODES

    def _say(self, msg: str) -> None:
        print(("[dry-run] " if self.dry_run else "") + msg)

    def make_skeleton(self, template_acq: Path, dest_acq: Path) -> None:
        self._say(f"skeleton  {template_acq}  ->  {dest_acq}/")
        if not self.dry_run:
            shutil.copytree(template_acq, dest_acq, dirs_exist_ok=True)

    def copy_file(self, src: Path, dest: Path) -> None:
        self._say(f"copy      {src}  ->  {dest}")
        if not self.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    def rename_dir(self, src: Path, dest: Path) -> None:
        """Rename the template's placeholder tilt-series dir to the real id.

        Idempotent across re-runs: if ``dest`` already exists (a prior run, or
        the .mrc was already placed there), the leftover placeholder is dropped
        instead of nesting it inside ``dest``.
        """
        if src == dest or not (src.is_dir() or src.is_symlink()):
            return
        self._say(f"rename    {src}  ->  {dest}")
        if self.dry_run:
            return
        if dest.exists():
            shutil.rmtree(src)
        else:
            shutil.move(str(src), str(dest))

    def remove_dir(self, target: Path) -> None:
        """Drop a leftover template placeholder dir, if present."""
        if not (target.is_dir() or target.is_symlink()):
            return
        self._say(f"remove    {target}")
        if not self.dry_run:
            shutil.rmtree(target)

    def _place(self, src: Path, dest: Path, mode: str) -> None:
        """Place ``src`` at ``dest`` using ``mode`` (one of PLACEMENT_MODES)."""
        self._say(f"{mode:8}{src}  ->  {dest}")
        if self.dry_run:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        if mode == "copy":
            shutil.copy2(src, dest)
        elif mode == "move":
            shutil.move(str(src), str(dest))
        elif mode in ("symlink", "hardlink"):
            # Idempotent on re-runs: clear any existing link/file first.
            if dest.is_symlink() or dest.exists():
                dest.unlink()
            try:
                if mode == "symlink":
                    dest.symlink_to(src)  # src is absolute, so the link is stable
                else:
                    os.link(src, dest)
            except OSError as exc:
                if mode == "hardlink" and getattr(exc, "errno", None) == errno.EXDEV:
                    raise SystemExit(
                        f"Cannot hardlink across filesystems: {src} -> {dest}. "
                        f"Use --copy (independent bytes) or --symlink instead."
                    )
                raise
        else:  # pragma: no cover - guarded by argparse choices
            raise ValueError(f"Unknown placement mode: {mode!r}")

    def place_frame(self, src: Path, dest: Path) -> None:
        """Place a bulk data file (frame / mdoc / mrc) using the run's mode."""
        self._place(src, dest, self.mode)

    def place_gain(self, src: Path, dest: Path) -> None:
        """Place the shared gain reference into an acquisition's Gains/.

        The gain is shared by every acquisition, so it can't be *moved* into
        each one — in move mode we copy it. In link modes we link it (instant,
        no duplication); in copy mode we copy.
        """
        self._place(src, dest, "copy" if self.mode == "move" else self.mode)

    def write_text(self, dest: Path, text: str, label: str) -> None:
        self._say(f"write     {label}  ->  {dest}  ({len(text.splitlines())} lines)")
        if not self.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)


def process(
    src: Path,
    sample_id: str,
    style: str,
    lab_name: str,
    template_dir: Path,
    dest_root: Path,
    runner: Runner,
    tilt_series_id: str = "raw",
    force: bool = False,
) -> None:
    template_acq = template_dir / "acquisition_id"
    template_sample_toml = template_dir / "sample.toml"
    template_acq_toml = template_acq / "acquisition.toml"
    if not template_acq.is_dir():
        raise SystemExit(f"Template acquisition dir not found: {template_acq}")
    acq_toml_text = (
        template_acq_toml.read_text() if template_acq_toml.is_file() else None
    )

    gain = find_gain(src)
    acqs = discover(src, style)

    sample_dir = dest_root / sample_id
    # Guard against silently merging into an existing sample. Populating a
    # sample_id that already exists (a prior run, or a name collision between
    # two source folders) is possible but must be explicit — it merges new
    # acquisitions in and overwrites sample.toml. Require --force to allow it.
    if sample_dir.exists() and not force:
        raise SystemExit(
            f"Refusing to write into existing sample directory:\n"
            f"    {sample_dir}\n"
            f"sample_id {sample_id!r} is already populated (a prior run, or a "
            f"name clash with another source folder).\n"
            f"Merging new acquisitions into it is possible but must be explicit: "
            f"re-run with --force to allow the merge, or pass a different "
            f"--sample-id."
        )
    print(
        f"\nStyle      : {style}\n"
        f"Lab        : {lab_name}\n"
        f"Source     : {src}\n"
        f"Sample id  : {sample_id}\n"
        f"Destination: {sample_dir}\n"
        f"Gain       : {gain.name}\n"
        f"Mode       : {runner.mode.upper()} frames"
        f"{'  (DRY RUN)' if runner.dry_run else ''}\n"
        f"Acquisitions ({len(acqs)}): {', '.join(acqs)}\n"
    )

    # Sample-level template files. sample.toml is rendered (not copied) so the
    # confirmed lab_name is written in.
    if template_sample_toml.is_file():
        project = PROJECT_BY_LAB.get(lab_name)
        text = render_sample_toml(template_sample_toml.read_text(), lab_name, project)
        label = f"sample.toml (lab_name = {lab_name}"
        label += f", project = {project})" if project else ")"
        runner.write_text(sample_dir / "sample.toml", text, label)

    for acq in acqs.values():
        print(f"\n── {acq.acq_id}  ({len(acq.frames)} frames) ──")
        dest_acq = sample_dir / acq.acq_id
        runner.make_skeleton(template_acq, dest_acq)

        # Tomo5 ships an initial .mrc raw tilt series: rename the placeholder
        # tilt-series folder to the real id and author the matching
        # [[tilt_series]] block. SerialEM has no raw series, so we leave both the
        # placeholder folder and the commented [[tilt_series]] block (copied
        # verbatim by make_skeleton) for the researcher to fill in later.
        ts_root = dest_acq / "TiltSeries"
        if style != "serialem":
            runner.rename_dir(
                ts_root / TILT_SERIES_PLACEHOLDER_DIR, ts_root / tilt_series_id
            )
            if acq_toml_text is not None:
                runner.write_text(
                    dest_acq / "acquisition.toml",
                    render_acquisition_toml(acq_toml_text, tilt_series_id),
                    f"acquisition.toml ([[tilt_series]] id = {tilt_series_id})",
                )
        # Drop the Reconstructions/ placeholder "<x>_id" dirs the template ships.
        for rel in PLACEHOLDER_DIRS:
            runner.remove_dir(dest_acq / rel)

        frames_dir = dest_acq / "Frames"
        # Frames.
        for frame in acq.frames:
            runner.place_frame(frame, frames_dir / frame.name)

        # Series mdoc.
        if style == "serialem":
            if acq.frame_mdocs:
                text = build_combined_mdoc(acq)
                runner.write_text(
                    frames_dir / f"{acq.acq_id}.mdoc",
                    text,
                    f"combined mdoc from {len(acq.frame_mdocs)} per-frame mdocs",
                )
        else:  # tomo5: existing series mdoc + initial tilt-series mrc
            if acq.series_mdoc is not None:
                runner.place_frame(acq.series_mdoc, frames_dir / acq.series_mdoc.name)
            if acq.mrc is not None:
                # The initial tilt series goes under TiltSeries/{ts_id}/stack/.
                # ts_id is the tilt-series folder name (default "raw" — the
                # unaligned series derived from Frames).
                runner.place_frame(
                    acq.mrc,
                    dest_acq / "TiltSeries" / tilt_series_id / "stack" / acq.mrc.name,
                )

        # Gain reference — placed into every acquisition's Gains/ (copied in
        # copy/move mode, linked in symlink/hardlink mode).
        runner.place_gain(gain, dest_acq / "Gains" / gain.name)


def apply_lab_prefix(sample_id: str, lab_name: str) -> str:
    """Return ``sample_id`` namespaced by lab as ``<lab>lab_<id>``.

    Portal sample ids are conventionally prefixed with the lab (e.g. a rosen
    sample becomes ``rosenlab_<id>``). This is applied to both the default
    (folder-derived) id and an explicit --sample-id, and is a no-op when the id
    already starts with the prefix (so it is never doubled).
    """
    prefix = f"{lab_name}lab_"
    return sample_id if sample_id.startswith(prefix) else prefix + sample_id


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Reorganize Janelia cryoET facility output for portal ingestion.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("source", type=Path, help="Source microscope-output folder.")
    ap.add_argument(
        "--sample-id",
        help="sample_id_experimental for the output. "
        "Defaults to the source folder name. Pass --lab-prefix to namespace "
        "it with the '<lab>lab_' convention prefix.",
    )
    ap.add_argument(
        "--lab-prefix",
        action="store_true",
        help="Prepend the '<lab>lab_' convention prefix to the sample_id "
        "(e.g. 'rosenlab_<id>'). Off by default; a no-op when the id already "
        "starts with the prefix.",
    )
    ap.add_argument(
        "--style",
        choices=("auto", "tomo5", "serialem"),
        default="auto",
        help="Acquisition style of the source data (default: auto-detect). "
        "Tomo5 is typically Gouaux-lab data; SerialEM typically Rosen-lab.",
    )
    ap.add_argument(
        "--lab-name",
        choices=LAB_NAMES,
        help="Lab to record in sample.toml's lab_name. If omitted, the lab "
        "implied by the acquisition style is offered for interactive "
        "confirmation.",
    )
    ap.add_argument(
        "--tilt-series-id",
        default="raw",
        help="Folder name for the initial tilt series under TiltSeries/ "
        "(Tomo5 .mrc). Default 'raw' — the unaligned series derived from "
        "Frames. This is also the `id` to record in the [[tilt_series]] block.",
    )
    ap.add_argument(
        "--dest",
        type=Path,
        default=DEST_ROOT,
        help=f"Destination root for new sample folders (default: {DEST_ROOT}).",
    )
    ap.add_argument(
        "--template",
        type=Path,
        default=TEMPLATE_DIR,
        help=f"Experimental sample-dir template (default: {TEMPLATE_DIR}).",
    )
    mode_group = ap.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--symlink",
        dest="mode",
        action="store_const",
        const="symlink",
        help="Symlink frames/mdocs/mrc/gain into the layout (DEFAULT). Instant "
        "and uses no extra space; ideal for test runs you'll discard. Links "
        "break if the source moves.",
    )
    mode_group.add_argument(
        "--copy",
        dest="mode",
        action="store_const",
        const="copy",
        help="Copy frames/mdocs/mrc/gain (independent bytes). EXPENSIVE — "
        "duplicates the full dataset (hundreds of GB). Use for the real run "
        "when you want the source left untouched.",
    )
    mode_group.add_argument(
        "--move",
        dest="mode",
        action="store_const",
        const="move",
        help="Move frames/mdocs/mrc out of the source (consumes it). Instant "
        "within one filesystem. The shared gain reference is copied.",
    )
    mode_group.add_argument(
        "--hardlink",
        dest="mode",
        action="store_const",
        const="hardlink",
        help="Hardlink frames/mdocs/mrc/gain (same filesystem only). Instant, "
        "no extra space, survives source deletion; but shares the source "
        "inode, so in-place edits affect both names.",
    )
    ap.set_defaults(mode="symlink")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without touching the filesystem.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Allow writing into an existing {dest}/{sample_id} directory, "
        "merging new acquisitions into it (and overwriting sample.toml). "
        "Without this the script refuses to touch a sample_id that already "
        "exists, to prevent accidental merges.",
    )
    args = ap.parse_args(argv)

    src = args.source.resolve()
    if not src.is_dir():
        raise SystemExit(f"Source is not a directory: {src}")

    style = detect_style(src) if args.style == "auto" else args.style
    if args.style == "auto":
        print(f"Auto-detected acquisition style: {style}")
    sample_id = args.sample_id or src.name
    lab_name = confirm_lab(style, args.lab_name)
    if args.lab_prefix:
        sample_id = apply_lab_prefix(sample_id, lab_name)

    runner = Runner(dry_run=args.dry_run, mode=args.mode)
    process(
        src=src,
        sample_id=sample_id,
        style=style,
        lab_name=lab_name,
        template_dir=args.template,
        dest_root=args.dest,
        runner=runner,
        tilt_series_id=args.tilt_series_id,
        force=args.force,
    )

    print(
        "\nDry run complete — no files were changed. Re-run without --dry-run to apply."
        if args.dry_run
        else "\nDone."
    )


if __name__ == "__main__":
    main()
