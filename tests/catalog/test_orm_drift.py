"""Drift test: every Pydantic field has a matching ORM column, and vice versa.

If you add a field to ``schema/schema.py``, you must also add a column to
``catalog/orm.py`` — or this test fails. Same in reverse, except for the
``db_only_columns`` carve-out for each ORM class.
"""

from __future__ import annotations

import datetime as _dt
import types
from enum import Enum
from typing import Annotated, Literal, Union, get_args, get_origin

import pytest

# SQLAlchemy is part of the `catalog` feature; in the bare `test` env this
# import fails. Skip the whole module rather than fail collection.
pytest.importorskip("sqlalchemy")

from sqlalchemy import JSON, Boolean, Date, Float, Integer, String  # noqa: E402
from sqlalchemy import Enum as SAEnum  # noqa: E402

from catalog import orm  # noqa: E402
from schema.schema import (
    Acquisition,
    Annotation,
    Chromatin,
    Fiducial,
    Freezing,
    Label,
    MdRun,
    MdSource,
    Milling,
    PostProcessedTomogram,
    RawTomogram,
    ReconstructionAlignment,
    Sample,
    Simulation,
    TiltSeries,
)

# The scan tables (scan_runs, scan_log_lines, scan_sample_outcomes, issues) and
# the two *_scan_status side tables are intentionally excluded from MAPPING:
# they're catalog-operational, not Pydantic-source data.
# (pydantic_cls, orm_cls, db_only_columns, pydantic_only_pk_fields, directive_only)
# pydantic_only_pk_fields: fields that are Optional[T] in Pydantic but NOT NULL
# in DB because they're path-injected.
# directive_only: fields that exist on the Pydantic model but are scan-time
# directives (§08c's `renamed_from`) with NO corresponding ORM column at all —
# not even a db_only one in reverse. Skipped entirely by every check below.
_RENAMED_FROM = {"renamed_from"}

MAPPING = [
    (Sample, orm.SampleORM, {"deleted_at", "disk_size_bytes", "thumbnail_path"}, {"sample_id", "data_source"}, _RENAMED_FROM),
    (Chromatin, orm.ChromatinORM, {"sample_id"}, set(), set()),
    (Label, orm.LabelORM, {"sample_id", "ordinal"}, set(), set()),
    (Fiducial, orm.FiducialORM, {"sample_id"}, set(), set()),
    (Simulation, orm.SimulationORM, {"sample_id"}, set(), set()),
    (Freezing, orm.FreezingORM, {"sample_id"}, set(), set()),
    (Milling, orm.MillingORM, {"sample_id"}, set(), set()),
    (MdRun, orm.MdRunORM, {"sample_id", "preview_path"}, set(), set()),
    (Acquisition, orm.AcquisitionORM, {"sample_id"}, {"acquisition_id"}, _RENAMED_FROM),
    (MdSource, orm.MdSourceORM, {"sample_id", "acquisition_id"}, set(), set()),
    (
        RawTomogram,
        orm.RawTomogramORM,
        {"sample_id", "acquisition_id"},
        {"reconstruction_alignment_id"},
        _RENAMED_FROM,
    ),
    (
        PostProcessedTomogram,
        orm.PostProcessedTomogramORM,
        {"sample_id", "acquisition_id"},
        {"reconstruction_alignment_id"},
        _RENAMED_FROM,
    ),
    (
        Annotation,
        orm.AnnotationORM,
        {"sample_id", "acquisition_id"},
        {"reconstruction_alignment_id"},
        _RENAMED_FROM,
    ),
    (
        TiltSeries,
        orm.TiltSeriesORM,
        set(),
        {"sample_id", "acquisition_id", "tilt_series_id"},
        _RENAMED_FROM,
    ),
    (
        ReconstructionAlignment,
        orm.ReconstructionAlignmentORM,
        set(),
        {"sample_id", "acquisition_id", "reconstruction_alignment_id"},
        _RENAMED_FROM,
    ),
]


def _strip_annotated(annotation):
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


