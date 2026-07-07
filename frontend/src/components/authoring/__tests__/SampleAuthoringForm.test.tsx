/**
 * Renderer test for the composite sample form. Asserts the section gating
 * reused from the filter model (synapse hides chromatin / non-chromatin
 * disables it; experimental vs simulation gates the experimental-only
 * sections; synapse forces experimental), repeatable [[label]] add/remove,
 * a backend 422 surfacing inline, a contradictory upload warning, and
 * deep-link auto-load.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { AuthoringForm } from '../AuthoringForm'

beforeAll(() => {
  // jsdom has no object-URL impl; the download path calls it on submit.
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock')
  globalThis.URL.revokeObjectURL = vi.fn()
})
afterEach(() => vi.restoreAllMocks())

async function selectProject(name: string) {
  await userEvent.click(screen.getByRole('combobox', { name: /Project/ }))
  await userEvent.click(await screen.findByRole('option', { name }))
}

const EXP_SECTIONS = [
  'Gold-nanoparticle labels',
  'Fiducial AuNP',
  'Freezing / grid prep',
  'Milling',
]

describe('AuthoringForm (sample) gating', () => {
  it('renders the [sample] section with the data-source toggle', () => {
    render(<AuthoringForm form="sample" />)
    expect(screen.getByRole('combobox', { name: /Project/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Experimental' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Simulation' })).toBeInTheDocument()
  })

  it('hides experimental-only sections when simulation is chosen', async () => {
    render(<AuthoringForm form="sample" />)
    for (const t of EXP_SECTIONS) expect(screen.getByText(t)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'Simulation' }))
    for (const t of EXP_SECTIONS) expect(screen.queryByText(t)).not.toBeInTheDocument()
  })

  it('hides chromatin for synapse and forces experimental', async () => {
    render(<AuthoringForm form="sample" />)
    expect(screen.getByText('Chromatin')).toBeInTheDocument()
    await selectProject('synapse')
    expect(screen.queryByText('Chromatin')).not.toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Experimental' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Simulation' })).toBeDisabled()
  })

  it('disables chromatin for a non-chromatin project but keeps it visible', async () => {
    render(<AuthoringForm form="sample" />)
    await selectProject('nanogold')
    expect(screen.getByText('Chromatin')).toBeInTheDocument()
    expect(screen.getByLabelText(/Substrate/)).toBeDisabled()
  })
})

describe('AuthoringForm (sample) repeatable labels', () => {
  it('adds and removes a [[label]] entry', async () => {
    render(<AuthoringForm form="sample" />)
    expect(screen.queryByLabelText(/Label target/)).not.toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: /Add Gold-nanoparticle labels/ }),
    )
    expect(screen.getByLabelText(/Label target/)).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: /Remove Gold-nanoparticle labels/ }),
    )
    expect(screen.queryByLabelText(/Label target/)).not.toBeInTheDocument()
  })
})

describe('AuthoringForm (sample) submit + seed', () => {
  it('surfaces a backend 422 inline on the section field', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          errors: [{ loc: ['sample', 'project'], msg: 'Field required', type: 'missing' }],
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    render(<AuthoringForm form="sample" />)
    await userEvent.click(screen.getByRole('button', { name: /Download sample\.toml/ }))
    await waitFor(() =>
      expect(screen.getByText('Field required')).toBeInTheDocument(),
    )
  })

  it('downloads on a 200 response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('project = "nanogold"\n', {
        status: 200,
        headers: { 'Content-Type': 'application/toml' },
      }),
    )
    render(<AuthoringForm form="sample" />)
    await selectProject('nanogold')
    await userEvent.click(screen.getByRole('button', { name: /Download sample\.toml/ }))
    await waitFor(() =>
      expect(screen.getByText(/Downloaded sample\.toml/)).toBeInTheDocument(),
    )
    expect(globalThis.URL.createObjectURL).toHaveBeenCalled()
  })

  it('warns and stays editable when an uploaded file is contradictory', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ fields: { simulation: {}, freezing: { method: 'HPF' } } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    render(<AuthoringForm form="sample" />)
    const file = new File(['[simulation]\n[freezing]\nmethod="HPF"\n'], 'sample.toml')
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, file)
    await waitFor(() =>
      expect(
        screen.getByText(/both experimental and simulation blocks/),
      ).toBeInTheDocument(),
    )
    // Conflict leaves the arm toggle editable (not locked).
    expect(screen.getByRole('radio', { name: 'Simulation' })).not.toBeDisabled()
  })

  it('auto-loads a sample by id and locks the arm from the record', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          fields: {
            sample: { sample_id: 'samp1', data_source: 'simulation', project: 'chromatin' },
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    render(<AuthoringForm form="sample" loadId="samp1" />)
    await waitFor(() =>
      expect(screen.getByText(/may lag the on-disk file/)).toBeInTheDocument(),
    )
    // data_source from the record -> simulation, locked.
    const sim = screen.getByRole('radio', { name: 'Simulation' })
    expect(sim).toBeChecked()
    expect(sim).toBeDisabled()
    // Placement hint reflects the loaded id.
    expect(screen.getByText('samp1/sample.toml')).toBeInTheDocument()
    // The id itself is pre-filled read-only (ADR-0004 identity guidance).
    expect(screen.getByLabelText(/Sample id/)).toBeDisabled()
  })
})
