/**
 * Component tests for OutstandingIssuesTable (Priority 1, plan §5.2 / §6).
 *
 * Mocks the data hook (`useOutstandingIssuesQuery`) and CustomLink so the table
 * renders without a router/query context. Covers:
 *   - rows render entity link, file kind, severity pill, messages, first-seen
 *   - "still present as of" §9.7: re-evaluated owner → latest scan ts;
 *     skipped owner → the group's last_seen_at with the skipped tooltip text
 *   - empty state copy
 */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { IssueGroup } from '~/types'

// Plain-anchor stand-in so the router's createLink isn't needed.
vi.mock('~/components/CustomLink', () => ({
  CustomLink: ({ children }: { children: React.ReactNode }) => (
    <a href="#">{children}</a>
  ),
}))

vi.mock('~/utils/queryOptions', () => ({
  useOutstandingIssuesQuery: vi.fn(),
}))

import { useOutstandingIssuesQuery } from '~/utils/queryOptions'
import { OutstandingIssuesTable } from '../OutstandingIssuesTable'

const mockUse = vi.mocked(useOutstandingIssuesQuery)

function group(overrides: Partial<IssueGroup>): IssueGroup {
  return {
    scope: 'sample',
    sample_id: 'villa_synapse_004',
    acquisition_id: null,
    md_run_id: null,
    file_kind: 'sample_toml',
    file_path: '/data/villa_synapse_004/sample.toml',
    severity: 'error',
    issues: [{ category: 'missing_field', message: 'missing required field project' }],
    first_seen_at: 1_700_000_000,
    last_seen_at: 1_700_100_000,
    last_seen_run_id: 'run_latest',
    latest_run_id: 'run_latest',
    latest_scan_at: 1_700_200_000,
    ...overrides,
  }
}

function setData(rows: IssueGroup[]) {
  mockUse.mockReturnValue({
    data: rows,
    isFetching: false,
  } as unknown as ReturnType<typeof useOutstandingIssuesQuery>)
}

beforeEach(() => {
  mockUse.mockReset()
})

describe('OutstandingIssuesTable', () => {
  it('renders an issue row with its message, file kind and severity', () => {
    setData([group({})])
    render(<OutstandingIssuesTable />)
    expect(screen.getByText('villa_synapse_004')).toBeInTheDocument()
    expect(
      screen.getByText('missing required field project'),
    ).toBeInTheDocument()
    expect(screen.getByText('sample_toml')).toBeInTheDocument()
    expect(screen.getByText('error')).toBeInTheDocument()
  })

  it('shows the latest-scan timestamp when the owner was re-evaluated', () => {
    setData([group({ last_seen_run_id: 'run_latest', latest_run_id: 'run_latest' })])
    render(<OutstandingIssuesTable />)
    const expected = new Date(1_700_200_000 * 1000).toLocaleString(undefined, { timeZoneName: 'short' })
    expect(screen.getByText(expected)).toBeInTheDocument()
  })

  it('shows the skipped-owner tooltip and stale last_seen when not re-evaluated', () => {
    setData([
      group({ last_seen_run_id: 'run_old', latest_run_id: 'run_latest' }),
    ])
    render(<OutstandingIssuesTable />)
    const stale = new Date(1_700_100_000 * 1000).toLocaleString(undefined, { timeZoneName: 'short' })
    expect(screen.getByText(stale)).toBeInTheDocument()
    // The MUI Tooltip title is rendered as an aria-label on the wrapped element.
    expect(
      screen.getByLabelText('owner skipped — not re-checked'),
    ).toBeInTheDocument()
  })

  it('renders the empty state when there are no outstanding issues', () => {
    setData([])
    render(<OutstandingIssuesTable />)
    expect(
      screen.getByText('No outstanding warnings or errors.'),
    ).toBeInTheDocument()
  })

  it('prefills the search box from the q prop (URL search param)', () => {
    setData([group({})])
    render(<OutstandingIssuesTable q="acq_02" />)
    expect(screen.getByDisplayValue('acq_02')).toBeInTheDocument()
  })
})
