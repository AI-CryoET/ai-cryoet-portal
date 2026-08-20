import { describe, expect, it } from 'vitest';
import type { IssueGroup } from '~/types';
import { groupSampleWarnings } from '../groupSampleWarnings';

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
    ...overrides
  };
}

describe('groupSampleWarnings', () => {
  it('merges the same category across acquisitions into one row', () => {
    const rows = groupSampleWarnings([
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

    expect(rows).toHaveLength(1);
    expect(rows[0].acquisitions.map(a => a.acquisition_id)).toEqual([
      'acq1',
      'acq2'
    ]);
    expect(rows[0].acquisitions[0].messages).toEqual(["id 'a1'"]);
    expect(rows[0].acquisitions[1].messages).toEqual(["id 'a2'"]);
  });

  it('renders a dash-worthy empty acquisitions list for sample-only issues', () => {
    const rows = groupSampleWarnings([
      group({
        scope: 'sample',
        acquisition_id: null,
        file_kind: 'sample_toml',
        issues: [{ category: 'assembly_failed', message: 'boom' }]
      })
    ]);
    expect(rows[0].acquisitions).toEqual([]);
  });

  it('keeps different md_run_ids as separate rows, not merged', () => {
    const rows = groupSampleWarnings([
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
    expect(rows).toHaveLength(2);
  });

  it('rolls up severity to the worst across merged acquisitions', () => {
    const rows = groupSampleWarnings([
      group({
        acquisition_id: 'acq1',
        severity: 'warning',
        issues: [{ category: 'tilt_series_alignment_mismatch', message: 'm' }]
      }),
      group({
        acquisition_id: 'acq2',
        severity: 'error',
        issues: [{ category: 'tilt_series_alignment_mismatch', message: 'm' }]
      })
    ]);
    expect(rows[0].severity).toBe('error');
  });

  it('marks the row stale when any acquisition was skipped this scan, using the oldest stale timestamp', () => {
    const rows = groupSampleWarnings([
      group({
        acquisition_id: 'acq1',
        last_seen_run_id: 'r-latest',
        last_seen_at: 190,
        latest_run_id: 'r-latest',
        latest_scan_at: 200
      }),
      group({
        acquisition_id: 'acq2',
        last_seen_run_id: 'r-old',
        last_seen_at: 50,
        latest_run_id: 'r-latest',
        latest_scan_at: 200
      })
    ]);
    expect(rows[0].reEvaluated).toBe(false);
    expect(rows[0].stillPresentAt).toBe(50);
  });

  it('uses the earliest first_seen_at across merged acquisitions', () => {
    const rows = groupSampleWarnings([
      group({ acquisition_id: 'acq1', first_seen_at: 500 }),
      group({ acquisition_id: 'acq2', first_seen_at: 100 })
    ]);
    expect(rows[0].first_seen_at).toBe(100);
  });

  it('groups issues carrying a reconstruction_alignment_id under that acquisition', () => {
    const rows = groupSampleWarnings([
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
    expect(rows[0].acquisitions[0].reconstructions).toEqual([
      {
        reconstruction_alignment_id: 'grp1',
        acquisition_id: 'acq1',
        messages: ['group grp1 undeclared']
      }
    ]);
  });

  it('collects two distinct reconstruction groups under the same acquisition separately', () => {
    const rows = groupSampleWarnings([
      group({
        acquisition_id: 'acq1',
        issues: [
          {
            category: 'undeclared_reconstruction_alignment_folder',
            message: 'group grp_b undeclared',
            reconstruction_alignment_id: 'grp_b'
          },
          {
            category: 'undeclared_reconstruction_alignment_folder',
            message: 'group grp_a undeclared',
            reconstruction_alignment_id: 'grp_a'
          }
        ]
      })
    ]);
    // Sorted alphabetically, same as acquisitions.
    expect(
      rows[0].acquisitions[0].reconstructions.map(
        r => r.reconstruction_alignment_id
      )
    ).toEqual(['grp_a', 'grp_b']);
  });

  it('keeps a reconstruction-owned message off the parent acquisition', () => {
    const rows = groupSampleWarnings([
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
    // The acquisition is still listed (grouping parent) but carries no
    // message of its own — the text lives only on the reconstruction.
    expect(rows[0].acquisitions[0].messages).toEqual([]);
    expect(rows[0].acquisitions[0].reconstructions[0].messages).toEqual([
      'group grp1 undeclared'
    ]);
  });

  it('skips reconstructions for issues with a null reconstruction_alignment_id', () => {
    const rows = groupSampleWarnings([
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
    expect(rows[0].acquisitions[0].reconstructions).toEqual([]);
  });
});
