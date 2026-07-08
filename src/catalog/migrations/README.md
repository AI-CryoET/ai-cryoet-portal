# `catalog` migrations

Schema evolution for the catalog DB is managed by [Alembic][alembic]. The ORM
in `catalog/orm.py` is the source of truth; revisions in `versions/` describe
the deltas between historical snapshots of that ORM.

`Base.metadata.create_all(engine)` is **not** the lifecycle entry point —
`catalog.db.init_schema(engine)` runs `alembic upgrade head` instead. The only
place `create_all` survives is the DDL-drift sanity check in
`tests/catalog/test_alembic.py`.

## Pixi tasks

```bash
# Apply every pending revision to head (against $CATALOG_DB_URL or the default).
pixi run -e catalog migrate

# Generate a new autogenerate revision after changing the ORM.
# The message is passed after `--`:
pixi run -e catalog migrate-revision -- "description of change"
```

Both tasks resolve to `alembic -c src/catalog/migrations/alembic.ini …`. The
DB URL is read from `CATALOG_DB_URL` in the environment, falling back to
`catalog.db.DEFAULT_DB_URL` (`sqlite:///catalog.db`).

## Workflow

1. Edit `catalog/orm.py` (and the corresponding Pydantic model in
   `schema/schema.py` — the drift test will yell otherwise).
2. Run `pixi run -e catalog migrate-revision -- "what changed"`.
3. **Open the generated revision under `versions/` and review every line.**
   Autogenerate is good but not perfect — see "SQLite caveats" below.
4. Apply with `pixi run -e catalog migrate`.
5. Update `tests/catalog/test_orm_drift.py` and any tests covering the new
   column/table.

## Rolling out to an already-running production DB

A prod DB that predates a given revision but already has the tables that
revision would create (e.g. the one-time cutover to Alembic itself) should be
**stamped**, not upgraded:

```bash
CATALOG_DB_URL=<prod url> alembic -c src/catalog/migrations/alembic.ini stamp head
```

`stamp` writes `alembic_version` without running any `upgrade()` — running
`upgrade head` instead would try to `CREATE TABLE` things that already exist
and fail. From that point on, `init_schema` (`alembic upgrade head`) applies
cleanly to that DB like any other.

## SQLite caveats

- **`render_as_batch=True` is mandatory** for `ALTER TABLE`. SQLite's
  in-place ALTER TABLE is far too narrow (no DROP COLUMN, no ALTER COLUMN
  type), so Alembic's batch mode rebuilds the whole table. That rebuild
  drops any **manual indexes, triggers, and PRAGMAs** not represented in
  the ORM. If you've added one outside Alembic, it will not survive a
  migration.
- **Autogenerate misses some changes.** It does NOT detect:
  - CHECK constraint changes,
  - server-side default changes (sometimes),
  - certain composite / functional index changes,
  - changes to type metadata that share an SA backing (e.g. `String(20)` →
    `String(40)` on SQLite where everything is TEXT — `compare_type=True`
    helps for cross-type but not always for length).
- **Review every revision diff before committing.** The `versions/` files
  are normal Python; treat them as code.
- **Add a data-preservation test when a revision alters an existing table.**
  Seed rows before `upgrade`, assert row counts (and any new columns'
  values) after — that's the safety net against silent batch-rebuild data
  loss. `tests/catalog/test_alembic.py` has no such test yet since the
  baseline revision only creates tables; add one alongside the first
  revision that does an `ALTER TABLE`.

[alembic]: https://alembic.sqlalchemy.org/