def _expected_sa_type(annotation):
    """Strip Optional/Annotated, return the SA type CLASS we expect."""
    annotation = _strip_annotated(annotation)
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            annotation = _strip_annotated(args[0])
            origin = get_origin(annotation)
        elif any(get_origin(_strip_annotated(a)) is list for a in args):
            # Polymorphic Union containing ``list[...]`` (e.g.
            # ``float | list[float]`` on ``Label.aunp_size_nm``) is stored
            # as a JSON column so both shapes round-trip.
            return JSON
    if annotation is str:
        return String
    if annotation is int:
        return Integer
    if annotation is float:
        return Float
    if annotation is bool:
        return Boolean
    if annotation is _dt.date:
        return Date
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return SAEnum
    if origin is Literal:
        # Literal[<str>,<str>,...] is stored as a plain String column on the
        # ORM (no SAEnum proliferation for ad-hoc enums). All literal members
        # must share the same scalar type for this branch to make sense.
        members = get_args(annotation)
        member_types = {type(m) for m in members}
        if member_types == {str}:
            return String
        if member_types == {int}:
            return Integer
        raise AssertionError(
            f"Literal with mixed member types not supported: {annotation!r}"
        )
    if get_origin(annotation) is list:
        return JSON
    raise AssertionError(f"unexpected pydantic annotation: {annotation!r}")


def _pydantic_field_is_nullable(field_info) -> bool:
    """A Pydantic field is 'nullable' iff its annotation includes ``None``."""
    ann = _strip_annotated(field_info.annotation)
    origin = get_origin(ann)
    if origin is Union or origin is types.UnionType:
        return type(None) in get_args(ann)
    return False


def _pydantic_column_name(field_name: str, field_info) -> str:
    """Resolve Pydantic alias to expected ORM column name.

    ``Tomogram.tomogram_id`` has alias ``id`` but the DB column is
    ``tomogram_id``. We always use the field *name* as the canonical column
    name (NOT the alias).
    """
    return field_name


@pytest.mark.parametrize("pydantic_cls,orm_cls,db_only,pydantic_pk,directive_only", MAPPING)
def test_every_pydantic_field_has_orm_column(
    pydantic_cls, orm_cls, db_only, pydantic_pk, directive_only
):
    orm_columns = {c.name for c in orm_cls.__table__.columns}
    for field_name, finfo in pydantic_cls.model_fields.items():
        if field_name in directive_only:
            continue
        col_name = _pydantic_column_name(field_name, finfo)
        assert col_name in orm_columns, (
            f"{pydantic_cls.__name__}.{field_name} has no column on {orm_cls.__name__}"
        )


@pytest.mark.parametrize("pydantic_cls,orm_cls,db_only,pydantic_pk,directive_only", MAPPING)
def test_every_orm_column_is_pydantic_or_db_only(
    pydantic_cls, orm_cls, db_only, pydantic_pk, directive_only
):
    pydantic_field_names = set(pydantic_cls.model_fields.keys())
    for col in orm_cls.__table__.columns:
        if col.name in pydantic_field_names:
            continue
        assert col.name in db_only, (
            f"{orm_cls.__name__}.{col.name} is neither a {pydantic_cls.__name__} "
            f"field nor in db_only_columns={db_only}"
        )


@pytest.mark.parametrize("pydantic_cls,orm_cls,db_only,pydantic_pk,directive_only", MAPPING)
def test_column_types_match(pydantic_cls, orm_cls, db_only, pydantic_pk, directive_only):
    orm_columns = {c.name: c for c in orm_cls.__table__.columns}
    for field_name, finfo in pydantic_cls.model_fields.items():
        if field_name in directive_only:
            continue
        col = orm_columns[_pydantic_column_name(field_name, finfo)]
        try:
            expected = _expected_sa_type(finfo.annotation)
        except AssertionError as e:
            pytest.fail(f"{pydantic_cls.__name__}.{field_name}: {e}")
        actual = type(col.type)
        if expected is SAEnum:
            assert isinstance(col.type, SAEnum), (
                f"{orm_cls.__name__}.{field_name}: expected SAEnum, got {actual.__name__}"
            )
        else:
            assert actual is expected, (
                f"{orm_cls.__name__}.{field_name}: expected {expected.__name__}, "
                f"got {actual.__name__}"
            )


@pytest.mark.parametrize("pydantic_cls,orm_cls,db_only,pydantic_pk,directive_only", MAPPING)
def test_nullability_matches(pydantic_cls, orm_cls, db_only, pydantic_pk, directive_only):
    orm_columns = {c.name: c for c in orm_cls.__table__.columns}
    for field_name, finfo in pydantic_cls.model_fields.items():
        if field_name in directive_only:
            continue
        col = orm_columns[_pydantic_column_name(field_name, finfo)]
        pyd_nullable = _pydantic_field_is_nullable(finfo)
        if field_name in pydantic_pk:
            assert col.nullable is False, (
                f"{orm_cls.__name__}.{field_name} is in pydantic_pk whitelist; "
                f"expected nullable=False"
            )
            continue
        assert col.nullable == pyd_nullable, (
            f"{orm_cls.__name__}.{field_name}: pydantic nullable={pyd_nullable}, "
            f"orm nullable={col.nullable}"
        )
