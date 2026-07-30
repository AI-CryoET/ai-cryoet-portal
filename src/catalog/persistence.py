"""Persistence: turn an AssemblyResult into rows in the catalog DB.

The persistence layer is dumb in two senses:
1. It never re-derives field values — whatever the assembler put on the record
   is what gets written.
2. It never re-walks the SampleRecord for extras — the structured ExtrasEntry
   list from schema.loader (passed through AssemblyResult.extras) is
   the single source of truth for the extras table.

A run-level ``now`` and ``run_id`` are supplied by the orchestrator; issue
reconciliation (``reconcile_sample_issues``/``reconcile_run_issues``) diffs the
fresh issue set against the stored outstanding issues, preserving first-seen and
detecting resolution.

Upserts use ``session.merge()`` for cross-dialect portability (SQLite +
Postgres). All operations for one sample happen inside one transaction (the
orchestrator opens ``session.begin()`` around the call); on exception the
transaction rolls back and the orchestrator records the sample as failed.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any, NamedTuple

from sqlalchemy import and_, delete, select, update
from sqlalchemy.orm import Session

from schema import SampleRecord
from schema.loader import ExtrasEntry

from catalog import orm
from catalog.assembler import ScanIssue


class PruneSafetyFloorExceeded(Exception):
    """Raised when soft_delete_missing_samples would delete more than the
    configured fraction of currently-live samples.

    Attributes
    ----------
    missing : list[str]
        Sample IDs that would be soft-deleted.
    threshold : float
        The configured safety-floor ratio (0.0 - 1.0).
    ratio : float
        The actual ratio that triggered the abort.
    """

    def __init__(self, missing: list[str], threshold: float, ratio: float) -> None:
        self.missing = missing
        self.threshold = threshold
        self.ratio = ratio
        super().__init__(
            f"safety floor exceeded: would soft-delete {len(missing)} sample(s) "
            f"({ratio:.1%} > {threshold:.1%})"
        )


class ChildPruneSafetyFloorExceeded(Exception):
    """Raised when a sample's per-child-type stale-row cleanup would delete
    more than the configured fraction of an already-catalogued child
    collection (§08b — mirrors :class:`PruneSafetyFloorExceeded` one level
    down the tree).

    Raised from inside :func:`upsert_sample_record`, which runs inside the
    orchestrator's per-sample ``session.begin()`` (``scanner._scan_one_sample``)
    — the caller's rollback undoes this sample's whole upsert, not just the
    one child type that tripped, and the sample is recorded ``failed``.

    Attributes
    ----------
    to_delete : list[tuple]
        PK tuples of the rows that would have been deleted.
    threshold : float
        The configured safety-floor ratio (0.0 - 1.0).
    ratio : float
        The actual ratio that triggered the abort.
    sample_id : str
        The sample whose upsert is aborting.
    acquisition_id : str | None
        Always ``None`` today — the floor is aggregated per child-type across
        the whole sample's acquisitions rather than scoped to one acquisition
        (see ``_check_child_prune_floor``); kept on the exception so a future
        per-acquisition scope wouldn't need a shape change.
    entity_type : str
        Which guarded level tripped, e.g. ``"acquisition"``, ``"raw_tomogram"``.
    """

    def __init__(
        self,
        to_delete: list,
        threshold: float,
        ratio: float,
        *,
        sample_id: str,
        acquisition_id: str | None,
        entity_type: str,
    ) -> None:
        self.to_delete = to_delete
        self.threshold = threshold
        self.ratio = ratio
        self.sample_id = sample_id
        self.acquisition_id = acquisition_id
        self.entity_type = entity_type
        super().__init__(
            f"child safety floor exceeded for sample={sample_id!r} "
            f"entity_type={entity_type!r}: would delete {len(to_delete)} "
            f"row(s) ({ratio:.1%} > {threshold:.1%})"
        )


class RenameContinuity(NamedTuple):
    """§08c continuity payload returned by :func:`upsert_sample_record`.

    ``sample`` is the old sample id if this upsert's sample was itself a
    rename target, else ``None``. ``acquisitions`` maps each renamed
    acquisition's fresh id to its old id. The caller (``scanner.py``) uses
    these to carry scan-status/issue continuity stamps onto the renamed rows.
    """

    sample: str | None
    acquisitions: dict[str, str]


class GuardedChild(NamedTuple):
    """One §08b/§08a-guarded child collection: the ORM class, its PK column
    names, the fresh keep-set already computed for it, the deletion-feed
    ``entity_type`` string, and (for leaf tables) the column holding its
    reported id."""

    orm_cls: type
    pk_cols: tuple[str, ...]
    keep: set[tuple]
    entity_type: str
    entity_id_attr: str | None


# ─── helpers ─────────────────────────────────────────────────────────────────


def derive_rename_hints(record: SampleRecord) -> tuple[str | None, dict[str, str]]:
    """Read every ``renamed_from`` hint off ``record`` (§08c) without writing
    anything — the single source of truth for "which ids does this record
    claim to be a rename of", shared by ``upsert_sample_record`` and
    ``scanner.py`` (which needs the same answer *before* calling it, to
    snapshot continuity state that ``upsert_sample_record`` is about to
    prune away).

    Returns ``(sample_renamed_from, acq_renames)`` where ``acq_renames`` maps
    each acquisition's fresh id to the old id it was renamed from (only for
    acquisitions that carry the hint).
    """
    sample_renamed_from = record.sample.renamed_from
    acq_renames = {
        acq_id: acq_file.acquisition.renamed_from
        for acq_id, acq_file in record.acquisitions.items()
        if acq_file.acquisition.renamed_from
    }
    return sample_renamed_from, acq_renames


def _filter_to_columns(payload: dict, orm_cls) -> dict:
    """Drop keys from ``payload`` that aren't columns on ``orm_cls``.

    Lets us pass Pydantic dumps that may include nested-model values or other
    keys without SQLAlchemy raising on unknown columns.
    """
    columns = {c.name for c in orm_cls.__table__.columns}
    return {k: v for k, v in payload.items() if k in columns}


def _json_safe(o: Any) -> Any:
    """``json.dumps`` default function — handles ``date``/``datetime`` etc."""
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _row_snapshot(row) -> dict:
    """JSON-safe dict of every column on ``row`` — the deletion feed's
    ``last_known_json`` recovery snapshot."""
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _row_last_known_path(row) -> str | None:
    """First present-and-non-null of ``path``/``mrc_path``/``zarr_path``."""
    for attr in ("path", "mrc_path", "zarr_path"):
        val = getattr(row, attr, None)
        if val is not None:
            return val
    return None


def _rename_already_recorded(
    session: Session, orm_cls, pk: tuple, *, deleted_at_col: str | None = None
) -> bool:
    """True if the old row named by a ``renamed_from`` hint was already
    handled by a previous scan, so recording another rename event now would
    duplicate it.

    ``renamed_from`` is a permanent breadcrumb in the authored TOML (per
    §08c, "it can stay in the file... once the old id is gone the hint is
    inert") — unlike an ordinary deletion, seeing it doesn't stop after one
    scan. The old row's own lifecycle is what's one-shot: acquisition/child
    rows are hard-deleted by the same call that first sees the rename, and
    samples get ``deleted_at`` set by ``soft_delete_missing_samples`` at the
    end of that same run. So "the old row is gone (or, for samples, already
    tombstoned)" is exactly "a rename event was already recorded for it."
    """
    row = session.get(orm_cls, pk)
    if row is None:
        return True
    if deleted_at_col is not None:
        return getattr(row, deleted_at_col) is not None
    return False


def _record_sample_rename(
    session: Session, *, sample_id: str, old_id: str | None, run_id: str, now: float
) -> None:
    """§08c sample-level rename bookkeeping: log one rename event unless a
    previous scan already did (``_rename_already_recorded``). Floor exemption
    at the sample level happens later, in ``soft_delete_missing_samples``
    (see its ``renamed_exempt`` param) — the only place a disappearing sample
    id and a fresh scan's rename hints are both in hand."""
    if old_id is None:
        return
    if _rename_already_recorded(
        session, orm.SampleORM, (old_id,), deleted_at_col="deleted_at"
    ):
        return
    session.add(
        _rename_event(
            run_id=run_id,
            now=now,
            entity_type="sample",
            sample_id=sample_id,
            acquisition_id=None,
            entity_id=None,
            old_id=old_id,
            new_id=sample_id,
        )
    )


