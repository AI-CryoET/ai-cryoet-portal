import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
      data-params={JSON.stringify(params)}
      data-search={JSON.stringify(search)}
      data-to={to}
      href="#"
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
      data-search={JSON.stringify(search)}
      data-to={to}
      href="#"
    >
      {children}
    </a>
  )
}));

import { AffectedTable, type AffectedRow } from '../issueCells';
import type { AffectedAcquisition } from '../groupSampleWarnings';

function acquisition(
  overrides: Partial<AffectedAcquisition>
): AffectedAcquisition {
  return {
    acquisition_id: 'acq1',
    acquisition_path: '/data/samp1/acq1',
    file_kind: 'acquisition_toml',
    messages: [],
    reconstructions: [],
    ...overrides
  };
}

function row(overrides: Partial<AffectedRow>): AffectedRow {
  return {
    sample_id: 'samp1',
    md_run_id: null,
    file_kind: 'acquisition_toml',
    message: '',
    acquisitions: [],
    ...overrides
  };
}

function renderTable(r: AffectedRow) {
  return render(
    <AffectedTable columnSizing={{}} onColumnSizingChange={() => {}} row={r} />
  );
}

describe('AffectedTable', () => {
  it('shows the row-level message for a sample/run-scoped row (no acquisitions)', () => {
    renderTable(row({ file_kind: 'sample_toml', message: 'boom' }));
    expect(screen.getByText('boom')).toBeTruthy();
    // Both entity columns render a dash (nothing to list).
    expect(screen.getAllByText('—')).toHaveLength(2);
  });

  it('shows an acquisition-owned message with the acquisition actions', () => {
    renderTable(
      row({ acquisitions: [acquisition({ messages: ['acq message'] })] })
    );
    expect(screen.getByText('acq1')).toBeTruthy();
    expect(screen.getByText('acq message')).toBeTruthy();
    expect(screen.getByLabelText('Copy path')).toBeTruthy();
    // The one edit link is the acquisition's.
    const edit = screen.getByLabelText('Edit metadata');
    expect(JSON.parse(edit.getAttribute('data-search') ?? '{}').tab).toBe(
      'acquisition'
    );
  });

  it('puts a reconstruction-owned message on the reconstruction and drops the acquisition actions', () => {
    renderTable(
      row({
        acquisitions: [
          acquisition({
            messages: [],
            reconstructions: [
              {
                reconstruction_alignment_id: 'grp1',
                acquisition_id: 'acq1',
                messages: ['grp1 undeclared']
              }
            ]
          })
        ]
      })
    );
    // Acquisition link stays (grouping context)...
    expect(screen.getByText('acq1')).toBeTruthy();
    expect(screen.getByText('grp1')).toBeTruthy();
    expect(screen.getByText('grp1 undeclared')).toBeTruthy();
    // ...but the only edit link is the reconstruction's — the acquisition's
    // actions are gone (the fix lives on the reconstruction).
    const edits = screen.getAllByLabelText('Edit metadata');
    expect(edits).toHaveLength(1);
    expect(JSON.parse(edits[0].getAttribute('data-search') ?? '{}').tab).toBe(
      'reconstruction'
    );
  });

  it('renders one row per reconstruction, each lined up with its own message', () => {
    renderTable(
      row({
        acquisitions: [
          acquisition({
            reconstructions: [
              {
                reconstruction_alignment_id: 'grp1',
                acquisition_id: 'acq1',
                messages: ['first']
              },
              {
                reconstruction_alignment_id: 'grp2',
                acquisition_id: 'acq1',
                messages: ['second']
              }
            ]
          })
        ]
      })
    );
    expect(screen.getByText('first')).toBeTruthy();
    expect(screen.getByText('second')).toBeTruthy();
    // Acquisition label shows once (only on its first reconstruction row).
    expect(screen.getAllByText('acq1')).toHaveLength(1);
    expect(screen.getAllByText('•')).toHaveLength(2);
  });
});
