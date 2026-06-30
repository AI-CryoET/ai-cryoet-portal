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
})