def _record_acquisition_rename(
    session: Session,
    exempt_ids: dict[str, set[str]],
    *,
    sample_id: str,
    acquisition_id: str,
    old_id: str,
    run_id: str,
    now: float,
) -> None:
    """§08c acquisition-level rename bookkeeping: exempt ``old_id`` from the
    §08b floor ratio, and log one rename event unless a previous scan
    already did."""
    exempt_ids.setdefault("acquisition", set()).add(old_id)
    if _rename_already_recorded(session, orm.AcquisitionORM, (sample_id, old_id)):
        return
    session.add(
        _rename_event(
            run_id=run_id,
            now=now,
            entity_type="acquisition",
            sample_id=sample_id,
            acquisition_id=acquisition_id,
            entity_id=None,
            old_id=old_id,
            new_id=acquisition_id,
        )
    )


def _record_leaf_rename(
    session: Session,
    exempt_ids: dict[str, set[str]],
    *,
    orm_cls,
    entity_type: str,
    sample_id: str,
    acquisition_id: str,
    entity_id: str,
    old_id: str,
    run_id: str,
    now: float,
) -> None:
    """§08c leaf-child rename bookkeeping shared by raw_tomogram/
    post_processed_tomogram/annotation/tilt_series (identical shape: a
    fresh-id-keyed row one level under an acquisition): exempt ``old_id``
    from the §08b floor ratio, and log one rename event unless a previous
    scan already did."""
    exempt_ids.setdefault(entity_type, set()).add(old_id)
    if _rename_already_recorded(
        session, orm_cls, (sample_id, acquisition_id, old_id)
    ):
        return
    session.add(
        _rename_event(
            run_id=run_id,
            now=now,
            entity_type=entity_type,
            sample_id=sample_id,
            acquisition_id=acquisition_id,
            entity_id=entity_id,
            old_id=old_id,
            new_id=entity_id,
        )
    )


def _rename_event(
    *,
    run_id: str,
    now: float,
    entity_type: str,
    sample_id: str,
    acquisition_id: str | None,
    entity_id: str | None,
    old_id: str,
    new_id: str,
) -> "orm.DeletionEventORM":
    """Build one rename-kind ``DeletionEventORM`` (§08c) — the audit-feed
    counterpart to an ordinary deletion event, recorded instead of (not in
    addition to) the suppressed deletion event for ``old_id``."""
    return orm.DeletionEventORM(
        scan_run_id=run_id,
        detected_at=now,
        entity_type=entity_type,
        kind="rename",
        sample_id=sample_id,
        acquisition_id=acquisition_id,
        entity_id=entity_id,
        last_known_path=None,
        last_known_json=json.dumps({"renamed_from": old_id, "renamed_to": new_id}),
    )


def _deletion_events_for_rows(
    rows: list,
    *,
    run_id: str,
    now: float,
    entity_type: str,
    sample_id: str,
    entity_id_attr: str | None,
) -> list["orm.DeletionEventORM"]:
    """Build one ``DeletionEventORM`` per dropped child row (§08a)."""
    return [
        orm.DeletionEventORM(
            scan_run_id=run_id,
            detected_at=now,
            entity_type=entity_type,
            sample_id=sample_id,
            acquisition_id=getattr(row, "acquisition_id", None),
            entity_id=getattr(row, entity_id_attr, None) if entity_id_attr else None,
            last_known_path=_row_last_known_path(row),
            last_known_json=json.dumps(_row_snapshot(row), default=_json_safe),
        )
        for row in rows
    ]


def _upsert_or_delete_sub(
    session: Session, orm_cls, sample_id: str, pyd_model
) -> None:
    """1:1 sub-entity upsert-or-delete (sample-scoped).

    If ``pyd_model`` is None, DELETE the row (clears stale data when a TOML
    block is removed); otherwise upsert via ``session.merge()``.
    """
    if pyd_model is None:
        session.execute(delete(orm_cls).where(orm_cls.sample_id == sample_id))
        return
    payload = pyd_model.model_dump(exclude_none=False)
    payload["sample_id"] = sample_id
    session.merge(orm_cls(**_filter_to_columns(payload, orm_cls)))


def _select_stale_children(
    session: Session,
    orm_cls,
    sample_id: str,
    *,
    pk_cols: tuple[str, ...],
    keep: set[tuple],
) -> tuple[list, list]:
    """SELECT existing child rows for ``sample_id`` and diff against ``keep``.

    Returns ``(existing, to_delete)`` — does NOT delete anything. Split out of
    the old single-shot ``_delete_stale_children`` (§08b) so
    ``upsert_sample_record`` can floor-check ``to_delete`` against the size of
    ``existing`` *before* any row is dropped, with the ratio math visible in
    ``upsert_sample_record`` (not buried here) so a future §08c can filter
    ``to_delete`` for ``renamed_from`` exemptions without restructuring.

    We do a SELECT of existing rows + Python diff against the in-memory keep
    set rather than ``NOT IN (subquery)`` because the merge() inserts in this
    same transaction may not be flushed/visible to a SELECT yet.
    """
    rows = session.execute(
        select(orm_cls).where(orm_cls.sample_id == sample_id)
    ).scalars().all()

    def _pk(row) -> tuple:
        return tuple(getattr(row, c) for c in pk_cols)

    to_delete = [row for row in rows if _pk(row) not in keep]
    return rows, to_delete


