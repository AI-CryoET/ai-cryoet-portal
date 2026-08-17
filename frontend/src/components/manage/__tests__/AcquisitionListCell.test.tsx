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

import { AcquisitionListCell } from '../issueCells';

describe('AcquisitionListCell', () => {
  it('renders a dash when no acquisitions are affected', () => {
    render(
      <AcquisitionListCell
        row={{
          sample_id: 'samp1',
          md_run_id: null,
          file_kind: 'sample_toml',
          acquisitions: [],
          message: 'm'
        }}
      />
    );
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('lists each acquisition with a link, copy button, and edit icon when authorable', () => {
    render(
      <AcquisitionListCell
        row={{
          sample_id: 'samp1',
          md_run_id: null,
          file_kind: 'acquisition_toml',
          acquisitions: [
            {
              acquisition_id: 'acq1',
              acquisition_path: '/data/samp1/acq1',
              file_kind: 'acquisition_toml',
              messages: ["id 'acq1'"]
            }
          ],
          message: "id 'acq1'"
        }}
      />
    );
    const link = screen.getByText('acq1').closest('a');
    expect(link).toHaveAttribute('data-to', '/acquisitions/$acquisitionId');
    expect(screen.getByLabelText('Copy path')).toBeTruthy();
    const editLink = screen.getByLabelText('Edit metadata');
    expect(editLink).toHaveAttribute('data-to', '/manage/author');
  });

  it('omits the edit icon for non-authorable file kinds', () => {
    render(
      <AcquisitionListCell
        row={{
          sample_id: 'samp1',
          md_run_id: null,
          file_kind: 'mdoc',
          acquisitions: [
            {
              acquisition_id: 'acq1',
              acquisition_path: null,
              file_kind: 'mdoc',
              messages: ['bad mdoc']
            }
          ],
          message: 'bad mdoc'
        }}
      />
    );
    expect(screen.queryByLabelText('Edit metadata')).toBeNull();
    expect(screen.queryByLabelText('Copy path')).toBeNull();
  });
});
