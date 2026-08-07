// Client-side acquisition predicate for the subtable filter.
//
// ponytail: duplicates the acquisition EXISTS semantics of
// src/catalog/api/routes/samples.py (scalar IN / NULL-tolerant range / boolean
// + nested existence over tilt_series / raw_tomogram / post_processed_tomograms
// / annotations). Pinned to the backend by the shared test vectors in
// tests/fixtures/acquisition_match_cases.json (consumed by both this vitest and
// the pytest). Change one side -> update the fixture -> both tests gate it.

import { FIELDS, type Field } from './filterFields';
import type { AcquisitionOut } from '~/types';

// Fixture/URL filter values arrive as strings or actual booleans depending on
// the source (raw JSON fixture vs. parsed SamplesSearchParams); normalize.
function asBool(v: unknown): boolean {
  return v === true || v === 'true' || v === '1';
}

// An acquisition column compared as a string against the selected string
// values (mirrors the backend `col.in_(values)` where URL values are strings).
function scalarIn(
  acq: AcquisitionOut,
  column: string,
  values: string[]
): boolean {
  const raw = (acq as Record<string, unknown>)[column];
  if (raw == null) {
    return false;
  }
  return values.includes(String(raw));
}

// NULL-tolerant range (matches `or_(col.is_(None), col >= lo)` / `<= hi`).
function rangeOk(
  acq: AcquisitionOut,
  column: string,
  lo: unknown,
  hi: unknown
): boolean {
  const raw = (acq as Record<string, unknown>)[column];
  if (raw == null) {
    return true;
  } // null passes both bounds
  const n = Number(raw);
  if (lo != null && n < Number(lo)) {
    return false;
  }
  if (hi != null && n > Number(hi)) {
    return false;
  }
  return true;
}

function existenceOk(acq: AcquisitionOut, predicate: string): boolean {
  switch (predicate) {
    case 'has_unaligned_tilt_series':
      return acq.tilt_series.some(t => t.is_aligned !== true);
    case 'has_aligned_tilt_series':
      return acq.tilt_series.some(t => t.is_aligned === true);
    case 'has_tilt_series_zarr':
      return acq.tilt_series.some(t => t.zarr_path != null);
    case 'has_raw_tomogram':
      return acq.raw_tomograms.length > 0;
    case 'has_post_processed_tomogram':
      return acq.post_processed_tomograms.length > 0;
    case 'has_tomogram_zarr':
      return (
        acq.raw_tomograms.some(t => t.zarr_path != null) ||
        acq.post_processed_tomograms.some(t => t.zarr_path != null)
      );
    default:
      return false;
  }
}

// True iff `filters` has an active value for this field.
function isActive(field: Field, filters: Record<string, unknown>): boolean {
  if (field.kind === 'range') {
    return (
      filters[`${field.key}_min`] != null || filters[`${field.key}_max`] != null
    );
  }
  if (field.kind === 'text') {
    const v = filters[field.key];
    return Array.isArray(v) && v.length > 0;
  }
  // boolean / existence: tri-state, active iff present
  return filters[field.key] != null;
}

function fieldHolds(
  field: Field,
  acq: AcquisitionOut,
  filters: Record<string, unknown>
): boolean {
  switch (field.kind) {
    case 'text':
      // annotation_type matches against the nested annotations, not a column.
      if (field.key === 'annotation_type') {
        const values = filters.annotation_type as string[];
        return acq.annotations.some(
          a => a.type != null && values.includes(a.type)
        );
      }
      return scalarIn(acq, field.column, filters[field.key] as string[]);
    case 'range':
      return rangeOk(
        acq,
        field.column,
        filters[`${field.key}_min`],
        filters[`${field.key}_max`]
      );
    case 'boolean': {
      // phase_plate: filter true requires === true; filter false requires !== true.
      const want = asBool(filters[field.key]);
      const actual = (acq as Record<string, unknown>)[field.column];
      return want ? actual === true : actual !== true;
    }
    case 'existence':
      // existence checkbox only constrains when checked (truthy).
      return asBool(filters[field.key]) ? existenceOk(acq, field.column) : true;
    default:
      return true;
  }
}

const ACQUISITION_FIELDS = FIELDS.filter(f => f.entity === 'acquisition');

/**
 * An acquisition matches iff every ACTIVE acquisition-entity filter holds on it
 * (per-acquisition AND), mirroring the backend correlated EXISTS.
 */
export function matchAcquisition(
  acq: AcquisitionOut,
  filters: Record<string, unknown>
): boolean {
  for (const field of ACQUISITION_FIELDS) {
    if (isActive(field, filters) && !fieldHolds(field, acq, filters)) {
      return false;
    }
  }
  return true;
}