def _execute_stale_deletes(
    session: Session, orm_cls, pk_cols: tuple[str, ...], to_delete: list
) -> None:
    """DELETE each row in ``to_delete``, matched by its ``pk_cols`` values.

    Rows are still readable after the DELETE executes (plain Python objects
    from an earlier SELECT), so callers can build ``DeletionEventORM`` rows
    from them afterwards (§08a).
    """
    for row in to_delete:
        stmt = delete(orm_cls)
        for col in pk_cols:
            stmt = stmt.where(getattr(orm_cls, col) == getattr(row, col))
        session.execute(stmt)


def _delete_stale_children(
    session: Session,
    orm_cls,
    sample_id: str,
    *,
    pk_cols: tuple[str, ...],
    keep: set[tuple],
) -> list:
    """Delete child rows for ``sample_id`` whose PK tuple isn't in ``keep``.

    Unguarded (no §08b floor check) — used only for ``MdRunORM``, which has
    no §08a feed entry either. Guarded child types call
    ``_select_stale_children`` / ``_check_child_prune_floor`` /
    ``_execute_stale_deletes`` directly (see ``upsert_sample_record``).
    """
    _existing, to_delete = _select_stale_children(
        session, orm_cls, sample_id, pk_cols=pk_cols, keep=keep
    )
    _execute_stale_deletes(session, orm_cls, pk_cols, to_delete)
    return to_delete


def _check_child_prune_floor(
    to_delete: list,
    existing: list,
    *,
    pk_cols: tuple[str, ...],
    sample_id: str,
    entity_type: str,
    floor: float,
    min_count: int,
) -> None:
    """Raise :class:`ChildPruneSafetyFloorExceeded` if dropping ``to_delete``
    out of ``existing`` exceeds ``floor``, and at least ``min_count`` rows
    existed (below that, "1 of 1 deleted" would trip on every legitimate
    single-item delete — skip the check entirely).

    Mirrors ``soft_delete_missing_samples``'s whole-run floor one level down
    the tree (§08b), aggregated per child-type *across the whole sample's
    acquisitions* rather than scoped to a single acquisition — matching the
    granularity ``_select_stale_children`` already selects at (every keep-set
    passed in from ``upsert_sample_record`` spans every acquisition under the
    sample already).
    """
    if not to_delete or len(existing) < min_count:
        return
    # §08c will filter renamed-from exemptions out of `to_delete` here before
    # the ratio is computed — a no-op until 08c ships (nothing exempt yet).
    ratio = len(to_delete) / len(existing)
    if ratio > floor:
        raise ChildPruneSafetyFloorExceeded(
            to_delete=[
                tuple(getattr(row, c) for c in pk_cols) for row in to_delete
            ],
            threshold=floor,
            ratio=ratio,
            sample_id=sample_id,
            acquisition_id=None,
            entity_type=entity_type,
        )


# ─── main entry point ────────────────────────────────────────────────────────


