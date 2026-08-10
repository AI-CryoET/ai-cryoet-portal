import { describe, expect, it } from 'vitest';
import type { SampleMatch } from '~/types';
import { matchedAcquisitionIds } from '../samplesMatchDisplay';

describe('matchedAcquisitionIds', () => {
  it('collects acquisition ids from acquisition/tomogram/annotation matches', () => {
    const matches: SampleMatch[] = [
      { kind: 'tomogram', acquisition_id: 'acq-100', matched_id: 'tomo-777' },
      { kind: 'annotation', acquisition_id: 'acq-200', matched_id: 'annot-9' },
      { kind: 'acquisition', acquisition_id: 'acq-100', matched_id: 'acq-100' }
    ];
    expect(matchedAcquisitionIds(matches)).toEqual(
      new Set(['acq-100', 'acq-200'])
    );
  });

  it('ignores sample-level matches (no acquisition)', () => {
    const matches: SampleMatch[] = [
      { kind: 'sample', acquisition_id: null, matched_id: 'smp-alpha' }
    ];
    expect(matchedAcquisitionIds(matches)).toEqual(new Set());
  });

  it('returns an empty set for no matches', () => {
    expect(matchedAcquisitionIds([])).toEqual(new Set());
  });
});
