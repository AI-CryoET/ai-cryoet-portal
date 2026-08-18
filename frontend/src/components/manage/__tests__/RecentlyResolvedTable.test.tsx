/**
 * Component tests for RecentlyResolvedTable (Priority 1 companion, §9.3).
 *
 * Mocks the data hook and CustomLink. Covers:
 *   - a resolved group renders its "Resolved at" timestamp
 *   - the "Nothing resolved in the last 24 hours." empty state
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IssueGroup } from '~/types';

vi.mock('~/components/CustomLink', () => ({
  CustomLink: ({ children }: { children: React.ReactNode }) => (
    <a href="#">{children}</a>
  ),
  IconButtonLink: ({ children }: { children: React.ReactNode }) => (
    <a href="#">{children}</a>
  )
}));

vi.mock('~/utils/queryOptions', () => ({
  useRecentlyResolvedQuery: vi.fn()
}));

import { useRecentlyResolvedQuery } from '~/utils/queryOptions';
import { RecentlyResolvedTable } from '../RecentlyResolvedTable';

const mockUse = vi.mocked(useRecentlyResolvedQuery);

function setData(rows: IssueGroup[]) {
  mockUse.mockReturnValue({
    data: rows
  } as unknown as ReturnType<typeof useRecentlyResolvedQuery>);
}

beforeEach(() => {
  mockUse.mockReset();
});

describe('RecentlyResolvedTable', () => {
  it('renders a resolved group with its resolved-at timestamp', () => {
    const resolvedAt = 1_700_300_000;
    setData([
      {
        scope: 'acquisition',
        sample_id: 'rosen_chromatin_012',
        sample_path: null,
        acquisition_id: 'acq_02',
        acquisition_path: null,
        md_run_id: null,
        file_kind: 'acquisition_toml',
        file_path: '/data/acq_02/acquisition.toml',
        severity: 'warning',
        issues: [
          {
            category: 'out_of_range',
            message: 'acquisition_quality out of range'
          }
        ],
        first_seen_at: 1_700_000_000,
        last_seen_at: 1_700_100_000,
        last_seen_run_id: 'run_x',
        latest_run_id: 'run_y',
        latest_scan_at: 1_700_200_000,
        resolved_at: resolvedAt,
        resolved_run_id: 'run_y'
      }
    ]);
    render(<RecentlyResolvedTable />);
    expect(screen.getByText('rosen_chromatin_012')).toBeInTheDocument();
    expect(screen.getByText('acq_02')).toBeInTheDocument();
    // No Message column anymore — the acquisition's message hangs off its
    // own info icon instead.
    expect(screen.getByLabelText('View message')).toBeInTheDocument();
    const expected = new Date(resolvedAt * 1000).toLocaleString(undefined, {
      timeZoneName: 'short'
    });
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it('renders the "nothing resolved" empty state', () => {
    setData([]);
    render(<RecentlyResolvedTable />);
    expect(
      screen.getByText('Nothing resolved in the last 24 hours.')
    ).toBeInTheDocument();
  });
});
