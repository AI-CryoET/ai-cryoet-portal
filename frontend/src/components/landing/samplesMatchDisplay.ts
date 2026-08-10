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
