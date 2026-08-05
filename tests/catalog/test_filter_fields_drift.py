"""Drift test for the filter field registry (Phase 0).

(a) Every Python registry field with a real column (kind != 'existence')
    must name a real ``table.column`` on the corresponding ORM model.
(b) The hand-mirrored TS registry (frontend/src/utils/filterFields.ts) must
    have the same set of keys and matching kind/table/column per key.

Mirrors the style of test_orm_drift.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# SQLAlchemy is part of the `catalog` feature; skip in the bare `test` env.
pytest.importorskip("sqlalchemy")

from catalog import orm  # noqa: E402
from catalog.api.filter_fields import FIELDS, PROJECT_REQUIRES_DATA_SOURCE  # noqa: E402

# table __tablename__ -> ORM column-name set, taken straight from the registered
# tables so this can't drift from orm.py.
_TABLE_COLUMNS = {
    t.name: {c.name for c in t.columns} for t in orm.Base.metadata.tables.values()
}

TS_PATH = Path(__file__).parents[2] / "frontend" / "src" / "utils" / "filterFields.ts"


def test_python_registry_columns_exist_on_orm():
    for f in FIELDS:
        if f.kind == "existence":
            continue  # column is a predicate id, not a real column
        assert f.table in _TABLE_COLUMNS, f"{f.key}: unknown table {f.table!r}"
        assert f.column in _TABLE_COLUMNS[f.table], (
            f"{f.key}: {f.table}.{f.column} not a real ORM column"
        )


def _parse_ts_fields() -> dict[str, dict[str, str]]:
    """Parse field objects out of filterFields.ts.

    Assumes (and the TS file is written so) each field is a single-line object
    literal containing key/kind/table/column as ``name: 'value'`` pairs.
    """
    text = TS_PATH.read_text()
    out: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{ key:"):
            continue

        def grab(name: str) -> str:
            m = re.search(rf"\b{name}:\s*'([^']*)'", line)
            assert m, f"missing {name} in TS field line: {line}"
            return m.group(1)

        key = grab("key")
        out[key] = {
            "kind": grab("kind"),
            "table": grab("table"),
            "column": grab("column"),
        }
    return out


def test_ts_python_parity():
    ts = _parse_ts_fields()
    py = {f.key: {"kind": f.kind, "table": f.table, "column": f.column} for f in FIELDS}

    assert set(ts) == set(py), (
        f"key set differs: only-TS={set(ts) - set(py)}, only-PY={set(py) - set(ts)}"
    )
    for key, py_entry in py.items():
        assert ts[key] == py_entry, f"{key}: TS {ts[key]} != PY {py_entry}"


def test_project_requires_data_source_parity():
    """The synapse ⇒ experimental gating constant stays mirrored."""
    text = TS_PATH.read_text()
    block = re.search(
        r"PROJECT_REQUIRES_DATA_SOURCE\b.*?=\s*\{(.*?)\}", text, re.DOTALL
    )
    assert block, "PROJECT_REQUIRES_DATA_SOURCE not found in filterFields.ts"
    ts = dict(re.findall(r"(\w+):\s*'(experimental|simulation)'", block.group(1)))
    assert ts == PROJECT_REQUIRES_DATA_SOURCE, (
        f"PROJECT_REQUIRES_DATA_SOURCE drift: TS {ts} != PY {PROJECT_REQUIRES_DATA_SOURCE}"
    )
