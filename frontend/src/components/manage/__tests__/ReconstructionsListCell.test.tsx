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

import { ReconstructionsListCell } from '../issueCells';
import type { AffectedAcquisition } from '../groupSampleWarnings';

function acquisition(
  overrides: Partial<AffectedAcquisition>
): AffectedAcquisition {
  return {
    acquisition_id: 'acq1',
    acquisition_path: '/data/samp1/acq1',
    file_kind: 'acquisition_toml',
    messages: ['m'],
    reconstructions: [],
    ...overrides
  };
}

describe('ReconstructionsListCell', () => {
  it('renders a dash for zero-acquisition (sample-scoped) rows', () => {
    render(
      <ReconstructionsListCell row={{ sample_id: 'samp1', acquisitions: [] }} />
    );
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('renders a dash inside the band when an acquisition has zero reconstructions', () => {
    render(
      <ReconstructionsListCell
        row={{
          sample_id: 'samp1',
          acquisitions: [acquisition({})]
        }}
      />
    );
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('renders a plain-text name, copy-path icon, and edit-metadata link for a reconstruction', () => {
    render(
      <ReconstructionsListCell
        row={{
          sample_id: 'samp1',
          acquisitions: [
            acquisition({
              reconstructions: [
                {
                  reconstruction_alignment_id: 'grp1',
                  acquisition_id: 'acq1',
                  messages: ["group 'grp1' undeclared"]
                }
              ]
            })
          ]
        }}
      />
    );
    expect(screen.getByText('grp1')).toBeTruthy();
    // Plain text, not a link.
    expect(screen.getByText('grp1').closest('a')).toBeNull();
    expect(screen.getByLabelText('Copy path')).toBeTruthy();
    const editLink = screen.getByLabelText('Edit metadata');
    expect(editLink).toHaveAttribute('data-to', '/manage/author');
    expect(editLink).toHaveAttribute(
      'data-search',
      JSON.stringify({
        tab: 'reconstruction',
        id: 'grp1',
        sampleId: 'samp1',
        acquisitionId: 'acq1'
      })
    );
  });

  it('skips the copy-path icon when acquisition_path is null', () => {
    render(
      <ReconstructionsListCell
        row={{
          sample_id: 'samp1',
          acquisitions: [
            acquisition({
              acquisition_path: null,
              reconstructions: [
                {
                  reconstruction_alignment_id: 'grp1',
                  acquisition_id: 'acq1',
                  messages: ['m']
                }
              ]
            })
          ]
        }}
      />
    );
    expect(screen.queryByLabelText('Copy path')).toBeNull();
  });

  it('shows a message icon for every reconstruction', () => {
    render(
      <ReconstructionsListCell
        row={{
          sample_id: 'samp1',
          acquisitions: [
            acquisition({
              reconstructions: [
                {
                  reconstruction_alignment_id: 'grp1',
                  acquisition_id: 'acq1',
                  messages: ['message one']
                },
                {
                  reconstruction_alignment_id: 'grp2',
                  acquisition_id: 'acq1',
                  messages: ['message two']
                }
              ]
            })
          ]
        }}
      />
    );
    expect(screen.getAllByLabelText('View message')).toHaveLength(2);
  });

  it('renders every reconstruction across multiple acquisitions with mixed counts', () => {
    render(
      <ReconstructionsListCell
        row={{
          sample_id: 'samp1',
          acquisitions: [
            acquisition({
              acquisition_id: 'acq1',
              acquisition_path: '/data/samp1/acq1',
              reconstructions: [
                {
                  reconstruction_alignment_id: 'grp1',
                  acquisition_id: 'acq1',
                  messages: ['m']
                }
              ]
            }),
            acquisition({
              acquisition_id: 'acq2',
              acquisition_path: '/data/samp1/acq2',
              reconstructions: []
            })
          ]
        }}
      />
    );
    expect(screen.getByText('grp1')).toBeTruthy();
    expect(screen.getByText('—')).toBeTruthy();
  });
});
