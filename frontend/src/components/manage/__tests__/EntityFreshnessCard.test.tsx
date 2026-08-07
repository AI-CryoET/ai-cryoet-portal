/**
 * Component tests for EntityFreshnessCard (Priority 2, plan §5.2 / §6).
 *
 * Focus on the empty / edge states called out in the plan:
 *   - not-yet-scanned entity (status === null) → "has not been scanned yet"
 *   - acquisition with no preview source → "— no preview source found —"
 *   - acquisition never rendered → "never" for thumbnail generated
 *   - a normal acquisition shows its source path + outcome pill
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { EntityFreshnessCard } from '../EntityFreshnessCard';
import type { AcquisitionScanStatus, EntityScanStatus } from '~/types';

const sampleStatus: EntityScanStatus = {
  last_scanned_at: 1_700_000_000,
  last_changed_at: 1_699_000_000,
  last_outcome: 'upserted',
  last_scan_run_id: 'run_1'
};

describe('EntityFreshnessCard — never scanned', () => {
  it('shows the "not scanned yet" empty state for a sample', () => {
    render(<EntityFreshnessCard status={null} kind="sample" />);
    expect(
      screen.getByText('This sample has not been scanned yet.')
    ).toBeInTheDocument();
  });

  it('shows the "not scanned yet" empty state for an acquisition', () => {
    render(<EntityFreshnessCard status={null} kind="acquisition" />);
    expect(
      screen.getByText('This acquisition has not been scanned yet.')
    ).toBeInTheDocument();
  });
});

describe('EntityFreshnessCard — sample with status', () => {
  it('renders the outcome pill and freshness rows', () => {
    render(<EntityFreshnessCard status={sampleStatus} kind="sample" />);
    expect(screen.getByText('updated')).toBeInTheDocument();
    expect(screen.getByText('Last updated')).toBeInTheDocument();
    expect(screen.getByText('Last scanned')).toBeInTheDocument();
    // Thumbnail provenance is acquisition-only.
    expect(screen.queryByText('Thumbnail source file')).not.toBeInTheDocument();
  });
});

describe('EntityFreshnessCard — acquisition thumbnail provenance', () => {
  it('shows "no preview source" when missing_source', () => {
    const status: AcquisitionScanStatus = {
      ...sampleStatus,
      last_outcome: 'skipped',
      thumbnail_path: null,
      thumbnail_source_kind: 'none',
      thumbnail_source_path: null,
      thumbnail_generated_at: null,
      thumbnail_status: 'missing_source'
    };
    render(<EntityFreshnessCard status={status} kind="acquisition" />);
    expect(screen.getByText('— no preview source found —')).toBeInTheDocument();
    expect(screen.getByText('never')).toBeInTheDocument();
  });

  it('shows the source path and a generated timestamp when ok', () => {
    const status: AcquisitionScanStatus = {
      ...sampleStatus,
      thumbnail_path: '/cache/thumb.png',
      thumbnail_source_kind: 'st',
      thumbnail_source_path: '/data/acq_01/series.st',
      thumbnail_generated_at: 1_700_000_500,
      thumbnail_status: 'ok'
    };
    render(<EntityFreshnessCard status={status} kind="acquisition" />);
    expect(screen.getByText('/data/acq_01/series.st')).toBeInTheDocument();
    expect(screen.queryByText('never')).not.toBeInTheDocument();
    expect(
      screen.queryByText('— no preview source found —')
    ).not.toBeInTheDocument();
  });
});