def upsert_sample_record(
    session: Session,
    record: SampleRecord,
    *,
    extras: list[ExtrasEntry],
    run_id: str,
    now: float,
    disk_size_bytes: int | None = None,
    thumbnail_path: str | None = None,
    child_prune_safety_floor: float = 0.5,
    child_prune_min_count: int = 3,
) -> RenameContinuity:
    """Per-sample upsert. Steps:

    1. ``samples`` row from ``record.sample`` (clear ``deleted_at`` on
       resurrection).
    2. 1:1 sub-entities upsert-or-delete (chromatin, fiducial, simulation,
       freezing, milling).
    3. ``labels`` ordinal upsert + clean rows with ordinal >= len(record.label).
    4. ``md_runs`` upsert + stale-row cleanup (keyed by md_run_id).
    5. Per-acquisition: ``acquisitions`` upsert, ``md_source`` 1:1
       upsert-or-delete (scoped by acq), ``raw_tomograms`` /
       ``post_processed_tomograms`` / ``annotations`` / ``tilt_series``
       upsert.
    6. ``extras`` refresh: DELETE WHERE sample_id = ? then INSERT fresh.
    7. Stale-row cleanup for the multi-row child tables using Python keep-sets,
       plus the §3.2/§9.10 acquisition-orphan prune: any
       ``acquisition_scan_status`` row and any acquisition-scope ``issue`` whose
       ``(sample_id, acquisition_id)`` is no longer in ``keep_acq_pks`` is
       deleted (no FK cascade is relied upon).

    Step 7's guarded child types (acquisitions + md_source/raw/post
    tomograms/annotations/tilt_series) are floor-checked before their deletes
    execute (§08b): if the fraction dropped for a child-type exceeds
    ``child_prune_safety_floor`` and at least ``child_prune_min_count`` rows
    existed, :class:`ChildPruneSafetyFloorExceeded` aborts — which, since this
    whole call runs inside the orchestrator's per-sample transaction, rolls
    back only this sample's upsert.

    Issue reconciliation is *not* done here — the orchestrator calls
    :func:`reconcile_sample_issues` separately with the same ``run_id``/``now``.

    §08c ``renamed_from``: a fresh sample/acquisition/child carrying
    ``renamed_from = old_id`` (i) suppresses the ordinary §08a deletion event
    that would otherwise fire for ``old_id`` at that level, (ii) exempts
    ``old_id`` from the §08b floor ratio (the old row still physically drops
    as usual — only accounting differs), and (iii) records one ``kind="rename"``
    event in its place. Continuity stamps (scan-status ``last_changed_at``,
    issue ``first_seen_at``) are NOT carried here — this function has no
    access to the run's other scan-status/issue calls, which happen from
    ``scanner.py`` after this returns. Instead, this returns a
    :class:`RenameContinuity` (``sample=old_sample_id | None``,
    ``acquisitions={new_acq_id: old_acq_id}``) so the caller can look up the
    old rows and carry continuity forward
    (``upsert_sample_scan_status``/``upsert_acquisition_scan_status``'s
    ``carried_last_changed_at``, ``reconcile_sample_issues``'s
    ``renamed_from_sample``/``renamed_acquisitions``). Child-level renames
    (tomogram/annotation/tilt_series) have no scan-status table of their own,
    so no continuity wiring is returned for them — event suppression + floor
    exemption is the whole of their §08c handling.
    """
    sample_id = record.sample.sample_id
    assert sample_id is not None, (
        "sample_id must be set on the record before persistence"
    )

    sample_renamed_from, acq_renames = derive_rename_hints(record)

    # ---- §08c: sample-level rename -----------------------------------------
    # Suppression of the old sample's own §08a deletion event + §08a-era
    # PruneSafetyFloorExceeded exemption happens later, in
    # soft_delete_missing_samples (the only place "fresh fs ids" vs. "live DB
    # samples" are ever compared) — scan_root threads this sample's
    # renamed_from through as part of its per-run exempt set. The rename event
    # itself is recorded here, immediately, same as acquisition/child levels.
    _record_sample_rename(
        session, sample_id=sample_id, old_id=sample_renamed_from, run_id=run_id, now=now
    )

    # ---- Step 1: samples row ------------------------------------------------
    sample_payload = record.sample.model_dump(exclude_none=False)
    # Resurrect on every upsert — if the row was previously soft-deleted, the
    # filesystem reappearing must clear the tombstone.
    sample_payload["deleted_at"] = None
    sample_payload["disk_size_bytes"] = disk_size_bytes
    sample_payload["thumbnail_path"] = thumbnail_path
    session.merge(
        orm.SampleORM(**_filter_to_columns(sample_payload, orm.SampleORM))
    )

    # ---- Step 2: 1:1 sub-entities ------------------------------------------
    _upsert_or_delete_sub(session, orm.ChromatinORM, sample_id, record.chromatin)
    _upsert_or_delete_sub(session, orm.FiducialORM, sample_id, record.fiducial)
    _upsert_or_delete_sub(session, orm.SimulationORM, sample_id, record.simulation)
    _upsert_or_delete_sub(session, orm.FreezingORM, sample_id, record.freezing)
    _upsert_or_delete_sub(session, orm.MillingORM, sample_id, record.milling)

    # ---- Step 3: labels (ordinal-keyed list) -------------------------------
    for ordinal, label_model in enumerate(record.label):
        payload = label_model.model_dump(exclude_none=False)
        payload["sample_id"] = sample_id
        payload["ordinal"] = ordinal
        session.merge(orm.LabelORM(**_filter_to_columns(payload, orm.LabelORM)))
    # Clean up trailing ordinals.
    session.execute(
        delete(orm.LabelORM)
        .where(orm.LabelORM.sample_id == sample_id)
        .where(orm.LabelORM.ordinal >= len(record.label))
    )

    # ---- Step 4: md_runs (id-keyed list) -----------------------------------
    keep_md_run_pks: set[tuple[str, str]] = set()
    for run in record.md_run:
        # by_alias=False so the dump uses ``md_run_id`` (the field name),
        # matching the ORM column. The schema field has alias ``id``.
        payload = run.model_dump(exclude_none=False, by_alias=False)
        payload["sample_id"] = sample_id
        session.merge(orm.MdRunORM(**_filter_to_columns(payload, orm.MdRunORM)))
        keep_md_run_pks.add((sample_id, run.md_run_id))

    # ---- Step 5: per-acquisition fan-out -----------------------------------
    keep_acq_pks: set[tuple[str, str]] = set()
    keep_md_source_pks: set[tuple[str, str]] = set()
    keep_raw_tomo_pks: set[tuple[str, str, str]] = set()
    keep_post_tomo_pks: set[tuple[str, str, str]] = set()
    keep_ann_pks: set[tuple[str, str, str]] = set()
    keep_ts_pks: set[tuple[str, str, str]] = set()

    # §08c: old ids named by a fresh entity's `renamed_from` at each guarded
    # level, keyed by the same `entity_type` strings as `guarded_children`
    # below — used to exempt those old rows from both the ordinary §08a
    # deletion event and the §08b floor ratio. `acq_renames` (new -> old,
    # from `derive_rename_hints` above) is returned to the caller for
    # continuity-stamp carry-over (scanner.py).
    exempt_ids: dict[str, set[str]] = {}

    for acq_id, acq_file in record.acquisitions.items():
        acq_payload = acq_file.acquisition.model_dump(
            exclude_none=False, by_alias=False
        )
        acq_payload["sample_id"] = sample_id
        # acquisition_id is Optional on the Pydantic model but PK on the
        # DB; the dict-key from the SampleRecord is authoritative.
        acq_payload["acquisition_id"] = acq_id
        session.merge(
            orm.AcquisitionORM(
                **_filter_to_columns(acq_payload, orm.AcquisitionORM)
            )
        )
        keep_acq_pks.add((sample_id, acq_id))

        old_acq_id = acq_renames.get(acq_id)
        if old_acq_id is not None:
            _record_acquisition_rename(
                session,
                exempt_ids,
                sample_id=sample_id,
                acquisition_id=acq_id,
                old_id=old_acq_id,
                run_id=run_id,
                now=now,
            )

        # md_source is 1:1 per acquisition. Delete on absence, upsert on
        # presence — scoped to this single (sample_id, acquisition_id) so we
        # don't clobber siblings. This is a separate delete path from
        # _delete_stale_children below (which only catches md_source rows
        # whose *acquisition* vanished entirely) — instrument it the same way
        # so an md_source disappearing while its acquisition survives is also
        # logged (§08a). No §08b floor check here (deliberate): this path
        # only ever drops at most one row (md_source is 1:1 per acquisition),
        # so a ratio floor doesn't mean anything — "1 of 1" is definitionally
        # the only possible outcome once md_source disappears. The guarded
        # md_source sweep below (whose *acquisition* vanished) still applies
        # the floor aggregated across the sample.
        if acq_file.md_source is None:
            stale_md_source = session.get(orm.MdSourceORM, (sample_id, acq_id))
            session.execute(
                delete(orm.MdSourceORM).where(
                    and_(
                        orm.MdSourceORM.sample_id == sample_id,
                        orm.MdSourceORM.acquisition_id == acq_id,
                    )
                )
            )
            if stale_md_source is not None:
                for event in _deletion_events_for_rows(
                    [stale_md_source],
                    run_id=run_id,
                    now=now,
                    entity_type="md_source",
                    sample_id=sample_id,
                    entity_id_attr=None,
                ):
                    session.add(event)
        else:
            md_payload = acq_file.md_source.model_dump(exclude_none=False)
            md_payload["sample_id"] = sample_id
            md_payload["acquisition_id"] = acq_id
            session.merge(
                orm.MdSourceORM(
                    **_filter_to_columns(md_payload, orm.MdSourceORM)
                )
            )
            keep_md_source_pks.add((sample_id, acq_id))

        if acq_file.raw_tomogram is not None:
            raw = acq_file.raw_tomogram
            raw_payload = raw.model_dump(exclude_none=False, by_alias=False)
            raw_payload["sample_id"] = sample_id
            raw_payload["acquisition_id"] = acq_id
            session.merge(
                orm.RawTomogramORM(
                    **_filter_to_columns(raw_payload, orm.RawTomogramORM)
                )
            )
            keep_raw_tomo_pks.add((sample_id, acq_id, raw.tomogram_id))
            if raw.renamed_from:
                _record_leaf_rename(
                    session,
                    exempt_ids,
                    orm_cls=orm.RawTomogramORM,
                    entity_type="raw_tomogram",
                    sample_id=sample_id,
                    acquisition_id=acq_id,
                    entity_id=raw.tomogram_id,
                    old_id=raw.renamed_from,
                    run_id=run_id,
                    now=now,
                )

        for tomo in acq_file.post_processed_tomogram:
            tomo_payload = tomo.model_dump(exclude_none=False, by_alias=False)
            tomo_payload["sample_id"] = sample_id
            tomo_payload["acquisition_id"] = acq_id
            session.merge(
                orm.PostProcessedTomogramORM(
                    **_filter_to_columns(
                        tomo_payload, orm.PostProcessedTomogramORM
                    )
                )
            )
            keep_post_tomo_pks.add((sample_id, acq_id, tomo.tomogram_id))
            if tomo.renamed_from:
                _record_leaf_rename(
                    session,
                    exempt_ids,
                    orm_cls=orm.PostProcessedTomogramORM,
                    entity_type="post_processed_tomogram",
                    sample_id=sample_id,
                    acquisition_id=acq_id,
                    entity_id=tomo.tomogram_id,
                    old_id=tomo.renamed_from,
                    run_id=run_id,
                    now=now,
                )

        for ann in acq_file.annotation:
            ann_payload = ann.model_dump(exclude_none=False, by_alias=False)
            ann_payload["sample_id"] = sample_id
            ann_payload["acquisition_id"] = acq_id
            session.merge(
                orm.AnnotationORM(
                    **_filter_to_columns(ann_payload, orm.AnnotationORM)
                )
            )
            keep_ann_pks.add((sample_id, acq_id, ann.annotation_id))
            if ann.renamed_from:
                _record_leaf_rename(
                    session,
                    exempt_ids,
                    orm_cls=orm.AnnotationORM,
                    entity_type="annotation",
                    sample_id=sample_id,
                    acquisition_id=acq_id,
                    entity_id=ann.annotation_id,
                    old_id=ann.renamed_from,
                    run_id=run_id,
                    now=now,
                )

        for ts in acq_file.tilt_series:
            # ``tilt_series_id`` is required at the DB level (composite PK)
            # but Optional on the Pydantic model. The scanner always sets
            # it; defensive skip on None preserves the invariant.
            if ts.tilt_series_id is None:
                continue
            ts_payload = ts.model_dump(exclude_none=False, by_alias=False)
            ts_payload["sample_id"] = sample_id
            ts_payload["acquisition_id"] = acq_id
            session.merge(
                orm.TiltSeriesORM(
                    **_filter_to_columns(ts_payload, orm.TiltSeriesORM)
                )
            )
            keep_ts_pks.add((sample_id, acq_id, ts.tilt_series_id))
            if ts.renamed_from:
                _record_leaf_rename(
                    session,
                    exempt_ids,
                    orm_cls=orm.TiltSeriesORM,
                    entity_type="tilt_series",
                    sample_id=sample_id,
                    acquisition_id=acq_id,
                    entity_id=ts.tilt_series_id,
                    old_id=ts.renamed_from,
                    run_id=run_id,
                    now=now,
                )

    # ---- Step 8: stale-row cleanup for multi-row child tables -------------
    # md_run has no §08a entity_type — not logged to the deletion feed — and
    # no §08b floor either.
    _delete_stale_children(
        session,
        orm.MdRunORM,
        sample_id,
        pk_cols=("sample_id", "md_run_id"),
        keep=keep_md_run_pks,
    )

    # Guarded child types (§08b floor, applied before each delete executes).
    # Each keep-set above already spans every acquisition under the sample
    # (not a single one), so the floor is aggregated per child-type across
    # the whole sample to match — see `_check_child_prune_floor`.
    guarded_children = (
        GuardedChild(orm.AcquisitionORM, ("sample_id", "acquisition_id"),
                     keep_acq_pks, "acquisition", None),
        GuardedChild(orm.MdSourceORM, ("sample_id", "acquisition_id"),
                     keep_md_source_pks, "md_source", None),
        GuardedChild(orm.RawTomogramORM,
                     ("sample_id", "acquisition_id", "tomogram_id"),
                     keep_raw_tomo_pks, "raw_tomogram", "tomogram_id"),
        GuardedChild(orm.PostProcessedTomogramORM,
                     ("sample_id", "acquisition_id", "tomogram_id"),
                     keep_post_tomo_pks, "post_processed_tomogram", "tomogram_id"),
        GuardedChild(orm.AnnotationORM,
                     ("sample_id", "acquisition_id", "annotation_id"),
                     keep_ann_pks, "annotation", "annotation_id"),
        GuardedChild(orm.TiltSeriesORM,
                     ("sample_id", "acquisition_id", "tilt_series_id"),
                     keep_ts_pks, "tilt_series", "tilt_series_id"),
    )
    deleted_rows: dict[str, list] = {}
    for gc in guarded_children:
        existing, to_delete = _select_stale_children(
            session, gc.orm_cls, sample_id, pk_cols=gc.pk_cols, keep=gc.keep
        )
        # §08c: rows named by some fresh entity's `renamed_from` at this level
        # are exempt from both the floor ratio and the ordinary deletion
        # event below (a rename event was already recorded for them, above) —
        # but they still get physically deleted along with the rest of
        # `to_delete` (no PK rewrite; see module docstring / issue 08c).
        exempt = exempt_ids.get(gc.entity_type)
        if exempt:
            leaf_attr = gc.entity_id_attr or gc.pk_cols[-1]
            non_exempt = [
                row for row in to_delete if getattr(row, leaf_attr) not in exempt
            ]
        else:
            non_exempt = to_delete
        _check_child_prune_floor(
            non_exempt,
            existing,
            pk_cols=gc.pk_cols,
            sample_id=sample_id,
            entity_type=gc.entity_type,
            floor=child_prune_safety_floor,
            min_count=child_prune_min_count,
        )
        _execute_stale_deletes(session, gc.orm_cls, gc.pk_cols, to_delete)
        deleted_rows[gc.entity_type] = non_exempt

    # ---- deletion audit feed (§08a) ----------------------------------------
    # One event per dropped row, keyed by run_id/now (already threaded through
    # for issue reconciliation). The orphan acquisition-status/issue prune
    # below is a *consequence* of the acquisition event above and is
    # deliberately NOT logged separately (would double-count).
    for gc in guarded_children:
        for event in _deletion_events_for_rows(
            deleted_rows[gc.entity_type],
            run_id=run_id,
            now=now,
            entity_type=gc.entity_type,
            sample_id=sample_id,
            entity_id_attr=gc.entity_id_attr,
        ):
            session.add(event)

    # ---- acquisition-orphan prune (§3.2 / §9.10) --------------------------
    # Acquisitions are hard-deleted above; mirror that for the side table and
    # for acquisition-scope issues so neither leaks orphans (no FK cascade).
    _prune_orphan_acquisition_status(session, sample_id, keep_acq_pks)

    # ---- Step 6: extras refresh -------------------------------------------
    session.execute(
        delete(orm.ExtrasORM).where(orm.ExtrasORM.sample_id == sample_id)
    )
    for entry in extras:
        session.add(
            orm.ExtrasORM(
                entity_type=entry.entity_type,
                entity_pk_json=json.dumps(list(entry.entity_pk)),
                key=entry.key,
                # Denormalized — by construction equal to sample_id.
                sample_id=entry.entity_pk[0],
                value_json=json.dumps(entry.value, default=_json_safe),
            )
        )

    return RenameContinuity(sample=sample_renamed_from, acquisitions=acq_renames)


