/**
 * Reconstructions are shown one block per 3D-alignment group: a subheader, the
 * group's tomograms, then the group's annotations. Both tomograms and
 * annotations carry `reconstruction_alignment_id`, so each group's annotation
 * table must list only its own group's annotations — never the acquisition's
 * whole list, which would attribute annotations to the wrong group.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AcquisitionOut } from '~/types'
import { TomogramsAnnotationsTable } from '../TomogramsAnnotationsTable'

vi.mock('../../../utils/api', () => ({ apiFetch: vi.fn() }))

// Two alignment groups, one tomogram and one annotation each.
const acquisition: AcquisitionOut = {
  acquisition_id: 'acq1',
  raw_tomograms: [],
  post_processed_tomograms: [
    { tomogram_id: 'denoised', reconstruction_alignment_id: 'align1' },
    { tomogram_id: 'denoised', reconstruction_alignment_id: 'align2' },
  ],
  annotations: [
    {
      annotation_id: 'ann_one',
      reconstruction_alignment_id: 'align1',
      type: 'membrane',
      derived_from: 'denoised',
      files: [],
    },
    { annotation_id: 'ann_two', reconstruction_alignment_id: 'align2', files: [] },
  ],
  tilt_series: [],
  reconstruction_alignment: [],
} as AcquisitionOut

function renderTable() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <TomogramsAnnotationsTable sampleId="sample_a" acquisition={acquisition} />
    </QueryClientProvider>,
  )
}

describe('TomogramsAnnotationsTable — annotations are scoped to their group', () => {
  it('each group annotation table lists only its own annotation', () => {
    renderTable()
    // One annotation table per group, in group order (align1 then align2).
    const [first, second] = screen.getAllByRole('table', { name: 'annotations' })
    expect(within(first).getByText('ann_one')).toBeInTheDocument()
    expect(within(first).queryByText('ann_two')).not.toBeInTheDocument()
    expect(within(second).getByText('ann_two')).toBeInTheDocument()
    expect(within(second).queryByText('ann_one')).not.toBeInTheDocument()
  })

  it('defaults to all open and the collapse-all button toggles every group', async () => {
    renderTable()
    // Default: each group open, so its toggle offers to collapse it.
    expect(screen.getByLabelText('Collapse align1')).toBeInTheDocument()
    expect(screen.getByLabelText('Collapse align2')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Collapse all' }))

    // Now every group is collapsed, so each toggle offers to expand it, and the
    // global link flips to "Expand all".
    expect(screen.getByLabelText('Expand align1')).toBeInTheDocument()
    expect(screen.getByLabelText('Expand align2')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Expand all' }),
    ).toBeInTheDocument()
  })

  it('shows the derived-from tomogram under the annotation id', () => {
    renderTable()
    const [first] = screen.getAllByRole('table', { name: 'annotations' })
    expect(within(first).getByText('Derived from:')).toBeInTheDocument()
    // "denoised" appears as the derived-from value in the annotation table.
    expect(
      within(first).getByText((_, el) => el?.textContent === 'Derived from: denoised'),
    ).toBeInTheDocument()
  })
})
