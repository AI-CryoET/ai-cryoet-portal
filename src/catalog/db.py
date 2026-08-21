"""SQLAlchemy engine + session helpers for the CryoET catalog.

Schema initialization is delegated to Alembic. ``init_schema(engine)`` runs
``alembic upgrade head`` against the engine. See
``catalog/migrations/README.md``.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DB_URL = "sqlite:///catalog.db"

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_ALEMBIC_INI = _MIGRATIONS_DIR / "alembic.ini"


def make_engine(url: str = DEFAULT_DB_URL) -> Engine:
    """Create a SQLAlchemy engine. Accepts any URL — sqlite:// or postgresql://."""
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        # DELETE (rollback) journal + a busy timeout, set on every connection.
        # SQLite only — Postgres ignores these.
        #
        # NOT WAL: in prod the scanner (writer) and api (reader) run as separate
        # pods sharing one DB file on a network (RWX) PVC. WAL coordinates
        # readers/writers through a shared-memory index (-shm) that SQLite
        # requires all connections to reach on the same host; across pods it
        # can't, which silently corrupted the catalog ("database disk image is
        # malformed"). Rollback-journal mode has no -shm and uses POSIX locks
        # (with busy_timeout to ride out the scanner's brief exclusive writes),
        # which is safe for this single-writer / one-reader layout.
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=DELETE")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def _alembic_cfg(engine: Engine):
    """Build an Alembic Config bound to ``engine`` for in-process use.

    The config file lives next to the migrations directory and is the same
    one the ``pixi run migrate`` task uses. We override ``sqlalchemy.url``
    from the engine and stash a live connection in ``cfg.attributes`` so
    ``env.py`` can use it directly (avoiding a second engine for the same
    DB, which on SQLite means a second file handle).
    """
    from alembic.config import Config  # local import: alembic is optional

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.attributes["connection"] = engine
    return cfg


def init_schema(engine: Engine) -> None:
    """Bring the DB at ``engine`` up to the head ORM revision via Alembic.

    Runs ``alembic upgrade head``. Works for both fresh DBs and any DB
    already under Alembic management (including one ``stamp``ed at head
    without being rebuilt — see ``catalog/migrations/README.md``).
    """
    from alembic import command  # local import: alembic is optional

    command.upgrade(_alembic_cfg(engine), "head")


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Yield a session inside a transaction.

    Commits on clean exit, rolls back on exception, and always closes.
    """
    SessionFactory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
