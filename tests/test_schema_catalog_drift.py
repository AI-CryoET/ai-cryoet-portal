from __future__ import annotations

from schema.schema_catalog import CATALOG, DOMAIN_ORM, UNDOCUMENTED_ORM_COLUMNS


def _catalog_by_orm():
    by_orm: dict[type, set[str]] = {}
    for e in CATALOG:
        by_orm.setdefault(e.orm, set()).update(f.name for f in e.fields if f.in_db)
    return by_orm


def test_every_documented_field_is_an_orm_column():
    by_orm = _catalog_by_orm()
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
