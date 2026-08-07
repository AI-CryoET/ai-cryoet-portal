/**
 * Renderer test for the composite sample form. Asserts the section gating
 * reused from the filter model (synapse hides chromatin / non-chromatin
 * disables it; experimental vs simulation gates the experimental-only
 * sections; synapse forces experimental), repeatable [[label]] add/remove,
 * a backend 422 surfacing inline, a contradictory upload warning, and
 * deep-link auto-load.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi
} from 'vitest';
import { AuthoringForm } from '../AuthoringForm';
import { AuthRequiredError } from '~/lib/fileglancerClient';

// Mock the vendored Fileglancer client (see AuthoringForm.test.tsx for the
// rationale): connect()/writeFile()/connectSilently() are shared vi.fns.
const fg = vi.hoisted(() => ({
  connect: vi.fn(),
  readFile: vi.fn(),
  writeFile: vi.fn(),
  connectSilently: vi.fn()
}));
vi.mock('~/lib/fileglancerClient', () => {
  class FileglancerError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }
  class AuthRequiredError extends FileglancerError {
    constructor(message = 'Authentication required') {
      super(message, 401);
      this.name = 'AuthRequiredError';
    }
  }
  class ForbiddenError extends FileglancerError {
    constructor(message = 'Forbidden') {
      super(message, 403);
      this.name = 'ForbiddenError';
    }
  }
  class ConflictError extends FileglancerError {
    constructor(message = 'Precondition failed') {
      super(message, 412);
      this.name = 'ConflictError';
    }
  }
  class FileglancerClient {
    connect = fg.connect;
    readFile = fg.readFile;
    writeFile = fg.writeFile;
    connectSilently = fg.connectSilently;
  }
  return {
    default: FileglancerClient,
    FileglancerClient,
    FileglancerError,
    AuthRequiredError,
    ForbiddenError,
    ConflictError
  };
});

beforeAll(() => {
  // jsdom has no object-URL impl; the download path calls it on submit.
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock');
  globalThis.URL.revokeObjectURL = vi.fn();
});
beforeEach(() => {
  fg.connect.mockReset().mockResolvedValue({ authenticated: true });
  // Readback for the save-path optimistic-concurrency check (etag → If-Match).
  fg.readFile
    .mockReset()
    .mockResolvedValue(new Response('', { headers: { etag: 'W/"seed"' } }));
  fg.writeFile.mockReset().mockResolvedValue({ bytes_written: 10 });
  fg.connectSilently.mockReset().mockResolvedValue(false);
});
afterEach(() => vi.restoreAllMocks());

// Route the shared fetch mock: portal load (GET .../load/...) vs the validate
// POST (POST /api/toml/sample).
function routeFetch(opts: {
  load: {
    fields: Record<string, unknown>;
    path: string | null;
    source?: 'disk' | 'catalog';
    baseline?: string | null;
  };
  post?: () => Response;
}) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(((
    input: RequestInfo | URL
  ) => {
    const url = String(input);
    if (url.includes('/load/')) {
      return Promise.resolve(
        new Response(JSON.stringify(opts.load), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        })
      );
    }
    const post =
      opts.post?.() ??
      new Response('project = "nanogold"\n', {
        status: 200,
        headers: { 'Content-Type': 'application/toml' }
      });
    return Promise.resolve(post);
  }) as typeof fetch);
}

async function selectProject(name: string) {
  await userEvent.click(screen.getByRole('combobox', { name: /Project/ }));
  await userEvent.click(await screen.findByRole('option', { name }));
}

const EXP_SECTIONS = [
  'Gold-nanoparticle labels',
  'Fiducial AuNP',
  'Freezing / grid prep',
  'Milling'
];

describe('AuthoringForm (sample) gating', () => {
  it('renders the [sample] section with the data-source toggle', () => {
    render(<AuthoringForm form="sample" />);
    expect(
      screen.getByRole('combobox', { name: /Project/ })
    ).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Experimental' })).toBeChecked();
    expect(
      screen.getByRole('radio', { name: 'Simulation' })
    ).toBeInTheDocument();
  });

  it('hides experimental-only sections when simulation is chosen', async () => {
    render(<AuthoringForm form="sample" />);
    for (const t of EXP_SECTIONS)
      expect(screen.getByText(t)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'Simulation' }));
    for (const t of EXP_SECTIONS)
      expect(screen.queryByText(t)).not.toBeInTheDocument();
  });

  it('hides chromatin for synapse and forces experimental', async () => {
    render(<AuthoringForm form="sample" />);
    expect(screen.getByText('Chromatin')).toBeInTheDocument();
    await selectProject('synapse');
    expect(screen.queryByText('Chromatin')).not.toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Experimental' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Simulation' })).toBeDisabled();
  });

  it('disables chromatin for a non-chromatin project but keeps it visible', async () => {
    render(<AuthoringForm form="sample" />);
    await selectProject('nanogold');
    expect(screen.getByText('Chromatin')).toBeInTheDocument();
    expect(screen.getByLabelText(/Substrate/)).toBeDisabled();
  });
});

describe('AuthoringForm (sample) repeatable labels', () => {
  it('adds and removes a [[label]] entry', async () => {
    render(<AuthoringForm form="sample" />);
    expect(screen.queryByLabelText(/Label target/)).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: /Add Gold-nanoparticle labels/ })
    );
    expect(screen.getByLabelText(/Label target/)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: /Remove Gold-nanoparticle labels/ })
    );
    // Removal is gated behind a confirm dialog; confirm it.
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(screen.queryByLabelText(/Label target/)).not.toBeInTheDocument();
  });
});

describe('AuthoringForm (sample) submit + seed', () => {
  it('surfaces a backend 422 inline on the section field', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          errors: [
            {
              loc: ['sample', 'project'],
              msg: 'Field required',
              type: 'missing'
            }
          ]
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } }
      )
    );
    render(<AuthoringForm form="sample" />);
    await userEvent.click(
      screen.getByRole('button', { name: /Download sample\.toml/ })
    );
    await waitFor(() =>
      expect(screen.getByText('Field required')).toBeInTheDocument()
    );
  });

  it('downloads on a 200 response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('project = "nanogold"\n', {
        status: 200,
        headers: { 'Content-Type': 'application/toml' }
      })
    );
    render(<AuthoringForm form="sample" />);
    await selectProject('nanogold');
    await userEvent.click(
      screen.getByRole('button', { name: /Download sample\.toml/ })
    );
    await waitFor(() =>
      expect(screen.getByText(/Downloaded sample\.toml/)).toBeInTheDocument()
    );
    expect(globalThis.URL.createObjectURL).toHaveBeenCalled();
  });

  it('warns and stays editable when an uploaded file is contradictory', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          fields: { simulation: {}, freezing: { method: 'HPF' } }
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      )
    );
    render(<AuthoringForm form="sample" />);
    const file = new File(
      ['[simulation]\n[freezing]\nmethod="HPF"\n'],
      'sample.toml'
    );
    const input = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() =>
      expect(
        screen.getByText(/both experimental and simulation blocks/)
      ).toBeInTheDocument()
    );
    // Conflict leaves the arm toggle editable (not locked).
    expect(
      screen.getByRole('radio', { name: 'Simulation' })
    ).not.toBeDisabled();
  });

  it('auto-loads a sample by id and locks the arm from the record', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          fields: {
            sample: {
              sample_id: 'samp1',
              data_source: 'simulation',
              project: 'chromatin'
            }
          }
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      )
    );
    render(<AuthoringForm form="sample" initialId="samp1" />);
    await waitFor(() =>
      expect(screen.getByText(/may lag the on-disk file/)).toBeInTheDocument()
    );
    // data_source from the record -> simulation, locked.
    const sim = screen.getByRole('radio', { name: 'Simulation' });
    expect(sim).toBeChecked();
    expect(sim).toBeDisabled();
    // Loaded → concrete save path with the known id.
    expect(screen.getByText('samp1/sample.toml')).toBeInTheDocument();
    // The directory-identity id is not a form field.
    expect(screen.queryByLabelText(/Sample id/)).not.toBeInTheDocument();
  });
});

describe('AuthoringForm (sample) save to file share', () => {
  const inMount = {
    fields: { sample: { sample_id: 'samp1', project: 'nanogold' } },
    path: '/groups/cryoet/cryoet/samp1'
  };

  async function loadSample() {
    render(<AuthoringForm form="sample" initialId="samp1" />);
    return waitFor(() =>
      expect(
        screen.getByRole('button', { name: /Save to file share/ })
      ).toBeInTheDocument()
    );
  }

  it('saves a portal-loaded sample and shows a success alert with a View link', async () => {
    routeFetch({ load: inMount });
    await loadSample();
    await userEvent.click(
      screen.getByRole('button', { name: /Save to file share/ })
    );
    // Dialog shows the concrete destination.
    expect(
      await screen.findByText('/groups/cryoet/cryoet/samp1/sample.toml')
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }));
    await waitFor(() => expect(fg.writeFile).toHaveBeenCalled());
    const [fsp, subpath, blob] = fg.writeFile.mock.calls[0];
    expect(fsp).toBe('groups_cryoet_cryoet');
    expect(subpath).toBe('samp1/sample.toml');
    // Backend-authoritative bytes: Save writes exactly what the endpoint returned.
    expect(await (blob as Blob).text()).toBe('project = "nanogold"\n');
    expect(fg.connect.mock.invocationCallOrder[0]).toBeLessThan(
      fg.writeFile.mock.invocationCallOrder[0]
    );
    // Success alert + "View in Fileglancer" link to the written file. Use
    // findByRole so it retries past the dialog's exit transition (which leaves
    // the form aria-hidden until it unmounts, hiding the link from getByRole).
    expect(await screen.findByText(/Saved to/)).toBeInTheDocument();
    const link = await screen.findByRole('link', {
      name: /View now in Fileglancer/
    });
    expect(link).toHaveAttribute(
      'href',
      'https://fileglancer.int.janelia.org/browse/groups_cryoet_cryoet/samp1/sample.toml'
    );
  });

  it('maps an AuthRequiredError from the write into the error alert', async () => {
    routeFetch({ load: inMount });
    fg.writeFile.mockRejectedValueOnce(new AuthRequiredError());
    await loadSample();
    await userEvent.click(
      screen.getByRole('button', { name: /Save to file share/ })
    );
    await screen.findByRole('dialog');
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }));
    expect(
      await screen.findByText(
        'Fileglancer login was not completed — try again.'
      )
    ).toBeInTheDocument();
  });

  it('hides the staleness warning for a disk-sourced load and saves with If-Match', async () => {
    routeFetch({
      load: { ...inMount, source: 'disk', baseline: 'project = "nanogold"\n' }
    });
    fg.readFile.mockResolvedValueOnce(
      new Response('project = "nanogold"\n', { headers: { etag: 'W/"live"' } })
    );
    await loadSample();
    // source='disk' → the DB "may lag" warning is suppressed.
    expect(
      screen.queryByText(/may lag the on-disk file/)
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: /Save to file share/ })
    );
    await screen.findByRole('dialog');
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }));
    await waitFor(() => expect(fg.writeFile).toHaveBeenCalled());
    const [, , , options] = fg.writeFile.mock.calls[0];
    expect(options).toEqual({ ifMatch: 'W/"live"' });
  });

  it('aborts the save and warns when the file changed since a disk load', async () => {
    routeFetch({
      load: { ...inMount, source: 'disk', baseline: 'project = "nanogold"\n' }
    });
    fg.readFile.mockResolvedValueOnce(
      new Response('project = "synapse"\n', { headers: { etag: 'W/"live"' } })
    );
    await loadSample();
    await userEvent.click(
      screen.getByRole('button', { name: /Save to file share/ })
    );
    await screen.findByRole('dialog');
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }));
    expect(
      await screen.findByText(/changed since you loaded it/)
    ).toBeInTheDocument();
    expect(fg.writeFile).not.toHaveBeenCalled();
  });
});
