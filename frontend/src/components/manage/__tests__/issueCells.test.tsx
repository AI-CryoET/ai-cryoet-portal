/**
 * Unit tests for the manage warnings table edit-link wiring (issue 07):
 * a row flagging a sample.toml / acquisition.toml links to the matching
 * authoring form, auto-loading that entity by id. Also covers the
 * columns-redesign cells: SampleCell's icon fold-in, and WarningTypeCell's
 * wrap-then-clamp treatment (no more chip/tooltip).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { IssueGroup } from '~/types';

// Expose the router link target as data-attributes so we can assert it without
// a router context.
vi.mock('~/components/CustomLink', () => ({
  CustomLink: ({
    children,
    to,
    search,
    params
  }: {
    children: React.ReactNode;
    to?: string;
    search?: Record<string, unknown>;
    params?: Record<string, unknown>;
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
  IconButtonLink: ({
    children,
    to,
    search,
    'aria-label': ariaLabel
  }: {
    children: React.ReactNode;
    to?: string;
    search?: Record<string, unknown>;
    'aria-label'?: string;
  }) => (
    <a
      aria-label={ariaLabel}
      data-to={to}
      data-search={JSON.stringify(search)}
      href="#"
    >
      {children}
    </a>
  )
}));

import { SampleCell, WarningTypeCell, authorLinkFor } from '../issueCells';

function group(overrides: Partial<IssueGroup>): IssueGroup {
  return {
    scope: 'sample',
    sample_id: 'samp1',
    acquisition_id: null,
    md_run_id: null,
    file_kind: 'sample_toml',
    file_path: '/data/samp1/sample.toml',
    severity: 'error',
    issues: [{ category: 'missing_field', message: 'missing project' }],
    first_seen_at: 1,
    last_seen_at: 1,
    last_seen_run_id: 'r',
    latest_run_id: 'r',
    latest_scan_at: 1,
    ...overrides
  };
}

describe('authorLinkFor', () => {
  it('links a sample.toml row to /manage/author on the sample tab', () => {
    expect(authorLinkFor(group({}))).toEqual({
      to: '/manage/author',
      search: { tab: 'sample', id: 'samp1' }
    });
  });

  it('links an acquisition.toml row to /manage/author with the composite id + tab', () => {
    expect(
      authorLinkFor(
        group({
          scope: 'acquisition',
          file_kind: 'acquisition_toml',
          acquisition_id: 'Pos1'
        })
      )
    ).toEqual({
      to: '/manage/author',
      search: { tab: 'acquisition', id: 'Pos1', sampleId: 'samp1' }
    });
  });

  it('links an md_run.toml row to /manage/author on the md_run tab', () => {
    expect(
      authorLinkFor(group({ file_kind: 'md_run_toml', md_run_id: 'run_a' }))
    ).toEqual({
      to: '/manage/author',
      search: { tab: 'md_run', id: 'run_a' }
    });
  });

  it('returns null for non-authorable kinds (mdoc, run-scope, missing ids)', () => {
    expect(authorLinkFor(group({ file_kind: 'mdoc' }))).toBeNull();
    expect(
      authorLinkFor(
        group({ scope: 'run', sample_id: null, file_kind: 'filesystem' })
      )
    ).toBeNull();
    // acquisition_toml without an acquisition id can't resolve the file.
    expect(
      authorLinkFor(
        group({ file_kind: 'acquisition_toml', acquisition_id: null })
      )
    ).toBeNull();
    // md_run_toml without a resolvable run id (e.g. the deprecated legacy
    // block, which names no single run) can't resolve either.
    expect(
      authorLinkFor(group({ file_kind: 'md_run_toml', md_run_id: null }))
    ).toBeNull();
  });
});

describe('SampleCell', () => {
  it('renders a plain link with no icons for an acquisition-scoped row', () => {
    render(
      <SampleCell
        fileKind="acquisition_toml"
        sampleId="samp1"
        samplePath="/data/samp1"
        showActions={false}
      />
    );
    expect(screen.getByText('samp1')).toBeInTheDocument();
    expect(screen.queryByLabelText('Copy path')).toBeNull();
    expect(screen.queryByLabelText('Edit metadata')).toBeNull();
  });

  it('folds in copy-path + edit-metadata icons for a sample/md_run-scoped row', () => {
    render(
      <SampleCell
        fileKind="sample_toml"
        sampleId="samp1"
        samplePath="/data/samp1"
        showActions
      />
    );
    expect(screen.getByLabelText('Copy path')).toBeInTheDocument();
    const editLink = screen.getByLabelText('Edit metadata');
    expect(editLink).toHaveAttribute('data-to', '/manage/author');
  });

  it('omits the edit icon when the file kind has no authoring form', () => {
    render(
      <SampleCell
        fileKind="mdoc"
        sampleId="samp1"
        samplePath="/data/samp1"
        showActions
      />
    );
    expect(screen.queryByLabelText('Edit metadata')).toBeNull();
  });

  it('shows a message icon for a sample/md_run-scoped row', () => {
    render(
      <SampleCell
        fileKind="sample_toml"
        message="something went wrong"
        sampleId="samp1"
        samplePath="/data/samp1"
        showActions
      />
    );
    expect(screen.getByLabelText('View message')).toBeInTheDocument();
  });

  it('omits the message icon for an acquisition-scoped row', () => {
    render(
      <SampleCell
        fileKind="acquisition_toml"
        message="something went wrong"
        sampleId="samp1"
        samplePath="/data/samp1"
        showActions={false}
      />
    );
    expect(screen.queryByLabelText('View message')).toBeNull();
  });
});

describe('WarningTypeCell', () => {
  it('renders the category as plain wrapped text, not a chip', () => {
    render(<WarningTypeCell category="undeclared_annotation_folder" />);
    expect(
      screen.getByText('undeclared annotation folder')
    ).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });
});
