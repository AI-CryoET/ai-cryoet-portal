from __future__ import annotations

from pathlib import Path

from catalog import orm
from schema.generate_schema_docs import _MD_OUT, _TS_OUT, render_md, render_ts
from schema.schema_catalog import CATALOG, DOMAIN_ORM, OPERATIONAL_ORM, UNDOCUMENTED_ORM_COLUMNS


def _catalog_by_orm():
    by_orm: dict[type, set[str]] = {}
    for e in CATALOG:
        by_orm.setdefault(e.orm, set()).update(f.name for f in e.fields if f.in_db)
    return by_orm


def test_every_documented_field_is_an_orm_column():
    for e in CATALOG:
        cols = {c.name for c in e.orm.__table__.columns}
        documented = {f.name for f in e.fields if f.in_db}
        stray = documented - cols
        assert not stray, f"{e.key}: documented fields absent from {e.orm.__name__}: {sorted(stray)}"


def test_every_domain_orm_column_is_documented_or_internal():
    by_orm = _catalog_by_orm()
    for model in DOMAIN_ORM:
        cols = {c.name for c in model.__table__.columns}
        documented = by_orm.get(model, set())
        internal = UNDOCUMENTED_ORM_COLUMNS.get(model.__tablename__, set())
        missing = cols - documented - internal
        assert not missing, (
            f"{model.__name__}: ORM columns neither documented in schema_catalog "
            f"nor listed internal: {sorted(missing)}"
        )


def test_domain_and_operational_orm_partition_all_tables():
    all_orm = {m.class_ for m in orm.Base.registry.mappers}
    classified = set(DOMAIN_ORM) | set(OPERATIONAL_ORM)
    assert all_orm == classified, (
        "A mapped ORM class is missing from schema_catalog's DOMAIN_ORM/"
        "OPERATIONAL_ORM partition. Add the new class to DOMAIN_ORM (if it "
        "should be documented in the catalog) or OPERATIONAL_ORM (if it's "
        f"internal/operational). Unclassified: {sorted(c.__name__ for c in all_orm - classified)}"
    )


def test_committed_schema_md_matches_codegen():
    assert Path(_MD_OUT).read_text() == render_md(), (
        "docs/schema.md is out of sync with schema_catalog.py. "
        "Regenerate with `pixi run schema-docs`."
    )


def test_committed_schema_ts_matches_codegen():
    assert Path(_TS_OUT).read_text() == render_ts(), (
        "frontend schemaData.ts is out of sync with schema_catalog.py. "
        "Regenerate with `pixi run schema-docs`."
    )
