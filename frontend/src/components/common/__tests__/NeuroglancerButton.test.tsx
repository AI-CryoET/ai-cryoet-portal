/**
 * Component tests for NeuroglancerButton.
 *
 * Covers three source variants:
 *   1. source={null}      → button is disabled
 *   2. kind:'zarr-link'   → renders an anchor (<a>) with the given href
 *   3. kind:'launch'      → clicking opens a popup (window.open), calls the
 *                           mutation (apiFetch), and rewrites the href on success
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NeuroglancerButton } from '../NeuroglancerButton'

// ---------------------------------------------------------------------------
// Module mock: apiFetch — hoisted so the module-level import is replaced.
// ---------------------------------------------------------------------------
vi.mock('../../../utils/api', () => ({
  apiFetch: vi.fn(),
}))

import * as apiModule from '../../../utils/api'
const mockApiFetch = vi.mocked(apiModule.apiFetch)

// ---------------------------------------------------------------------------
// Helper: wrap component in a fresh QueryClientProvider.
// ---------------------------------------------------------------------------
function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// ---------------------------------------------------------------------------
// window.open mock — replaced before every test.
// ---------------------------------------------------------------------------
let mockWindow: { location: { href: string }; close: ReturnType<typeof vi.fn> }

beforeEach(() => {
  mockWindow = { location: { href: '' }, close: vi.fn() }
  vi.spyOn(window, 'open').mockReturnValue(mockWindow as unknown as Window)
  mockApiFetch.mockReset()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NeuroglancerButton — source={null}', () => {
  it('renders a disabled button', () => {
    renderWithClient(<NeuroglancerButton source={null} />)
    const btn = screen.getByRole('button', { name: /view in neuroglancer/i })
    expect(btn).toBeDisabled()
  })
})

describe('NeuroglancerButton — kind:zarr-link', () => {
  it('renders an anchor with the given href', () => {
    renderWithClient(
      <NeuroglancerButton source={{ kind: 'zarr-link', url: 'http://example.com/viewer' }} />,
    )
    // MUI Button with href renders as an <a> element.
    const link = screen.getByRole('link', { name: /view in neuroglancer/i })
    expect(link).toHaveAttribute('href', 'http://example.com/viewer')
  })
})

describe('NeuroglancerButton — kind:launch', () => {
  const launchSource = {
    kind: 'launch' as const,
    entity: 'tomogram' as const,
    sampleId: 'sample_a',
    acquisitionId: 'acq1',
    groupId: 'align1',
    entityId: 't1',
  }

  it('opens a blank popup on click and re-roots the viewer URL onto the current origin', async () => {
    // Backend returns an absolute URL on the API host's Neuroglancer port.
    mockApiFetch.mockResolvedValueOnce({ url: 'http://server-host:8050/v/tok123/' })

    renderWithClient(<NeuroglancerButton source={launchSource} />)
    const btn = screen.getByRole('button', { name: /view in neuroglancer/i })

    await userEvent.click(btn)

    // Popup opened synchronously inside click handler.
    expect(window.open).toHaveBeenCalledWith('about:blank', '_blank')

    // apiFetch called with the correct launch URL.
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/tomograms/sample_a/acq1/align1/t1/neuroglancer',
        { method: 'POST' },
      )
    })

    // DEV-ONLY behaviour: the backend host:port is dropped and only the path is
    // re-rooted onto the current origin, so the browser hits the Vite dev
    // server's Neuroglancer reverse proxy instead of a second port.
    await waitFor(() => {
      expect(mockWindow.location.href).toBe(`${window.location.origin}/v/tok123/`)
    })
  })

  it('drops the backend host and port entirely (uses only the path)', async () => {
    // A wildly different backend host/port must not survive the rewrite — the
    // dev proxy serves Neuroglancer on the frontend's own origin.
    mockApiFetch.mockResolvedValueOnce({ url: 'http://10.20.30.40:9999/v/tok456/' })

    renderWithClient(<NeuroglancerButton source={launchSource} />)
    await userEvent.click(screen.getByRole('button', { name: /view in neuroglancer/i }))

    await waitFor(() => {
      expect(mockWindow.location.href).toBe(`${window.location.origin}/v/tok456/`)
    })
  })

  it('closes the popup on error', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('server error'))

    renderWithClient(<NeuroglancerButton source={launchSource} />)
    const btn = screen.getByRole('button', { name: /view in neuroglancer/i })

    await userEvent.click(btn)

    await waitFor(() => {
      expect(mockWindow.close).toHaveBeenCalled()
    })
  })
})