def _prune_orphan_acquisition_status(
    session: Session, sample_id: str, keep_acq_pks: set[tuple[str, str]]
) -> None:
    """Delete acquisition_scan_status rows + acquisition-scope issues for
    acquisitions of ``sample_id`` that are no longer present (not in
    ``keep_acq_pks``). Python-diff mirrors ``_delete_stale_children`` so
    in-transaction merges that aren't flushed yet don't confuse a NOT IN.
    """
    # acquisition_scan_status rows
    status_rows = session.execute(
        select(orm.AcquisitionScanStatusORM.acquisition_id).where(
            orm.AcquisitionScanStatusORM.sample_id == sample_id
        )
    ).scalars().all()
    for acq_id in status_rows:
        if (sample_id, acq_id) not in keep_acq_pks:
            session.execute(
                delete(orm.AcquisitionScanStatusORM).where(
                    and_(
                        orm.AcquisitionScanStatusORM.sample_id == sample_id,
                        orm.AcquisitionScanStatusORM.acquisition_id == acq_id,
                    )
                )
            )

    # acquisition-scope issues for this sample
    issue_rows = session.execute(
        select(orm.IssueORM.id, orm.IssueORM.acquisition_id).where(
            and_(
                orm.IssueORM.sample_id == sample_id,
                orm.IssueORM.scope == "acquisition",
            )
        )
    ).all()
    orphan_ids = [
        row_id
        for row_id, acq_id in issue_rows
        if (sample_id, acq_id) not in keep_acq_pks
    ]
    if orphan_ids:
        session.execute(
            delete(orm.IssueORM).where(orm.IssueORM.id.in_(orphan_ids))
        )


