/**
 * Unit tests for the manage warnings table edit-link wiring (issue 07):
 * a row flagging a sample.toml / acquisition.toml links to the matching
 * authoring form, auto-loading that entity by id.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { IssueGroup } from '~/types'

// Expose the router link target as data-attributes so we can assert it without
// a router context.
vi.mock('~/components/CustomLink', () => ({
  CustomLink: ({
    children,
    to,
    search,
    params,
  }: {
    children: React.ReactNode
    to?: string
    search?: Record<string, unknown>
    params?: Record<string, unknown>
  }) => (
    <a
      href="#"
      data-to={to}
      data-search={JSON.stringify(search)}
      data-params={JSON.stringify(params)}
    >
      {children}
    </a>
  ),
}))

import { FileCell, authorLinkFor } from '../issueCells'

function group(overrides: Partial<IssueGroup>): IssueGroup {
  return {
    scope: 'sample',
    sample_id: 'samp1',
    acquisition_id: null,
    file_kind: 'sample_toml',
    file_path: '/data/samp1/sample.toml',
    severity: 'error',
    issues: [{ category: 'missing_field', message: 'missing project' }],
    first_seen_at: 1,
    last_seen_at: 1,
    last_seen_run_id: 'r',
    latest_run_id: 'r',
    latest_scan_at: 1,
    ...overrides,
  }
}

describe('authorLinkFor', () => {
  it('links a sample.toml row to /author/sample?id=', () => {
    expect(authorLinkFor(group({}))).toEqual({
      to: '/author/sample',
      search: { id: 'samp1' },
    })
  })

  it('links an acquisition.toml row to /author/acquisition with composite id', () => {
    expect(
      authorLinkFor(
        group({
          scope: 'acquisition',
          file_kind: 'acquisition_toml',
          acquisition_id: 'Pos1',
        }),
      ),
    ).toEqual({
      to: '/author/acquisition',
      search: { id: 'Pos1', sampleId: 'samp1' },
    })
  })

  it('returns null for non-authorable kinds (mdoc, run-scope, missing ids)', () => {
    expect(authorLinkFor(group({ file_kind: 'mdoc' }))).toBeNull()
    expect(
      authorLinkFor(group({ scope: 'run', sample_id: null, file_kind: 'filesystem' })),
    ).toBeNull()
    // acquisition_toml without an acquisition id can't resolve the file.
    expect(
      authorLinkFor(group({ file_kind: 'acquisition_toml', acquisition_id: null })),
    ).toBeNull()
  })
})

describe('FileCell edit link', () => {
  it('makes the file-kind chip an edit link for a sample.toml row', () => {
    render(<FileCell group={group({})} />)
    const link = screen.getByText('sample_toml').closest('a')
    expect(link).not.toBeNull()
    expect(link).toHaveAttribute('data-to', '/author/sample')
    expect(link).toHaveAttribute('data-search', JSON.stringify({ id: 'samp1' }))
  })

  it('does not link a non-authorable file kind', () => {
    render(<FileCell group={group({ file_kind: 'mdoc', file_path: null })} />)
    expect(screen.getByText('mdoc').closest('a')).toBeNull()
  })
})
