"""MDOC parser.

MDOC files are plain text emitted by SerialEM for tilt-series acquisition.
They contain global ``Key = Value`` pairs at the top, followed by per-tilt
sections marked ``[ZValue = N]``.

For v1, when ``frames_dir`` contains multiple ``.mdoc`` files, we parse the
first one (sorted alphabetically) to extract acquisition-level fields.
Per-tilt fields (TiltAngle, ExposureDose, Defocus) are aggregated across
all ZValue sections in that single file.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from catalog.parsers import ParseResult


# Keys we coerce to float; all other values are kept as raw strings.
_NUMERIC_KEYS = {
    "PixelSpacing",
    "Voltage",
    "FilterSlitWidth",
    "TiltAxisAngle",
    "TiltAngle",
    "ExposureDose",
    "Defocus",
}


def _parse_kv(line: str) -> tuple[str, str] | None:
    """Split ``Key = Value`` into ``(key, value)``; return None on no-match."""
    if "=" not in line:
        return None
    key, _, value = line.partition("=")
    return key.strip(), value.strip()


def _coerce_numeric(key: str, value: str) -> Any:
    """Return ``float(value)`` for numeric keys, raw string otherwise.

    Raises ``ValueError`` if a numeric coercion fails — caller wraps that.
    """
    if key in _NUMERIC_KEYS:
        return float(value)
    return value


def _parse_datetime(value: str) -> _dt.date | None:
    """Parse a SerialEM ``DateTime`` string; return its ``.date()`` or None.

    SerialEM emits e.g. ``"24-Aug-25  10:00:00"`` with TWO spaces between
    date and time, but some installations write a single space, and newer
    installs (2026+) write a 4-digit year (``"27-Jan-2026  19:14:10"``). All
    four combinations are accepted; on failure of all we return None
    (DateTime format varies in the wild, so a parse failure here does NOT
    mark the mdoc unreadable).
    """
    for fmt in (
        "%d-%b-%y  %H:%M:%S",
        "%d-%b-%y %H:%M:%S",
        "%d-%b-%Y  %H:%M:%S",
        "%d-%b-%Y %H:%M:%S",
    ):
        try:
            return _dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def is_series_level_mdoc(mdoc_path: Path) -> bool:
    """Return True if the MDOC contains at least one ``[ZValue`` section.

    Cheap check used by the tilt-series layout classifier — reads the first
    2 KB only, since the first ``[ZValue`` always falls inside the early
    header region of a series-level MDOC. Per-tilt (gouauxlab-style) MDOCs
    have no ``[ZValue`` sections; their tilt angle lives in the filename.

    Missing / unreadable files return False; the classifier interprets that
    as "not series-level" and the surrounding parser still records the
    underlying parse failure separately.
    """
    try:
        with mdoc_path.open("rb") as f:
            head = f.read(2048)
    except OSError:
        return False
    return b"[ZValue" in head


def parse_mdoc_file(mdoc_path: Path) -> ParseResult:
    """Parse a single ``.mdoc`` file and return acquisition / tilt-series fields.

    Field shape matches :func:`parse_acquisition_mdocs`; the only difference
    is the entry point (single file vs. ``frames_dir`` scan). The
    multi-MDOC tilt-series parser dispatches here per file.

    ``status="missing"`` if ``mdoc_path`` doesn't exist. ``status="unreadable"``
    with ``error`` set on I/O failure or numeric coercion failure.
    """
    if not mdoc_path.is_file():
        return ParseResult(status="missing")

    try:
        text = mdoc_path.read_text()
    except OSError as e:
        return ParseResult(status="unreadable", error=f"mdoc read error: {e}")

    globals_kv: dict[str, Any] = {}
    tilts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None  # None == still in globals

    try:
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                inner = line[1:-1].strip()
                if inner.lower().startswith("zvalue"):
                    current = {}
                    tilts.append(current)
                else:
                    # Some other bracketed section — treat as switching out
                    # of globals but don't accumulate into a tilt.
                    current = {}
                continue
            kv = _parse_kv(line)
            if kv is None:
                continue
            key, value = kv
            coerced = _coerce_numeric(key, value)
            target = globals_kv if current is None else current
            target[key] = coerced
    except ValueError as e:
        return ParseResult(
            status="unreadable",
            error=f"mdoc malformed numeric value: {e}",
        )

    # Aggregate per-tilt fields. Only [ZValue=...] sections accumulated into
    # ``tilts``; the dummy "other bracketed section" branch produces an
    # empty dict so we filter empties before the count.
    zvalue_tilts = [t for t in tilts if t]
    frame_count = len(zvalue_tilts)

    dose_per_tilt = [
        t["ExposureDose"] for t in zvalue_tilts if "ExposureDose" in t
    ]
    total_dose = float(sum(dose_per_tilt))

    tilt_angles = [t["TiltAngle"] for t in zvalue_tilts if "TiltAngle" in t]
    tilt_min = min(tilt_angles) if tilt_angles else None
    tilt_max = max(tilt_angles) if tilt_angles else None

    defocus_per_image = [
        t["Defocus"] for t in zvalue_tilts if "Defocus" in t
    ]

    date_collected = None
    if zvalue_tilts:
        first_dt = zvalue_tilts[0].get("DateTime")
        if isinstance(first_dt, str):
            date_collected = _parse_datetime(first_dt)

    fields = {
        "pixel_size": globals_kv.get("PixelSpacing"),
        "voltage": globals_kv.get("Voltage"),
        "energy_filter_slit_width": globals_kv.get("FilterSlitWidth"),
        "date_collected": date_collected,
        "frame_count": frame_count,
        "dose_per_tilt": dose_per_tilt,
        "total_dose": total_dose,
        "tilt_min": tilt_min,
        "tilt_max": tilt_max,
        "tilt_axis": globals_kv.get("TiltAxisAngle"),
        "defocus_per_image": defocus_per_image,
        "tilt_angles": tilt_angles,
    }
    return ParseResult(fields=fields, status="ok")


def parse_acquisition_mdocs(frames_dir: Path) -> ParseResult:
    """Parse the first ``.mdoc`` in ``frames_dir`` and return acquisition fields.

    Fields returned (all may be ``None`` / empty if unset):

    - ``pixel_size``: float | None  (from ``PixelSpacing``, in Angstroms)
    - ``voltage``: float | None
    - ``energy_filter_slit_width``: float | None  (from ``FilterSlitWidth``)
    - ``date_collected``: ``datetime.date`` | None  (from first ZValue's DateTime)
    - ``frame_count``: int  (number of ``[ZValue=N]`` sections)
    - ``dose_per_tilt``: list[float]  (per-tilt ``ExposureDose``)
    - ``total_dose``: float  (sum of ``dose_per_tilt``)
    - ``tilt_min``: float | None  (min TiltAngle)
    - ``tilt_max``: float | None  (max TiltAngle)
    - ``tilt_axis``: float | None  (from global ``TiltAxisAngle``)
    - ``defocus_per_image``: list[float]  (from per-tilt ``Defocus``)
    - ``tilt_angles``: list[float]  (per-tilt ``TiltAngle`` — full ordered
      list; consumed by the tilt-series parser and the polar-plot endpoint
      so the MDOC never has to be re-parsed)

    ``status="missing"`` if ``frames_dir`` doesn't exist or contains no
    ``.mdoc`` file. ``status="unreadable"`` with ``error`` set if a mdoc
    exists but a numeric coercion fails (malformed value).
    """
    if not frames_dir.is_dir():
        return ParseResult(status="missing")

    mdocs = sorted(frames_dir.glob("*.mdoc"))
    if not mdocs:
        return ParseResult(status="missing")

    return parse_mdoc_file(mdocs[0])
