/**
 * Component tests for NeuroglancerButton.
 *
 * Covers three source variants:
 *   1. source={null}      → button is disabled
 *   2. kind:'zarr-link'   → renders an anchor (<a>) with the given href
 *   3. kind:'launch'      → clicking opens a popup (window.open), calls the
 *                           mutation (apiFetch), and rewrites the href on success
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NeuroglancerButton } from '../NeuroglancerButton';

// ---------------------------------------------------------------------------
// Module mock: apiFetch — hoisted so the module-level import is replaced.
// ---------------------------------------------------------------------------
vi.mock('../../../utils/api', () => ({
  apiFetch: vi.fn()
}));

import * as apiModule from '../../../utils/api';
const mockApiFetch = vi.mocked(apiModule.apiFetch);

// ---------------------------------------------------------------------------
// Helper: wrap component in a fresh QueryClientProvider.
// ---------------------------------------------------------------------------
function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// window.open mock — replaced before every test.
// ---------------------------------------------------------------------------
let mockWindow: { location: { href: string }; close: ReturnType<typeof vi.fn> };

beforeEach(() => {
  mockWindow = { location: { href: '' }, close: vi.fn() };
  vi.spyOn(window, 'open').mockReturnValue(mockWindow as unknown as Window);
  mockApiFetch.mockReset();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NeuroglancerButton — source={null}', () => {
  it('renders a disabled button', () => {
    renderWithClient(<NeuroglancerButton source={null} />);
    const btn = screen.getByRole('button', { name: /view in neuroglancer/i });
    expect(btn).toBeDisabled();
  });
});

describe('NeuroglancerButton — disabledReason', () => {
  it('disables the button and shows the reason underneath, even with a valid source', () => {
    renderWithClient(
      <NeuroglancerButton
        source={{
          kind: 'launch',
          entity: 'tomogram',
          sampleId: 's',
          acquisitionId: 'a',
          groupId: 'g',
          entityId: 't'
        }}
        disabledReason="Viewer disabled: fix the MRC header."
      />
    );
    expect(
      screen.getByRole('button', { name: /view in neuroglancer/i })
    ).toBeDisabled();
    expect(screen.getByText(/fix the mrc header/i)).toBeInTheDocument();
  });
});

describe('NeuroglancerButton — kind:zarr-link', () => {
  it('renders an anchor with the given href', () => {
    renderWithClient(
      <NeuroglancerButton
        source={{ kind: 'zarr-link', url: 'http://example.com/viewer' }}
      />
    );
    // MUI Button with href renders as an <a> element.
    const link = screen.getByRole('link', { name: /view in neuroglancer/i });
    expect(link).toHaveAttribute('href', 'http://example.com/viewer');
  });
});

describe('NeuroglancerButton — kind:launch', () => {
  // Tomograms carry a group id and return a fully-formed Fileglancer-hosted
  // viewer URL (stateless, precomputed:// source) that must open as-is.
  const tomogramSource = {
    kind: 'launch' as const,
    entity: 'tomogram' as const,
    sampleId: 'sample_a',
    acquisitionId: 'acq1',
    groupId: 'align1',
    entityId: 't1'
  };

  it('opens a tomogram over its group-scoped launch URL and uses the viewer URL as-is', async () => {
    // Stateless tomogram launch: the backend returns an external Fileglancer
    // viewer URL, which must open unchanged (re-rooting it would break it).
    mockApiFetch.mockResolvedValueOnce({
      url: 'https://viewer.example/ng#!state'
    });

    renderWithClient(<NeuroglancerButton source={tomogramSource} />);
    const btn = screen.getByRole('button', { name: /view in neuroglancer/i });

    await userEvent.click(btn);

    // Popup opened synchronously inside click handler.
    expect(window.open).toHaveBeenCalledWith('about:blank', '_blank');

    // apiFetch called with the group-scoped launch URL.
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/tomograms/sample_a/acq1/align1/t1/neuroglancer',
        { method: 'POST' }
      );
    });

    await waitFor(() => {
      expect(mockWindow.location.href).toBe('https://viewer.example/ng#!state');
    });
  });

  it('closes the popup on error', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('server error'));

    renderWithClient(<NeuroglancerButton source={tomogramSource} />);
    const btn = screen.getByRole('button', { name: /view in neuroglancer/i });

    await userEvent.click(btn);

    await waitFor(() => {
      expect(mockWindow.close).toHaveBeenCalled();
    });
  });
});
