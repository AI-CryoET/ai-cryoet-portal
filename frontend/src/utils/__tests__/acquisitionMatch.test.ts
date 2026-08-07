import { describe, it, expect } from 'vitest';
import { matchAcquisition } from '../acquisitionMatch';
import type { AcquisitionOut } from '~/types';
// Shared contract fixture, also consumed by the pytest backend test, so the two
// predicate implementations can't silently drift. Repo-root relative path;
// resolveJsonModule + Vite JSON import handle it under vitest.
import cases from '../../../../tests/fixtures/acquisition_match_cases.json';

// Fixture acq objects mirror AcquisitionOut but omit fields; matchAcquisition
// treats missing nested arrays as empty, so backfill the required array props.
function asAcq(acq: Record<string, unknown>): AcquisitionOut {
  return {
    tilt_series: [],
    post_processed_tomograms: [],
    annotations: [],
    raw_tomograms: [],
    ...acq
  } as unknown as AcquisitionOut;
}

describe('matchAcquisition (shared fixture)', () => {
  for (const c of cases as Array<{
    name: string;
    acq: Record<string, unknown>;
    filters: Record<string, unknown>;
    expected: boolean;
  }>) {
    it(c.name, () => {
      expect(matchAcquisition(asAcq(c.acq), c.filters)).toBe(c.expected);
    });
  }
});
