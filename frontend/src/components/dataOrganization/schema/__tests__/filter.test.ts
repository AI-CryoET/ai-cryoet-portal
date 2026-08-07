import { describe, expect, it } from 'vitest';
import { filterTree } from '../shared';
import { SCHEMA } from '../schemaData';

describe('filterTree', () => {
  it('hides chromatin sub-entity when non-chromatin selected', () => {
    const tree = filterTree(SCHEMA, {
      arm: 'experimental',
      chromatin: false,
      source: 'all'
    });
    const sample = tree.find(e => e.id === 'sample')!;
    expect(sample.children?.some(c => c.id === 'chromatin')).toBe(false);
  });

  it('hides simulation-only entities under the experimental arm', () => {
    const tree = filterTree(SCHEMA, {
      arm: 'experimental',
      chromatin: true,
      source: 'all'
    });
    const sample = tree.find(e => e.id === 'sample')!;
    expect(sample.children?.some(c => c.id === 'md_run')).toBe(false);
  });

  it('source=authored drops derived fields', () => {
    const tree = filterTree(SCHEMA, {
      arm: 'experimental',
      chromatin: true,
      source: 'authored'
    });
    const acq = tree.find(e => e.id === 'acquisition')!;
    expect(acq.fields.every(f => f.kind === 'authored')).toBe(true);
  });
});
