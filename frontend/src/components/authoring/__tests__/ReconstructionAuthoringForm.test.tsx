/**
 * Renderer test for the reconstruction form. Identity is a triple
 * (sample, acquisition, Reconstructions/<group> folder), so this form is the
 * only one with a group selector: it picks which group's file is being
 * authored, and switching remounts the form so nothing bleeds between groups.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { AuthoringForm } from '../AuthoringForm';

beforeAll(() => {
  // jsdom has no object-URL impl; the download path calls it on submit.
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock');
  globalThis.URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  });
}

// The form fires three GETs on mount: the group list, the record load, and the
// tilt-series suggestions. Route by URL so each gets a plausible body.
//
// A load is keyed by the triple (sample, acquisition, group), so `byGroup` may
// be keyed either by the bare group id or by "<acquisition_id>/<group>" — the
// latter lets a test prove the load used the context the user actually typed
// rather than the route's. A group id with no matching key 422s, mirroring
// _load_reconstruction's missing-context error.
function mockApi(groups: string[], byGroup: Record<string, unknown>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(input => {
    const url = String(input);
    if (url.includes('/reconstruction-group-ids/')) {
      return Promise.resolve(jsonResponse({ ids: groups }));
    }
    if (url.includes('/tilt-series-ids/')) {
      return Promise.resolve(jsonResponse({ ids: ['ts_raw'] }));
    }
    const [path, query = ''] = url.split('/load/')[1]?.split('?') ?? [];
    const group = decodeURIComponent(path ?? '');
    const acq = new URLSearchParams(query).get('acquisition_id');
    const fields = byGroup[`${acq}/${group}`] ?? byGroup[group];
    if (fields === undefined) {
      return Promise.resolve(
        jsonResponse(
          { detail: 'sample_id and acquisition_id query params required' },
          422
        )
      );
    }
    return Promise.resolve(jsonResponse({ fields }));
  });
}

describe('AuthoringForm (reconstruction)', () => {
  it('renders the four reconstruction sections with a group selector', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({
        fields: {
          reconstruction_alignment: { alignment_software: 'IMOD 4.12' },
          raw_tomogram: [{ id: 'bp_3dctf_bin4' }]
        }
      })
    );
    render(
      <AuthoringForm
        form="reconstruction"
        initialId="recon_1"
        initialSampleId="samp1"
        initialAcquisitionId="Position_86"
      />
    );
    expect(await screen.findByLabelText(/Alignment software/)).toHaveValue(
      'IMOD 4.12'
    );
    expect(screen.getByRole('combobox', { name: /Group/ })).toBeInTheDocument();
    expect(screen.getByText('3D alignment')).toBeInTheDocument();
    expect(screen.getByText('Raw tomograms')).toBeInTheDocument();
    expect(screen.getByText('Post-processed tomograms')).toBeInTheDocument();
    expect(screen.getByText('Annotations')).toBeInTheDocument();
  });

  it('shows the concrete placement path once loaded', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ fields: { reconstruction_alignment: {} } })
    );
    render(
      <AuthoringForm
        form="reconstruction"
        initialId="recon_1"
        initialSampleId="samp1"
        initialAcquisitionId="Position_86"
      />
    );
    expect(
      await screen.findByText(
        /samp1\/Position_86\/Reconstructions\/recon_1\/reconstruction\.toml/
      )
    ).toBeInTheDocument();
  });

  it('lists the acquisition groups and reloads on switch, resetting state', async () => {
    mockApi(['grp_a', 'grp_b'], {
      grp_a: {
        reconstruction_alignment: { alignment_software: 'IMOD 4.12' },
        raw_tomogram: [{ id: 'bp_bin4' }, { id: 'bp_bin8' }]
      },
      grp_b: { reconstruction_alignment: { alignment_method: 'fiducial' } }
    });
    render(
      <AuthoringForm
        form="reconstruction"
        initialId="grp_a"
        initialSampleId="samp1"
        initialAcquisitionId="Position_86"
      />
    );
    expect(await screen.findByLabelText(/Alignment software/)).toHaveValue(
      'IMOD 4.12'
    );
    expect(
      screen.getAllByRole('button', { name: /Remove Raw tomograms entry/ })
    ).toHaveLength(2);

    await userEvent.click(screen.getByRole('combobox', { name: /Group/ }));
    await userEvent.click(await screen.findByRole('option', { name: 'grp_b' }));

    await waitFor(() =>
      expect(screen.getByLabelText(/Alignment method/)).toHaveValue('fiducial')
    );
    // grp_a's value is gone — the form remounted rather than merging.
    expect(screen.getByLabelText(/Alignment software/)).toHaveValue('');
    // …and so are its repeatable rows: isolation has to hold for arrays too,
    // not just scalars, or grp_a's tomograms get filed under grp_b.
    expect(
      screen.queryAllByRole('button', { name: /Remove Raw tomograms entry/ })
    ).toHaveLength(0);
    expect(
      screen.getByText(
        /samp1\/Position_86\/Reconstructions\/grp_b\/reconstruction\.toml/
      )
    ).toBeInTheDocument();
  });

  it('renames the save path when a different group is loaded by id', async () => {
    // The group id is a folder name, never a column, so the hint falls back to
    // the id the content was loaded BY. That must track the current load, not
    // the id the route mounted with — otherwise the hint files one group's
    // content over another group's file.
    mockApi(['grp_a', 'denoised'], {
      grp_a: { reconstruction_alignment: {} },
      denoised: { reconstruction_alignment: { alignment_method: 'fiducial' } }
    });
    render(
      <AuthoringForm
        form="reconstruction"
        initialId="grp_a"
        initialSampleId="samp1"
        initialAcquisitionId="Position_86"
      />
    );
    expect(
      await screen.findByText(
        /samp1\/Position_86\/Reconstructions\/grp_a\/reconstruction\.toml/
      )
    ).toBeInTheDocument();

    await userEvent.type(
      screen.getByLabelText(/Load from portal by id/),
      'denoised'
    );
    await userEvent.click(screen.getByRole('button', { name: 'Load' }));

    await waitFor(() =>
      expect(screen.getByLabelText(/Alignment method/)).toHaveValue('fiducial')
    );
    expect(
      screen.getByText(
        'samp1/Position_86/Reconstructions/denoised/reconstruction.toml'
      )
    ).toBeInTheDocument();
  });

  it('follows a load-by-id in the selector, so switching back still works', async () => {
    // The selector and the placement hint must never name different groups.
    // MUI's SelectInput skips onChange when the clicked value equals the
    // current one, so a stale selector turns a click on the originally
    // deep-linked group into a no-op — a dead end with no way back.
    mockApi(['grp_a', 'denoised'], {
      grp_a: { reconstruction_alignment: { alignment_software: 'IMOD 4.12' } },
      denoised: { reconstruction_alignment: { alignment_method: 'fiducial' } }
    });
    render(
      <AuthoringForm
        form="reconstruction"
        initialId="grp_a"
        initialSampleId="samp1"
        initialAcquisitionId="Position_86"
      />
    );
    const selector = await screen.findByRole('combobox', { name: /Group/ });
    await waitFor(() => expect(selector).toHaveTextContent('grp_a'));

    await userEvent.type(
      screen.getByLabelText(/Load from portal by id/),
      'denoised'
    );
    await userEvent.click(screen.getByRole('button', { name: 'Load' }));

    await waitFor(() =>
      expect(screen.getByLabelText(/Alignment method/)).toHaveValue('fiducial')
    );
    // Selector and hint agree on the group the form is actually holding.
    expect(screen.getByRole('combobox', { name: /Group/ })).toHaveTextContent(
      'denoised'
    );
    expect(
      screen.getByText(
        'samp1/Position_86/Reconstructions/denoised/reconstruction.toml'
      )
    ).toBeInTheDocument();

    // …so picking grp_a again is a real change and does reload it.
    await userEvent.click(screen.getByRole('combobox', { name: /Group/ }));
    await userEvent.click(await screen.findByRole('option', { name: 'grp_a' }));
    await waitFor(() =>
      expect(screen.getByLabelText(/Alignment software/)).toHaveValue(
        'IMOD 4.12'
      )
    );
    expect(
      screen.getByText(
        'samp1/Position_86/Reconstructions/grp_a/reconstruction.toml'
      )
    ).toBeInTheDocument();
  });

  it('keeps hand-typed context when loading by id with no route context', async () => {
    // Reaching the form from a bare /author tab supplies no sample or
    // acquisition, so the load can only use what the user typed. Anything that
    // remounts the form on load re-initialises those two fields from the route
    // props (undefined here) and re-fetches without them — a 422 that wipes
    // out the load that had just succeeded.
    mockApi([], {
      'Position_86/grp_a': {
        reconstruction_alignment: { alignment_software: 'IMOD 4.12' }
      }
    });
    render(<AuthoringForm form="reconstruction" />);

    await userEvent.type(screen.getByLabelText(/Sample id/), 'samp1');
    await userEvent.type(
      screen.getByLabelText(/Acquisition id/),
      'Position_86'
    );
    await userEvent.type(
      screen.getByLabelText(/Load from portal by id/),
      'grp_a'
    );
    await userEvent.click(screen.getByRole('button', { name: 'Load' }));

    await waitFor(() =>
      expect(screen.getByLabelText(/Alignment software/)).toHaveValue(
        'IMOD 4.12'
      )
    );
    // The typed context survives, so the hint names a complete path…
    expect(screen.getByLabelText(/Sample id/)).toHaveValue('samp1');
    expect(screen.getByLabelText(/Acquisition id/)).toHaveValue('Position_86');
    expect(
      screen.getByText(
        'samp1/Position_86/Reconstructions/grp_a/reconstruction.toml'
      )
    ).toBeInTheDocument();
    // …and the load isn't undone by a follow-up fetch.
    expect(screen.queryByText(/load failed/i)).not.toBeInTheDocument();
  });

  it('loads the edited acquisition context, not the route acquisition', async () => {
    // Editing the Acquisition id before loading targets a different record.
    // A remount would silently revert to the route acquisition and either 404
    // or load someone else's group under the same folder name.
    mockApi(['grp_a'], {
      'Position_86/grp_a': {
        reconstruction_alignment: { alignment_software: 'route acquisition' }
      },
      'Position_99/grp_b': {
        reconstruction_alignment: { alignment_software: 'typed acquisition' }
      }
    });
    render(
      <AuthoringForm
        form="reconstruction"
        initialId="grp_a"
        initialSampleId="samp1"
        initialAcquisitionId="Position_86"
      />
    );
    expect(await screen.findByLabelText(/Alignment software/)).toHaveValue(
      'route acquisition'
    );

    await userEvent.clear(screen.getByLabelText(/Acquisition id/));
    await userEvent.type(
      screen.getByLabelText(/Acquisition id/),
      'Position_99'
    );
    await userEvent.type(
      screen.getByLabelText(/Load from portal by id/),
      'grp_b'
    );
    await userEvent.click(screen.getByRole('button', { name: 'Load' }));

    await waitFor(() =>
      expect(screen.getByLabelText(/Alignment software/)).toHaveValue(
        'typed acquisition'
      )
    );
    expect(screen.getByLabelText(/Acquisition id/)).toHaveValue('Position_99');
    expect(
      screen.getByText(
        'samp1/Position_99/Reconstructions/grp_b/reconstruction.toml'
      )
    ).toBeInTheDocument();
  });

  it('starts an empty file for a new group, showing the folder-name hint', async () => {
    mockApi(['grp_a'], {
      grp_a: { reconstruction_alignment: { alignment_software: 'IMOD 4.12' } }
    });
    render(
      <AuthoringForm
        form="reconstruction"
        initialId="grp_a"
        initialSampleId="samp1"
        initialAcquisitionId="Position_86"
      />
    );
    expect(await screen.findByLabelText(/Alignment software/)).toHaveValue(
      'IMOD 4.12'
    );

    await userEvent.click(screen.getByRole('combobox', { name: /Group/ }));
    await userEvent.click(
      await screen.findByRole('option', { name: /New group/ })
    );

    await waitFor(() =>
      expect(screen.getByLabelText(/Alignment software/)).toHaveValue('')
    );
    // No id yet: the hint tells the user to name the folder they create.
    expect(
      screen.getByText(
        'samp1/Position_86/Reconstructions/{reconstruction_alignment_id}/reconstruction.toml'
      )
    ).toBeInTheDocument();
  });
});
