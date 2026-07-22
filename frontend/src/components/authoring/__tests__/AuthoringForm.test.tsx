/**
 * Renderer test for AuthoringForm (md_run). Asserts: the authored md_run
 * fields render from the registry; the directory-identity id is NOT a field
 * (the save-location hint covers it); a 422 from the endpoint surfaces inline
 * on the right field.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthoringForm } from '../AuthoringForm'
import { ForbiddenError } from '~/lib/fileglancerClient'

// Mock the vendored Fileglancer client: connect()/writeFile()/connectSilently()
// are shared vi.fns (accessed via `fg`), and the error classes are real-enough
// for describeSaveError's instanceof mapping.
const fg = vi.hoisted(() => ({
  connect: vi.fn(),
  readFile: vi.fn(),
  writeFile: vi.fn(),
  connectSilently: vi.fn(),
}))
vi.mock('~/lib/fileglancerClient', () => {
  class FileglancerError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.status = status
    }
  }
  class AuthRequiredError extends FileglancerError {
    constructor(message = 'Authentication required') {
      super(message, 401)
      this.name = 'AuthRequiredError'
    }
  }
  class ForbiddenError extends FileglancerError {
    constructor(message = 'Forbidden') {
      super(message, 403)
      this.name = 'ForbiddenError'
    }
  }
  class ConflictError extends FileglancerError {
    constructor(message = 'Precondition failed') {
      super(message, 412)
      this.name = 'ConflictError'
    }
  }
  class FileglancerClient {
    connect = fg.connect
    readFile = fg.readFile
    writeFile = fg.writeFile
    connectSilently = fg.connectSilently
  }
  return {
    default: FileglancerClient,
    FileglancerClient,
    FileglancerError,
    AuthRequiredError,
    ForbiddenError,
    ConflictError,
  }
})

beforeEach(() => {
  fg.connect.mockReset().mockResolvedValue({ authenticated: true })
  // Readback for the save-path optimistic-concurrency check (etag → If-Match).
  fg.readFile
    .mockReset()
    .mockResolvedValue(new Response('', { headers: { etag: 'W/"seed"' } }))
  fg.writeFile.mockReset().mockResolvedValue({ bytes_written: 10 })
  fg.connectSilently.mockReset().mockResolvedValue(false)
})

afterEach(() => {
  vi.restoreAllMocks()
})

// Route the shared fetch mock by URL: portal load (GET .../load/...), upload
// parse (POST .../parse), and the validate POST (POST /api/toml/{form}).
function routeFetch(opts: {
  load?: {
    fields: Record<string, unknown>
    path: string | null
    source?: 'disk' | 'catalog'
    baseline?: string | null
  }
  parse?: { fields: Record<string, unknown> }
  post?: () => Response
}) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(((
    input: RequestInfo | URL,
  ) => {
    const url = String(input)
    if (url.includes('/parse')) {
      return Promise.resolve(jsonResponse(opts.parse ?? { fields: {} }))
    }
    if (url.includes('/load/')) {
      return Promise.resolve(jsonResponse(opts.load ?? { fields: {}, path: null }))
    }
    const post = opts.post?.() ??
      new Response('seed = 42\n', {
        status: 200,
        headers: { 'Content-Type': 'application/toml' },
      })
    return Promise.resolve(post)
  }) as typeof fetch)
}

describe('AuthoringForm (md_run)', () => {
  it('renders the authored md_run fields from the registry', () => {
    render(<AuthoringForm form="md_run" />)
    // The directory-identity id is not a form field.
    expect(screen.queryByLabelText(/Run id/)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/Seed/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Timestep/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Force field version/)).toBeInTheDocument()
  })

  it('shows the save-location hint with the id placeholder for a new file', () => {
    render(<AuthoringForm form="md_run" />)
    expect(
      screen.getByText('MdRuns/{md_run_id}/md_run.toml'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Save the downloaded file inside/),
    ).toBeInTheDocument()
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
    await userEvent.click(screen.getByRole('button', { name: /Download/ }))
    await waitFor(() =>
      expect(screen.getByText('must be an integer')).toBeInTheDocument(),
    )
  })

  it('auto-loads the run from the edit-link search param (deep link)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ fields: { md_run_id: 'run01', seed: 42 } }),
    )
    render(<AuthoringForm form="md_run" initialId="run01" />)
    await waitFor(() =>
      expect(screen.getByLabelText(/Seed/)).toHaveValue(42),
    )
    expect(screen.getByText(/may lag the on-disk file/)).toBeInTheDocument()
    // Loaded → the concrete save path with the known id.
    expect(screen.getByText('MdRuns/run01/md_run.toml')).toBeInTheDocument()
  })

  it('has no load-from-portal-by-id field (removed for md_run)', () => {
    render(<AuthoringForm form="md_run" />)
    expect(
      screen.queryByLabelText(/Load from portal by id/),
    ).not.toBeInTheDocument()
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
    // The directory-identity id is not a form field.
    expect(screen.queryByLabelText(/Acquisition id/)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/Resolution/)).toBeInTheDocument()
    // Quality is a select limited to 1–5 (can't enter an out-of-range value).
    const quality = screen.getByLabelText(/Quality/)
    expect(quality).toBeInTheDocument()
  })

  it('gates [md_source] on the simulation data-source radio', async () => {
    render(<AuthoringForm form="acquisition" />)
    // Experimental (default): no MD source field.
    expect(screen.queryByLabelText(/MD run id/)).not.toBeInTheDocument()
    // Pick Simulation → md_source appears.
    await userEvent.click(screen.getByRole('radio', { name: 'Simulation' }))
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
    // [acquisition] stays editable; the directory-identity id is not a field.
    expect(screen.queryByLabelText(/Acquisition id/)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/Resolution/)).not.toBeDisabled()
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
      expect(screen.getByLabelText(/Resolution/)).toHaveValue(3.4),
    )
    // Loaded → the concrete save path with the known composite id.
    expect(screen.getByText('samp1/Pos1/acquisition.toml')).toBeInTheDocument()
    // md_source present in the file → simulation inferred → field shown.
    expect(screen.getByLabelText(/MD run id/)).toBeInTheDocument()
    expect(screen.getByText(/may lag the on-disk file/)).toBeInTheDocument()
  })
})

describe('AuthoringForm (sectioned) save to file share', () => {
  const inMount = { fields: { seed: 42 }, path: '/groups/cryoet/cryoet/MdRuns/run01' }

  async function loadRun() {
    render(<AuthoringForm form="md_run" initialId="run01" />)
    return waitFor(() =>
      expect(
        screen.getByRole('button', { name: /Save to file share/ }),
      ).toBeInTheDocument(),
    )
  }

  it('shows Save for a portal-loaded record and a dialog with the destination', async () => {
    routeFetch({ load: inMount })
    await loadRun()
    await userEvent.click(screen.getByRole('button', { name: /Save to file share/ }))
    expect(
      await screen.findByText('/groups/cryoet/cryoet/MdRuns/run01/md_run.toml'),
    ).toBeInTheDocument()
  })

  it('confirm connects BEFORE writeFile with the derived target + blob', async () => {
    routeFetch({ load: inMount })
    await loadRun()
    await userEvent.click(screen.getByRole('button', { name: /Save to file share/ }))
    await screen.findByRole('dialog')
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }))
    await waitFor(() => expect(fg.writeFile).toHaveBeenCalled())
    const [fsp, subpath, blob] = fg.writeFile.mock.calls[0]
    expect(fsp).toBe('groups_cryoet_cryoet')
    expect(subpath).toBe('MdRuns/run01/md_run.toml')
    // Backend-authoritative bytes: Save writes exactly what the endpoint returned.
    expect(await (blob as Blob).text()).toBe('seed = 42\n')
    expect(fg.connect.mock.invocationCallOrder[0]).toBeLessThan(
      fg.writeFile.mock.invocationCallOrder[0],
    )
  })

  it('lets the user cancel while waiting for Fileglancer sign-in', async () => {
    routeFetch({ load: inMount })
    // connect() hangs (e.g. a login popup that never resolves) so the dialog
    // stays in the "connecting" phase.
    let releaseConnect: () => void = () => {}
    fg.connect.mockReset().mockImplementation(
      () =>
        new Promise((resolve) => {
          releaseConnect = () => resolve({ authenticated: true })
        }),
    )
    await loadRun()
    await userEvent.click(screen.getByRole('button', { name: /Save to file share/ }))
    await screen.findByRole('dialog')
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }))
    // Connecting: Cancel must stay enabled so a stuck popup can't trap the user,
    // and nothing has been written yet.
    const cancel = screen.getByRole('button', { name: /Cancel/ })
    expect(cancel).toBeEnabled()
    expect(fg.writeFile).not.toHaveBeenCalled()
    // Cancel closes the dialog...
    await userEvent.click(cancel)
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    )
    // ...and even if the abandoned connect() later resolves, no write happens.
    releaseConnect()
    await Promise.resolve()
    await Promise.resolve()
    expect(fg.writeFile).not.toHaveBeenCalled()
  })

  it('keeps the inline 422 error and does NOT open the dialog on Save', async () => {
    routeFetch({
      load: inMount,
      post: () =>
        jsonResponse(
          { errors: [{ loc: ['seed'], msg: 'must be an integer', type: 'int_parsing' }] },
          422,
        ),
    })
    await loadRun()
    await userEvent.click(screen.getByRole('button', { name: /Save to file share/ }))
    await waitFor(() =>
      expect(screen.getByText('must be an integer')).toBeInTheDocument(),
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fg.writeFile).not.toHaveBeenCalled()
  })

  it('maps a ForbiddenError from the write into the error alert', async () => {
    routeFetch({ load: inMount })
    fg.writeFile.mockRejectedValueOnce(new ForbiddenError())
    await loadRun()
    await userEvent.click(screen.getByRole('button', { name: /Save to file share/ }))
    await screen.findByRole('dialog')
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }))
    expect(
      await screen.findByText(/Not authorized: this app's origin/),
    ).toBeInTheDocument()
  })

  it('hides the staleness warning when the seed came from a live disk read', async () => {
    // source='disk' → the form seeded from the fresh on-disk file, so the
    // "may lag" DB warning must NOT show (but Save is still offered).
    routeFetch({
      load: { ...inMount, source: 'disk', baseline: 'seed = 42\n' },
    })
    await loadRun()
    expect(screen.queryByText(/may lag the on-disk file/)).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Save to file share/ }),
    ).toBeInTheDocument()
  })

  it('shows the staleness warning when the seed fell back to the catalog', async () => {
    routeFetch({ load: { ...inMount, source: 'catalog', baseline: null } })
    await loadRun()
    expect(screen.getByText(/may lag the on-disk file/)).toBeInTheDocument()
  })

  it('connects, then reads back, then writes with the baseline etag', async () => {
    routeFetch({
      load: { ...inMount, source: 'disk', baseline: 'seed = 42\n' },
    })
    fg.readFile.mockResolvedValueOnce(
      new Response('seed = 42\n', { headers: { etag: 'W/"live"' } }),
    )
    await loadRun()
    await userEvent.click(screen.getByRole('button', { name: /Save to file share/ }))
    await screen.findByRole('dialog')
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }))
    await waitFor(() => expect(fg.writeFile).toHaveBeenCalled())
    // Ordering: connect (user gesture) → readback → guarded write.
    expect(fg.connect.mock.invocationCallOrder[0]).toBeLessThan(
      fg.readFile.mock.invocationCallOrder[0],
    )
    expect(fg.readFile.mock.invocationCallOrder[0]).toBeLessThan(
      fg.writeFile.mock.invocationCallOrder[0],
    )
    // The readback etag is forwarded as If-Match on the write.
    const [, , , options] = fg.writeFile.mock.calls[0]
    expect(options).toEqual({ ifMatch: 'W/"live"' })
  })

  it('aborts the write and warns when the file changed since load', async () => {
    routeFetch({
      load: { ...inMount, source: 'disk', baseline: 'seed = 42\n' },
    })
    // Readback differs from the baseline → byte-compare fails, no write.
    fg.readFile.mockResolvedValueOnce(
      new Response('seed = 999\n', { headers: { etag: 'W/"live"' } }),
    )
    await loadRun()
    await userEvent.click(screen.getByRole('button', { name: /Save to file share/ }))
    await screen.findByRole('dialog')
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }))
    expect(
      await screen.findByText(/changed since you loaded it/),
    ).toBeInTheDocument()
    expect(fg.writeFile).not.toHaveBeenCalled()
  })

  it('hides Save for an upload-seeded form (no known path); Download remains', async () => {
    routeFetch({ parse: { fields: { seed: 1, custom_note: 'keep me' } } })
    render(<AuthoringForm form="md_run" />)
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(
      input,
      new File(['seed = 1\ncustom_note = "keep me"\n'], 'md_run.toml'),
    )
    await waitFor(() =>
      expect(screen.getByDisplayValue('custom_note')).toBeInTheDocument(),
    )
    expect(
      screen.queryByRole('button', { name: /Save to file share/ }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Download/ })).toBeInTheDocument()
  })
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
