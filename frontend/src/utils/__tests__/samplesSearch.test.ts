import { describe, it, expect } from 'vitest';
import {
  samplesSearchSchema,
  buildSamplesQueryString,
  type SamplesSearchParams
} from '../samplesSearch';

// Round-trip: a populated params object → query string → URLSearchParams →
// plain object → schema.parse, asserting it survives the trip. Covers one of
// each kind (text array, range min+max, existence true, phase_plate boolean)
// plus the canonical q/sort.
function qsToObject(qs: string): Record<string, string | string[]> {
  const sp = new URLSearchParams(qs.startsWith('?') ? qs.slice(1) : qs);
  const obj: Record<string, string | string[]> = {};
  for (const key of new Set(sp.keys())) {
    const all = sp.getAll(key);
    obj[key] = all.length > 1 ? all : all[0];
  }
  return obj;
}

describe('samplesSearch round-trip', () => {
  it('builds then parses back the same values', () => {
    const params: SamplesSearchParams = {
      lab_name: ['villa', 'rosen'], // text array
      resolution_min: 2, // range
      resolution_max: 10,
      has_aligned_tilt_series: true, // existence
      phase_plate: false, // boolean (tri-state, false is meaningful)
      q: 'foo',
      sort: 'project'
    };

    const parsed = samplesSearchSchema.parse(
      qsToObject(buildSamplesQueryString(params))
    );

    expect(parsed).toMatchObject({
      lab_name: ['villa', 'rosen'],
      resolution_min: 2,
      resolution_max: 10,
      has_aligned_tilt_series: true,
      phase_plate: false,
      q: 'foo',
      sort: 'project'
    });
  });

  it('drops empty params', () => {
    expect(buildSamplesQueryString({})).toBe('');
  });
});
