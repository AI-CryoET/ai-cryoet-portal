/**
 * Tests for the sample-centric warnings layout: `flattenBand` row ordering +
 * acquisition-group shading, and the rendered inner table (scope icons +
 * per-level edit links). Grouping is covered in groupSampleWarnings.test.ts.
 */
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

import { flattenBand, type SampleBand } from '../groupSampleWarnings';
import { SampleWarningBands } from '../SampleWarningBands';

function band(overrides: Partial<SampleBand>): SampleBand {
  return {
    key: 'samp1',
    sample_id: 'samp1',
    sample_path: '/data/samp1',
    file_kind: 'sample_toml',
    severity: 'error',
    hasSampleEdit: false,
    sampleEntries: [],
    acquisitions: [],
    ...overrides
  };
}

function acq(overrides: Record<string, unknown>) {
  return {
    acquisition_id: 'acq1',
    acquisition_path: '/data/samp1/acq1',
    file_kind: 'acquisition_toml',
    messages: [],
    reconstructions: [],
    reEvaluated: true,
    stillPresentAt: 20,
    resolved_at: null,
    ...overrides
  } as SampleBand['acquisitions'][number];
}

function recon(id: string, message: string) {
  return {
    reconstruction_alignment_id: id,
    acquisition_id: 'acq1',
    messages: [{ text: message, scope: 'reconstruction' as const }],
    reEvaluated: true,
    stillPresentAt: 20,
    resolved_at: null
  };
}

describe('flattenBand', () => {
  it('orders sample entries before acquisitions', () => {
    const rows = flattenBand(
      band({
        sampleEntries: [
          {
            md_run_id: null,
            file_kind: 'sample_toml',
            messages: [{ text: 's', scope: 'sample' }],
            reEvaluated: true,
            stillPresentAt: 20,
            resolved_at: null
          }
        ],
        acquisitions: [acq({ messages: [{ text: 'a', scope: 'acquisition' }] })]
      })
    );
    expect(rows.map(r => r.messages[0].scope)).toEqual([
      'sample',
      'acquisition'
    ]);
  });

  it('names once and shares one shade across an acquisition with multiple reconstructions', () => {
    const rows = flattenBand(
      band({
        acquisitions: [
          acq({
            reconstructions: [recon('grp1', 'first'), recon('grp2', 'second')]
          })
        ]
      })
    );
    expect(rows).toHaveLength(2);
    expect(rows[0].shaded).toBe(rows[1].shaded);
    expect(rows[0].showAcqLabel).toBe(true);
    // Name is a group header only — reconstruction owns the message, so the
    // acquisition gets no copy/edit actions.
    expect(rows[0].acqActions).toBe(false);
    expect(rows[1].showAcqLabel).toBe(false);
  });

  it('alternates shading acquisition to acquisition, regardless of group size', () => {
    const rows = flattenBand(
      band({
        acquisitions: [
          acq({
            acquisition_id: 'acq1',
            reconstructions: [recon('grp1', 'first'), recon('grp2', 'second')]
          }),
          acq({
            acquisition_id: 'acq2',
            messages: [{ text: 'solo', scope: 'acquisition' }]
          })
        ]
      })
    );
    expect(rows).toHaveLength(3);
    expect(rows[0].shaded).toBe(false);
    expect(rows[1].shaded).toBe(false);
    expect(rows[2].shaded).toBe(true);
  });
});

describe('SampleWarningBands', () => {
  it('renders scope icons and a reconstruction edit link', () => {
    render(
      <SampleWarningBands
        bands={[
          band({
            acquisitions: [acq({ reconstructions: [recon('grp1', 'boom')] })]
          })
        ]}
        variant="outstanding"
      />
    );
    expect(screen.getByText('boom')).toBeInTheDocument();
    expect(
      screen.getByLabelText('Reconstruction-level message')
    ).toBeInTheDocument();
    const edit = screen.getByLabelText('Edit metadata');
    expect(JSON.parse(edit.getAttribute('data-search') ?? '{}').tab).toBe(
      'reconstruction'
    );
  });
});
