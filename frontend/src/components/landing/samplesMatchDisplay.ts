import type { SampleMatch } from '~/types';

// The acquisitions to highlight in an expanded sample: every acquisition that
// contains a search hit at any level (the acquisition id itself, or a tomogram
// / annotation under it). Sample-id hits carry no acquisition, so they add
// nothing here.
export function matchedAcquisitionIds(matches: SampleMatch[]): Set<string> {
  const ids = new Set<string>();
  for (const m of matches) {
    if (m.acquisition_id) {
      ids.add(m.acquisition_id);
    }
  }
  return ids;
}

// True when a sample has a match below the sample level (acquisition/tomogram
// /annotation) — drives auto-expanding the sample's detail panel. A sample-id-only
// match does not auto-expand (nothing to see in the sub-table).
export function hasDescendantMatch(matches: SampleMatch[]): boolean {
  return matchedAcquisitionIds(matches).size > 0;
}

// Stable-partitions `items` into matched-first, then the rest, each group
// keeping its original relative order.
export function orderWithMatchesFirst<T>(
  items: T[],
  matchedIds: Set<string>,
  idOf: (item: T) => string
): T[] {
  if (matchedIds.size === 0) {
    return items;
  }
  const matched: T[] = [];
  const rest: T[] = [];
  for (const item of items) {
    (matchedIds.has(idOf(item)) ? matched : rest).push(item);
  }
  return [...matched, ...rest];
}