# ─── issue reconciliation (§4.4) ─────────────────────────────────────────────


def _issue_fingerprint(issue: ScanIssue) -> str:
    """Stable identity for an issue — deliberately EXCLUDES ``message`` so a
    re-worded message preserves ``first_seen_at`` (decision §9.4)."""
    raw = (
        f"{issue.scope}|{issue.sample_id}|{issue.acquisition_id}"
        f"|{issue.file_kind}|{issue.location}|{issue.category}"
    )
    return hashlib.sha1(raw.encode()).hexdigest()


def _match_renamed_issue(
    session: Session,
    issue: ScanIssue,
    *,
    old_sample_id: str | None,
    old_acquisition_id: str | None,
) -> "orm.IssueORM | None":
    """Best-effort match of a fresh issue against its pre-rename counterpart
    (§08c), so ``first_seen_at`` carries over instead of the rename reading as
    a newly-introduced problem.

    Matches on ``category`` + ``file_kind`` under the old (sample_id,
    acquisition_id) — a `renamed_from` at exactly one level always leaves the
    other id unchanged, so whichever id didn't rename is reused as-is for the
    lookup. If more than one candidate shares category+file_kind (e.g. two
    distinct missing-file issues), we disambiguate by comparing ``location``
    with the old/new id substring stripped out; if that still doesn't pick a
    single winner we just take the first (ponytail: lazy heuristic — this is
    a nice-to-have continuity feature, not correctness-critical, per the
    issue's own tone).
    """
    if old_sample_id is None and old_acquisition_id is None:
        return None
    lookup_sample_id = old_sample_id or issue.sample_id
    lookup_acquisition_id = (
        old_acquisition_id if old_acquisition_id is not None else issue.acquisition_id
    )
    candidates = (
        session.execute(
            select(orm.IssueORM).where(
                and_(
                    orm.IssueORM.sample_id == lookup_sample_id,
                    orm.IssueORM.acquisition_id == lookup_acquisition_id,
                    orm.IssueORM.category == issue.category,
                    orm.IssueORM.file_kind == issue.file_kind,
                )
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def _stripped(location: str | None, *ids: str | None) -> str:
        loc = location or ""
        for i in ids:
            if i:
                loc = loc.replace(i, "")
        return loc

    new_stripped = _stripped(issue.location, issue.sample_id, issue.acquisition_id)
    for c in candidates:
        old_stripped = _stripped(c.location, lookup_sample_id, lookup_acquisition_id)
        if old_stripped == new_stripped:
            return c
    return candidates[0]


def _apply_fresh_issue(
    session: Session,
    issue: ScanIssue,
    fp: str,
    run_id: str,
    now: float,
    outstanding_by_fp: dict[str, "orm.IssueORM"],
    *,
    renamed_from_sample: str | None = None,
    renamed_acquisitions: dict[str, str] | None = None,
) -> bool:
    """Upsert one fresh issue by fingerprint. Returns True if it is newly opened
    (a fresh insert OR the reopening of a previously-resolved row).

    The ``issues.fingerprint`` column is globally UNIQUE, so a recurring problem
    whose row was previously resolved must be *reopened* in place rather than
    re-inserted (which would violate the constraint). ``first_seen_*`` is
    preserved on reopen so the issue's original first-seen survives a
    resolve→recur cycle.

    ``renamed_from_sample``/``renamed_acquisitions`` (§08c): on a genuinely
    fresh insert (not a reopen — a reopened row already has its own
    ``first_seen_at``), try to seed ``first_seen_*`` from the matching
    pre-rename issue instead of ``now``/``run_id`` — see
    :func:`_match_renamed_issue`.
    """
    existing = outstanding_by_fp.get(fp)
    if existing is not None:
        existing.last_seen_at = now
        existing.last_seen_run_id = run_id
        existing.message = issue.message
        existing.severity = issue.severity
        return False

    # Not in the outstanding set — it may still exist as a resolved row.
    prior = session.execute(
        select(orm.IssueORM).where(orm.IssueORM.fingerprint == fp)
    ).scalars().first()
    if prior is not None:
        # Reopen the resolved row (recurrence).
        prior.last_seen_at = now
        prior.last_seen_run_id = run_id
        prior.message = issue.message
        prior.severity = issue.severity
        prior.resolved_at = None
        prior.resolved_run_id = None
        prior.file_path = issue.file_path
        prior.md_run_id = issue.md_run_id
        return True

    first_seen_at, first_seen_run_id = now, run_id
    old_acquisition_id = (
        renamed_acquisitions.get(issue.acquisition_id)
        if renamed_acquisitions and issue.acquisition_id is not None
        else None
    )
    if renamed_from_sample is not None or old_acquisition_id is not None:
        match = _match_renamed_issue(
            session,
            issue,
            old_sample_id=renamed_from_sample,
            old_acquisition_id=old_acquisition_id,
        )
        if match is not None:
            first_seen_at = match.first_seen_at
            first_seen_run_id = match.first_seen_run_id

    session.add(
        orm.IssueORM(
            fingerprint=fp,
            severity=issue.severity,
            scope=issue.scope,
            sample_id=issue.sample_id,
            acquisition_id=issue.acquisition_id,
            md_run_id=issue.md_run_id,
            file_kind=issue.file_kind,
            file_path=issue.file_path,
            location=issue.location,
            category=issue.category,
            message=issue.message,
            first_seen_at=first_seen_at,
            first_seen_run_id=first_seen_run_id,
            last_seen_at=now,
            last_seen_run_id=run_id,
            resolved_at=None,
            resolved_run_id=None,
        )
    )
    return True


def reconcile_sample_issues(
    session: Session,
    run_id: str,
    sample_id: str,
    fresh_issues: list[ScanIssue],
    now: float,
    *,
    resolve_missing: bool = True,
    renamed_from_sample: str | None = None,
    renamed_acquisitions: dict[str, str] | None = None,
) -> tuple[int, int]:
    """Diff ``fresh_issues`` against this sample's outstanding issues (§4.4).

    - Upsert each fresh issue by fingerprint: existing → bump
      ``last_seen_at``/``last_seen_run_id`` + refresh ``message``/``severity``;
      missing → insert with ``first_seen_* = last_seen_* = now/run_id`` and
      ``resolved_at = NULL``.
    - Outstanding issues absent from the fresh set → ``resolved_at = now``,
      ``resolved_run_id = run_id`` — UNLESS ``resolve_missing=False`` (the
      failed-sample path, where we couldn't re-evaluate the sample).

    ``renamed_from_sample`` (§08c): this sample's old id, if
    ``upsert_sample_record`` reported this sample as a rename target.
    ``renamed_acquisitions``: ``{new_acquisition_id: old_acquisition_id}`` for
    any acquisitions renamed this scan. Both feed :func:`_apply_fresh_issue`'s
    first-seen carry-over for fresh inserts only.

    Returns ``(n_new, n_resolved)``.
    """
    outstanding = (
        session.execute(
            select(orm.IssueORM).where(
                and_(
                    orm.IssueORM.sample_id == sample_id,
                    orm.IssueORM.resolved_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_fp = {row.fingerprint: row for row in outstanding}

    n_new = 0
    fresh_fps: set[str] = set()
    for issue in fresh_issues:
        fp = _issue_fingerprint(issue)
        fresh_fps.add(fp)
        if _apply_fresh_issue(
            session,
            issue,
            fp,
            run_id,
            now,
            by_fp,
            renamed_from_sample=renamed_from_sample,
            renamed_acquisitions=renamed_acquisitions,
        ):
            n_new += 1

    n_resolved = 0
    if resolve_missing:
        for fp, row in by_fp.items():
            if fp not in fresh_fps:
                row.resolved_at = now
                row.resolved_run_id = run_id
                n_resolved += 1

    return n_new, n_resolved


def reconcile_run_issues(
    session: Session,
    run_id: str,
    fresh_run_issues: list[ScanIssue],
    now: float,
) -> tuple[int, int]:
    """Reconcile run-scope issues (``scope="run"``, ``sample_id IS NULL``).

    Same diff as :func:`reconcile_sample_issues` but over ALL outstanding
    run-scope issues. The orchestrator calls this ONLY when the run completes
    (§4.4/§9.6) — a crashed run may not have finished discovery, so resolving
    absent run-scope issues would be wrong. Returns ``(n_new, n_resolved)``.
    """
    outstanding = (
        session.execute(
            select(orm.IssueORM).where(
                and_(
                    orm.IssueORM.scope == "run",
                    orm.IssueORM.sample_id.is_(None),
                    orm.IssueORM.resolved_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_fp = {row.fingerprint: row for row in outstanding}

    n_new = 0
    fresh_fps: set[str] = set()
    for issue in fresh_run_issues:
        fp = _issue_fingerprint(issue)
        fresh_fps.add(fp)
        if _apply_fresh_issue(session, issue, fp, run_id, now, by_fp):
            n_new += 1

    n_resolved = 0
    for fp, row in by_fp.items():
        if fp not in fresh_fps:
            row.resolved_at = now
            row.resolved_run_id = run_id
            n_resolved += 1

    return n_new, n_resolved


# ─── freshness + thumbnail provenance status (§4.5) ──────────────────────────


def upsert_sample_scan_status(
    session: Session,
    sample_id: str,
    *,
    now: float,
    outcome: str,
    run_id: str,
    changed: bool,
    carried_last_changed_at: float | None = None,
) -> None:
    """Upsert the 1:1 ``sample_scan_status`` row by PK (§4.5).

    ``last_scanned_at=now`` always; ``last_changed_at=now`` only when
    ``changed`` (an upsert), else the prior value is preserved.

    ``carried_last_changed_at`` (§08c): when ``changed`` and this sample is
    the renamed-to target of an old sample id, the caller passes the OLD
    row's ``last_changed_at`` here so the rename doesn't read as a
    brand-new "just changed" sample. Ignored when ``changed=False``.
    """
    existing = session.get(orm.SampleScanStatusORM, sample_id)
    prior_changed = existing.last_changed_at if existing is not None else None
    if changed:
        last_changed_at = (
            carried_last_changed_at if carried_last_changed_at is not None else now
        )
    else:
        last_changed_at = prior_changed
    session.merge(
        orm.SampleScanStatusORM(
            sample_id=sample_id,
            last_scanned_at=now,
            last_changed_at=last_changed_at,
            last_outcome=outcome,
            last_scan_run_id=run_id,
        )
    )


def upsert_acquisition_scan_status(
    session: Session,
    sample_id: str,
    acquisition_id: str,
    *,
    now: float,
    outcome: str,
    run_id: str,
    changed: bool,
    thumbnail_path: str | None = None,
    thumbnail_source_kind: str | None = None,
    thumbnail_source_path: str | None = None,
    thumbnail_generated_at: float | None = None,
    thumbnail_status: str | None = None,
    carried_last_changed_at: float | None = None,
) -> None:
    """Upsert the 1:1 ``acquisition_scan_status`` row by PK (§4.5).

    Freshness fields mirror :func:`upsert_sample_scan_status`. Thumbnail
    provenance fields are only overwritten when provided (on (re)generation);
    otherwise the prior values are preserved (e.g. on a skip, which carries no
    thumbnail info). ``carried_last_changed_at`` (§08c) mirrors
    :func:`upsert_sample_scan_status`'s parameter of the same name, one level
    down.
    """
    existing = session.get(
        orm.AcquisitionScanStatusORM, (sample_id, acquisition_id)
    )
    prior_changed = existing.last_changed_at if existing is not None else None
    if changed:
        last_changed_at = (
            carried_last_changed_at if carried_last_changed_at is not None else now
        )
    else:
        last_changed_at = prior_changed

    def _pick(new, attr):
        if new is not None:
            return new
        return getattr(existing, attr) if existing is not None else None

    session.merge(
        orm.AcquisitionScanStatusORM(
            sample_id=sample_id,
            acquisition_id=acquisition_id,
            last_scanned_at=now,
            last_changed_at=last_changed_at,
            last_outcome=outcome,
            last_scan_run_id=run_id,
            thumbnail_path=_pick(thumbnail_path, "thumbnail_path"),
            thumbnail_source_kind=_pick(
                thumbnail_source_kind, "thumbnail_source_kind"
            ),
            thumbnail_source_path=_pick(
                thumbnail_source_path, "thumbnail_source_path"
            ),
            thumbnail_generated_at=_pick(
                thumbnail_generated_at, "thumbnail_generated_at"
            ),
            thumbnail_status=_pick(thumbnail_status, "thumbnail_status"),
        )
    )


# ─── soft delete + safety floor ──────────────────────────────────────────────


def soft_delete_missing_samples(
    session: Session,
    fs_sample_ids: set[str],
    *,
    run_id: str,
    now: float,
    dry_run: bool = False,
    safety_floor: float = 0.5,
    report=None,
    renamed_exempt: frozenset[str] = frozenset(),
) -> None:
    """Diff ``fs_sample_ids`` against currently-live samples in the DB.

    - Live samples are those with ``deleted_at IS NULL``.
    - If the prune fraction would exceed ``safety_floor`` (and there is at
      least one live sample), raise :class:`PruneSafetyFloorExceeded` —
      this is checked before either dry-run reporting or writes.
    - On ``dry_run``: append the would-delete IDs to
      ``report.would_soft_delete`` (if a report is provided) and return
      without writing.
    - Otherwise: ``UPDATE samples SET deleted_at = ? WHERE sample_id IN ?``
      and log one ``sample``-level ``DeletionEventORM`` per soft-deleted
      sample (§08a), captured from the row before the tombstone is written.

    ``renamed_exempt`` (§08c): old sample ids that some fresh sample scanned
    *this run* named via ``renamed_from`` — this is the only place a
    disappearing sample id and a fresh scan's rename hints are both in hand,
    so exemption from the floor ratio and deletion-event suppression both
    happen here (the rename event itself was already recorded, immediately,
    by ``upsert_sample_record`` when the new sample was persisted). Exempt
    ids are still soft-deleted like any other missing sample — only the
    floor accounting and the ordinary deletion event are suppressed for them.

    Child entities are intentionally NOT touched: soft delete preserves
    history so a sample can be resurrected by a later upsert. The sample's
    *outstanding issues* ARE resolved, though — a tombstoned sample no longer
    emits them, so they must not keep showing as active; a resurrecting upsert
    re-opens them via ``reconcile_sample_issues``.
    """
    live_rows = (
        session.execute(
            select(orm.SampleORM.sample_id).where(
                orm.SampleORM.deleted_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    live = set(live_rows)
    to_delete = sorted(live - fs_sample_ids)

    if not to_delete:
        return

    non_exempt = [sid for sid in to_delete if sid not in renamed_exempt]

    if live:
        ratio = len(non_exempt) / len(live)
        if ratio > safety_floor:
            raise PruneSafetyFloorExceeded(
                missing=non_exempt, threshold=safety_floor, ratio=ratio
            )

    if dry_run:
        if report is not None:
            existing = getattr(report, "would_soft_delete", None)
            if existing is None:
                report.would_soft_delete = []
            report.would_soft_delete.extend(to_delete)
        return

    # Capture full rows (path + snapshot) before the tombstone write.
    rows = (
        session.execute(
            select(orm.SampleORM).where(orm.SampleORM.sample_id.in_(to_delete))
        )
        .scalars()
        .all()
    )
    for row in rows:
        if row.sample_id in renamed_exempt:
            continue  # §08c: rename event already recorded; no deletion event.
        session.add(
            orm.DeletionEventORM(
                scan_run_id=run_id,
                detected_at=now,
                entity_type="sample",
                sample_id=row.sample_id,
                acquisition_id=None,
                entity_id=None,
                last_known_path=_row_last_known_path(row),
                last_known_json=json.dumps(_row_snapshot(row), default=_json_safe),
            )
        )

    session.execute(
        update(orm.SampleORM)
        .where(orm.SampleORM.sample_id.in_(to_delete))
        .values(deleted_at=now)
    )
    # Resolve the soft-deleted samples' outstanding issues: a tombstoned sample
    # emits nothing, so its warnings must stop counting as active (the manage
    # summary/issues list and stats overview all key off resolved_at IS NULL).
    # A resurrecting upsert re-opens them via reconcile_sample_issues.
    session.execute(
        update(orm.IssueORM)
        .where(orm.IssueORM.sample_id.in_(to_delete))
        .where(orm.IssueORM.resolved_at.is_(None))
        .values(resolved_at=now, resolved_run_id=run_id)
    )
    if report is not None:
        report.soft_deleted = getattr(report, "soft_deleted", 0) + len(to_delete)


__all__ = [
    "ChildPruneSafetyFloorExceeded",
    "PruneSafetyFloorExceeded",
    "RenameContinuity",
    "derive_rename_hints",
    "reconcile_run_issues",
    "reconcile_sample_issues",
    "soft_delete_missing_samples",
    "upsert_acquisition_scan_status",
    "upsert_sample_record",
    "upsert_sample_scan_status",
]
