import { describe, expect, it } from 'vitest';
import type { IssueGroup } from '~/types';
import { groupBySample } from '../groupSampleWarnings';

function group(overrides: Partial<IssueGroup>): IssueGroup {
  return {
    scope: 'acquisition',
    sample_id: 'samp1',
    acquisition_id: null,
    acquisition_path: null,
    sample_path: '/data/samp1',
    md_run_id: null,
    file_kind: 'acquisition_toml',
    file_path: null,
    severity: 'warning',
    issues: [{ category: 'undeclared_annotation_folder', message: 'm' }],
    first_seen_at: 100,
    last_seen_at: 100,
    last_seen_run_id: 'r-latest',
    latest_run_id: 'r-latest',
    latest_scan_at: 200,
    resolved_at: null,
    ...overrides
  };
}

const texts = (ms: { text: string }[]) => ms.map(m => m.text);

describe('groupBySample', () => {
  it('collapses every acquisition of a sample into one band', () => {
    const bands = groupBySample([
      group({
        acquisition_id: 'acq1',
        acquisition_path: '/data/samp1/acq1',
        issues: [
          { category: 'undeclared_annotation_folder', message: "id 'a1'" }
        ]
      }),
      group({
        acquisition_id: 'acq2',
        acquisition_path: '/data/samp1/acq2',
        issues: [
          { category: 'undeclared_annotation_folder', message: "id 'a2'" }
        ]
      })
    ]);

    expect(bands).toHaveLength(1);
    expect(bands[0].acquisitions.map(a => a.acquisition_id)).toEqual([
      'acq1',
      'acq2'
    ]);
    expect(texts(bands[0].acquisitions[0].messages)).toEqual(["id 'a1'"]);
    expect(texts(bands[0].acquisitions[1].messages)).toEqual(["id 'a2'"]);
  });

  it('leaves the acquisitions list empty for sample-only issues', () => {
    const bands = groupBySample([
      group({
        scope: 'sample',
        acquisition_id: null,
        file_kind: 'sample_toml',
        issues: [{ category: 'assembly_failed', message: 'boom' }]
      })
    ]);
    expect(bands[0].acquisitions).toEqual([]);
    expect(texts(bands[0].sampleEntries[0].messages)).toEqual(['boom']);
    expect(bands[0].sampleEntries[0].messages[0].scope).toBe('sample');
  });

  it('keeps different md_run_ids as separate sample entries in the band', () => {
    const bands = groupBySample([
      group({
        scope: 'sample',
        file_kind: 'md_run_toml',
        md_run_id: 'run_a',
        issues: [{ category: 'unfilled_placeholder', message: 'run_a' }]
      }),
      group({
        scope: 'sample',
        file_kind: 'md_run_toml',
        md_run_id: 'run_b',
        issues: [{ category: 'unfilled_placeholder', message: 'run_b' }]
      })
    ]);
    expect(bands).toHaveLength(1);
    expect(bands[0].sampleEntries.map(e => e.md_run_id)).toEqual([
      'run_a',
      'run_b'
    ]);
  });

  it('rolls up band severity to the worst across acquisitions', () => {
    const bands = groupBySample([
      group({ acquisition_id: 'acq1', severity: 'warning' }),
      group({ acquisition_id: 'acq2', severity: 'error' })
    ]);
    expect(bands[0].severity).toBe('error');
  });

  it('marks an acquisition stale (with its stale timestamp) when it was skipped this scan', () => {
    const bands = groupBySample([
      group({
        acquisition_id: 'acq1',
        last_seen_run_id: 'r-old',
        last_seen_at: 50,
        latest_run_id: 'r-latest',
        latest_scan_at: 200
      })
    ]);
    const acq = bands[0].acquisitions[0];
    expect(acq.reEvaluated).toBe(false);
    expect(acq.stillPresentAt).toBe(50);
  });

  it('groups a reconstruction-scoped issue under its acquisition', () => {
    const bands = groupBySample([
      group({
        acquisition_id: 'acq1',
        acquisition_path: '/data/samp1/acq1',
        issues: [
          {
            category: 'undeclared_reconstruction_alignment_folder',
            message: 'group grp1 undeclared',
            reconstruction_alignment_id: 'grp1'
          }
        ]
      })
    ]);
    const recon = bands[0].acquisitions[0].reconstructions[0];
    expect(recon.reconstruction_alignment_id).toBe('grp1');
    expect(texts(recon.messages)).toEqual(['group grp1 undeclared']);
    expect(recon.messages[0].scope).toBe('reconstruction');
  });

  it('sorts reconstructions alphabetically', () => {
    const bands = groupBySample([
      group({
        acquisition_id: 'acq1',
        issues: [
          {
            category: 'c',
            message: 'b',
            reconstruction_alignment_id: 'grp_b'
          },
          {
            category: 'c',
            message: 'a',
            reconstruction_alignment_id: 'grp_a'
          }
        ]
      })
    ]);
    expect(
      bands[0].acquisitions[0].reconstructions.map(
        r => r.reconstruction_alignment_id
      )
    ).toEqual(['grp_a', 'grp_b']);
  });

  it('keeps a reconstruction-owned message off the parent acquisition', () => {
    const bands = groupBySample([
      group({
        acquisition_id: 'acq1',
        issues: [
          {
            category: 'undeclared_reconstruction_alignment_folder',
            message: 'group grp1 undeclared',
            reconstruction_alignment_id: 'grp1'
          }
        ]
      })
    ]);
    const acq = bands[0].acquisitions[0];
    expect(acq.messages).toEqual([]);
    expect(texts(acq.reconstructions[0].messages)).toEqual([
      'group grp1 undeclared'
    ]);
  });

  it('keeps acquisition-scoped messages on the acquisition (no reconstruction)', () => {
    const bands = groupBySample([
      group({
        acquisition_id: 'acq1',
        issues: [
          {
            category: 'undeclared_annotation_folder',
            message: 'no group here',
            reconstruction_alignment_id: null
          }
        ]
      })
    ]);
    const acq = bands[0].acquisitions[0];
    expect(acq.reconstructions).toEqual([]);
    expect(texts(acq.messages)).toEqual(['no group here']);
    expect(acq.messages[0].scope).toBe('acquisition');
  });
});
