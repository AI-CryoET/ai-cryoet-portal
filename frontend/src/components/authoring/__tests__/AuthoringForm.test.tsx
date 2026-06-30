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

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
