/**
 * The annotations detail panel is scoped to the row's 3D-alignment group.
 *
 * An acquisition can hold several Reconstructions/{group}/ directories. Before
 * the group became part of the storage key, an acquisition had one group and the
 * panel could show `acquisition.annotations` wholesale. Now that it can hold
 * several, showing the whole list under a header that names one group tells the
 * user the wrong group.
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
    { annotation_id: 'ann_one', reconstruction_alignment_id: 'align1', files: [] },
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

describe('TomogramsAnnotationsTable — annotations are scoped to the row group', () => {
  it('each row panel lists only its own group annotation', async () => {
    renderTable()
    // Expanding mounts the detail panels. Rows are in group order (the API
    // orders by group then id): align1 first, then align2.
    await userEvent.click(screen.getAllByRole('button', { name: /expand/i })[0])
    const [first, second] = screen.getAllByRole('table', { name: 'annotations' })
    expect(within(first).getByText('ann_one')).toBeInTheDocument()
    expect(within(first).queryByText('ann_two')).not.toBeInTheDocument()
    expect(within(second).getByText('ann_two')).toBeInTheDocument()
    expect(within(second).queryByText('ann_one')).not.toBeInTheDocument()
  })

  it('the Annotations count is per group, not per acquisition', () => {
    renderTable()
    // One annotation in each group → every row reads 1, never 2.
    // Last cell of each tomogram row is the Annotations column. Detail-panel
    // rows contribute an empty trailing cell, so drop the blanks.
    const counts = screen
      .getAllByRole('row')
      .map((r) => within(r).queryAllByRole('cell').at(-1)?.textContent)
      .filter(Boolean)
    expect(counts).toEqual(['1', '1'])
  })
})
