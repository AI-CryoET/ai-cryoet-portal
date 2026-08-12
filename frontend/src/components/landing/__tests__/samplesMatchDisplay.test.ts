import { describe, expect, it } from 'vitest';
import type { SampleMatch } from '~/types';
import {
  hasDescendantMatch,
  matchedAcquisitionIds,
  orderWithMatchesFirst
} from '../samplesMatchDisplay';

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

describe('hasDescendantMatch', () => {
  it('is false when the only match is sample-level', () => {
    const matches: SampleMatch[] = [
      { kind: 'sample', acquisition_id: null, matched_id: 'smp-alpha' }
    ];
    expect(hasDescendantMatch(matches)).toBe(false);
  });

  it('is true when a tomogram/annotation/acquisition match is present', () => {
    const matches: SampleMatch[] = [
      { kind: 'sample', acquisition_id: null, matched_id: 'smp-alpha' },
      { kind: 'tomogram', acquisition_id: 'acq-100', matched_id: 'tomo-777' }
    ];
    expect(hasDescendantMatch(matches)).toBe(true);
  });

  it('is false for no matches', () => {
    expect(hasDescendantMatch([])).toBe(false);
  });
});

describe('orderWithMatchesFirst', () => {
  const idOf = (s: string) => s;

  it('moves matched items to the front, preserving relative order within each group', () => {
    const items = ['a1', 'a2', 'a3', 'a4', 'a5'];
    const matched = new Set(['a3', 'a4', 'a5']);
    expect(orderWithMatchesFirst(items, matched, idOf)).toEqual([
      'a3',
      'a4',
      'a5',
      'a1',
      'a2'
    ]);
  });

  it('returns items unchanged when no ids match', () => {
    const items = ['a1', 'a2'];
    expect(orderWithMatchesFirst(items, new Set(), idOf)).toEqual(['a1', 'a2']);
  });

  it('returns items unchanged when every id matches', () => {
    const items = ['a1', 'a2'];
    const matched = new Set(['a1', 'a2']);
    expect(orderWithMatchesFirst(items, matched, idOf)).toEqual(['a1', 'a2']);
  });
});
