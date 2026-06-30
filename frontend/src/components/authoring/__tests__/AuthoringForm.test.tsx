/**
 * Renderer test for AuthoringForm (md_run). Asserts: the authored md_run
 * fields render from the registry; the placement hint reflects the entered id;
 * a 422 from the endpoint surfaces inline on the right field.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthoringForm } from '../AuthoringForm'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AuthoringForm (md_run)', () => {
  it('renders the authored md_run fields from the registry', () => {
    render(<AuthoringForm form="md_run" />)
    expect(screen.getByLabelText(/Run id/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Seed/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Timestep/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Force field version/)).toBeInTheDocument()
  })

  it('placement hint reflects the entered id', async () => {
    render(<AuthoringForm form="md_run" />)
    await userEvent.type(screen.getByLabelText(/Run id/), 'run01')
    expect(screen.getByText('MdRuns/run01/md_run.toml')).toBeInTheDocument()
  })

  it('shows a backend 422 error inline on the field', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          errors: [{ loc: ['seed'], msg: 'must be an integer', type: 'int_parsing' }],
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    render(<AuthoringForm form="md_run" />)
    // Valid id so the structural check passes and we reach the backend.
    await userEvent.type(screen.getByLabelText(/Run id/), 'run01')
    await userEvent.click(screen.getByRole('button', { name: /Download/ }))
    await waitFor(() =>
      expect(screen.getByText('must be an integer')).toBeInTheDocument(),
    )
  })

  it('blocks submit with a structural error when the id is empty', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<AuthoringForm form="md_run" />)
    await userEvent.click(screen.getByRole('button', { name: /Download/ }))
    expect(screen.getByText('Required')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('loading by id populates the form and shows the staleness warning', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ fields: { md_run_id: 'run01', seed: 42 } }),
    )
    render(<AuthoringForm form="md_run" />)
    await userEvent.type(screen.getByLabelText(/Load from portal by id/), 'run01')
    await userEvent.click(screen.getByRole('button', { name: /^Load$/ }))
    await waitFor(() =>
      expect(screen.getByLabelText(/Run id/)).toHaveValue('run01'),
    )
    expect(screen.getByLabelText(/Seed/)).toHaveValue(42)
    expect(screen.getByText(/may lag the on-disk file/)).toBeInTheDocument()
  })

  it('renders an uploaded scalar extra as an editable custom-field row', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ fields: { seed: 1, custom_note: 'keep me' } }),
    )
    render(<AuthoringForm form="md_run" />)
    const file = new File(['seed = 1\ncustom_note = "keep me"\n'], 'md_run.toml')
    // The hidden file input sits inside the "Upload" label button.
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement
    await userEvent.upload(input, file)
    await waitFor(() =>
      expect(screen.getByDisplayValue('custom_note')).toBeInTheDocument(),
    )
    expect(screen.getByDisplayValue('keep me')).toBeInTheDocument()
  })

  it('adds a custom field row on demand', async () => {
    render(<AuthoringForm form="md_run" />)
    await userEvent.click(
      screen.getByRole('button', { name: /Add custom field/ }),
    )
    expect(screen.getByLabelText(/^Key$/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Value$/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Type$/)).toBeInTheDocument()
  })
})

describe('AuthoringForm (acquisition)', () => {
  it('renders [acquisition] fields and a constrained 1–5 quality dropdown', () => {
    render(<AuthoringForm form="acquisition" />)
    expect(screen.getByLabelText(/Acquisition id/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Resolution/)).toBeInTheDocument()
    // Quality is a select limited to 1–5 (can't enter an out-of-range value).
    const quality = screen.getByLabelText(/Quality/)
    expect(quality).toBeInTheDocument()
  })

  it('gates [md_source] on the simulation data source', async () => {
    render(<AuthoringForm form="acquisition" />)
    // Experimental (default): no MD source field.
    expect(screen.queryByLabelText(/MD run id/)).not.toBeInTheDocument()
    // Switch to simulation → md_source appears.
    const select = screen.getByLabelText(/Data source/)
    await userEvent.click(select)
    await userEvent.click(screen.getByRole('option', { name: /Simulation/ }))
    expect(screen.getByLabelText(/MD run id/)).toBeInTheDocument()
  })

  it('adds and removes tilt-series entries', async () => {
    render(<AuthoringForm form="acquisition" />)
    expect(screen.queryByLabelText(/Tilt series id/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Add tilt series/ }))
    expect(screen.getByLabelText(/Tilt series id/)).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: /Remove Tilt series entry/ }),
    )
    expect(screen.queryByLabelText(/Tilt series id/)).not.toBeInTheDocument()
  })

  it("derived_from offers 'Frames' and another in-form tilt-series id", async () => {
    render(<AuthoringForm form="acquisition" />)
    const add = screen.getByRole('button', { name: /Add tilt series/ })
    await userEvent.click(add)
    await userEvent.click(add)
    // Give the first entry an id so it becomes a derived_from option.
    const ids = screen.getAllByLabelText(/Tilt series id/)
    await userEvent.type(ids[0], 'ts_raw')
    // Open the second entry's derived_from dropdown.
    const derivedFroms = screen.getAllByLabelText(/Derived from/)
    await userEvent.click(derivedFroms[1])
    expect(screen.getByRole('option', { name: 'Frames' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'ts_raw' })).toBeInTheDocument()
  })

  it('shows a backend 422 inline on the nested quality field', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          errors: [
            {
              loc: ['acquisition', 'acquisition_quality'],
              msg: 'Input should be less than or equal to 5',
              type: 'less_than_equal',
            },
          ],
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    render(<AuthoringForm form="acquisition" />)
    await userEvent.type(screen.getByLabelText(/Acquisition id/), 'Pos1')
    await userEvent.click(screen.getByRole('button', { name: /Download/ }))
    await waitFor(() =>
      expect(
        screen.getByText('Input should be less than or equal to 5'),
      ).toBeInTheDocument(),
    )
  })

  it("annotation target_tomogram offers in-form tomogram ids", async () => {
    render(<AuthoringForm form="acquisition" />)
    // Author a raw tomogram id, then add an annotation.
    await userEvent.type(screen.getByLabelText(/Tomogram id/), 'tomo_raw')
    await userEvent.click(screen.getByRole('button', { name: /Add annotations/i }))
    // The annotation's target dropdown is sourced from the tomogram namespace.
    await userEvent.click(screen.getByLabelText(/Target tomogram/))
    expect(
      screen.getByRole('option', { name: 'tomo_raw' }),
    ).toBeInTheDocument()
  })

  it('renders loaded processing-log entries read-only (immutability)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({
        fields: {
          acquisition: { acquisition_id: 'Pos1' },
          tilt_series: [{ id: 'ts_raw', derived_from: 'Frames' }],
          raw_tomogram: { id: 'tomo_raw', software: 'AreTomo' },
        },
      }),
    )
    render(
      <AuthoringForm form="acquisition" initialId="Pos1" initialSampleId="samp1" />,
    )
    // Loaded tilt-series + raw-tomogram fields are disabled; no remove button.
    await waitFor(() =>
      expect(screen.getByLabelText(/Tilt series id/)).toBeDisabled(),
    )
    expect(screen.getByLabelText(/^Software$/)).toBeDisabled()
    expect(
      screen.queryByRole('button', { name: /Remove Tilt series entry/ }),
    ).not.toBeInTheDocument()
    // [acquisition] stays editable.
    expect(screen.getByLabelText(/Acquisition id/)).not.toBeDisabled()
  })

  it('auto-loads the acquisition from the edit-link search params', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({
        fields: {
          acquisition: { acquisition_id: 'Pos1', resolution: 3.4 },
          md_source: { md_run_id: 'run01' },
        },
      }),
    )
    render(
      <AuthoringForm form="acquisition" initialId="Pos1" initialSampleId="samp1" />,
    )
    await waitFor(() =>
      expect(screen.getByLabelText(/Acquisition id/)).toHaveValue('Pos1'),
    )
    expect(screen.getByLabelText(/Resolution/)).toHaveValue(3.4)
    // md_source present in the file → simulation inferred → field shown.
    expect(screen.getByLabelText(/MD run id/)).toBeInTheDocument()
    expect(screen.getByText(/may lag the on-disk file/)).toBeInTheDocument()
  })
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
