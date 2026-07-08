"""End-to-end tests for ``catalog.db.init_schema``.

``init_schema`` runs ``alembic upgrade head`` (see
``catalog/migrations/README.md``). These tests pin that contract.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")

from pathlib import Path  # noqa: E402

from sqlalchemy import inspect  # noqa: E402

from catalog import db  # noqa: E402
from catalog.orm import Base  # noqa: E402


def _engine_at(tmp_path: Path, name: str = "cat.db"):
    return db.make_engine(f"sqlite:///{tmp_path / name}")


def test_init_schema_creates_all_orm_tables(tmp_path):
    engine = _engine_at(tmp_path)
    db.init_schema(engine)

    tables = set(inspect(engine).get_table_names())
    # Every ORM-declared table must be present.
    expected = set(Base.metadata.tables.keys())
    assert expected <= tables, f"missing tables: {expected - tables}"

    # Alembic's version table is written and pinned at head.
    assert "alembic_version" in tables


def test_init_schema_is_idempotent(tmp_path):
    engine = _engine_at(tmp_path)
    db.init_schema(engine)

    pre_tables = set(inspect(engine).get_table_names())

    # Re-run init_schema; create_all is a no-op when every table already exists.
    db.init_schema(engine)

    assert set(inspect(engine).get_table_names()) == pre_tables
