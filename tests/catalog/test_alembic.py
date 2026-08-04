"""Alembic-specific tests covering autogen drift and the prod rollout paths.

These tests live in the ``catalog`` env (alembic is part of
``feature.catalog.dependencies``); the bare ``test`` env can't import
alembic, so the whole module is skipped there.
"""

from __future__ import annotations

import pytest

pytest.importorskip("alembic")
pytest.importorskip("sqlalchemy")

from pathlib import Path  # noqa: E402

from alembic import command  # noqa: E402
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from catalog import db, orm  # noqa: E402
from catalog.orm import Base  # noqa: E402


def _engine_at(tmp_path: Path, name: str = "cat.db"):
    return db.make_engine(f"sqlite:///{tmp_path / name}")


def test_autogenerate_empty_at_head(tmp_path):
    """Running autogenerate against a head-state DB must produce no ops.

    Catches forgotten revisions when the ORM is changed without a matching
    Alembic revision.
    """
    engine = _engine_at(tmp_path)
    command.upgrade(db._alembic_cfg(engine), "head")

    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={"compare_type": True, "render_as_batch": True},
        )
        diff = compare_metadata(ctx, Base.metadata)

    assert diff == [], (
        f"ORM has drifted from head revision; pending autogenerate diff: {diff!r}"
    )


@pytest.mark.parametrize(
    "orm_class",
    [orm.RawTomogramORM, orm.PostProcessedTomogramORM, orm.AnnotationORM],
    ids=lambda c: c.__tablename__,
)
def test_upgrade_head_pk_column_order(tmp_path, orm_class):
    """The migrated PK's column ORDER must match the ORM mapper's.

    ``compare_metadata`` (test_autogenerate_empty_at_head) ignores
    ``PrimaryKeyConstraint`` entirely, and every other test builds the schema
    with ``create_all``, so nothing else exercises what the migration actually
    emitted. Order matters here beyond cosmetics: the prune keep-set tuples and
    ``GuardedChild.pk_cols`` are built in PK order, so a transposed
    ``reconstruction_alignment_id``/``<leaf>_id`` silently prunes live rows.

    Expected order comes from the mapper (``inspect(cls).primary_key`` yields
    the columns in constraint order) so the test tracks orm.py instead of
    pinning a hardcoded list that would need editing alongside a real change.
    """
    expected = [c.name for c in inspect(orm_class).primary_key]

    engine = _engine_at(tmp_path)
    command.upgrade(db._alembic_cfg(engine), "head")
    actual = inspect(engine).get_pk_constraint(orm_class.__tablename__)[
        "constrained_columns"
    ]

    assert actual == expected, (
        f"{orm_class.__tablename__}: migrated PK order {actual!r} != "
        f"ORM mapper PK order {expected!r}"
    )


def test_create_all_matches_upgrade_head(tmp_path):
    """``Base.metadata.create_all`` must produce the same table set as
    ``alembic upgrade head`` from empty.

    If this fails, someone added/removed an ORM table without a matching
    revision (or vice versa).
    """
    engine_create = _engine_at(tmp_path, "create.db")
    Base.metadata.create_all(engine_create)
    create_tables = set(inspect(engine_create).get_table_names())

    engine_upgrade = _engine_at(tmp_path, "upgrade.db")
    command.upgrade(db._alembic_cfg(engine_upgrade), "head")
    upgrade_tables = set(inspect(engine_upgrade).get_table_names()) - {
        "alembic_version"
    }

    assert create_tables == upgrade_tables, (
        f"create_all vs. upgrade head differ: "
        f"only-in-create_all={create_tables - upgrade_tables}, "
        f"only-in-upgrade-head={upgrade_tables - create_tables}"
    )


def test_stamp_head_on_existing_db(tmp_path):
    """The prod rollout step: a DB already at the current ORM shape (built
    pre-Alembic via ``create_all``) gets ``stamp``ed at head, not
    ``upgrade``d — stamping must not touch any table, and a subsequent
    ``init_schema`` (upgrade head) must be a no-op.
    """
    engine = _engine_at(tmp_path)
    Base.metadata.create_all(engine)
    assert "alembic_version" not in set(inspect(engine).get_table_names())

    cfg = db._alembic_cfg(engine)
    command.stamp(cfg, "head")

    tables_after_stamp = set(inspect(engine).get_table_names())
    assert "alembic_version" in tables_after_stamp

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == ScriptDirectory.from_config(cfg).get_current_head()

    db.init_schema(engine)
    assert set(inspect(engine).get_table_names()) == tables_after_stamp
