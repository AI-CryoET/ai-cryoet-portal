import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the vendored client module: a constructable class whose readFile /
// writeFile are shared mocks (so the lazy singleton in ~/utils/fileglancer
// exposes them), plus real-enough error classes so `instanceof` mapping works
// end to end (including the 412 ConflictError added for optimistic concurrency).
vi.mock('~/lib/fileglancerClient', () => {
  class FileglancerError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.name = 'FileglancerError'
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
    readFile = vi.fn()
    writeFile = vi.fn().mockResolvedValue({ bytes_written: 42 })
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

import {
  AuthRequiredError,
  ConflictError,
  FileglancerError,
  ForbiddenError,
} from '~/lib/fileglancerClient'
import { getFileglancerClient } from '~/utils/fileglancer'
import {
  StaleFileError,
  describeSaveError,
  saveTomlToShare,
} from '~/utils/fileglancerSave'

// The lazy singleton constructs one mock client; grab its read/write mocks.
const client = getFileglancerClient()
const readFile = vi.mocked(client.readFile)
const writeFile = vi.mocked(client.writeFile)

// Build a Response-like readback with the given body text and (optional) etag.
function readback(text: string, etag?: string): Response {
  return new Response(text, { headers: etag ? { etag } : {} })
}

const RELOAD_MESSAGE =
  'The file on the share changed since you loaded it. Reload to get the latest, then re-apply your edits.'

describe('saveTomlToShare', () => {
  beforeEach(() => {
    readFile.mockReset().mockResolvedValue(readback('current = 1\n', 'W/"etag1"'))
    writeFile.mockReset().mockResolvedValue({ bytes_written: 42 })
  })

  it('reads back then writes with ifMatch when the file is unchanged', async () => {
    const blob = new Blob(['x = 1\n'])
    readFile.mockResolvedValueOnce(readback('same = 1\n', 'W/"etag1"'))
    await saveTomlToShare({
      dirPath: '/groups/cryoet/cryoet/Samples/samp1',
      filename: 'sample.toml',
      blob,
      baseline: 'same = 1\n',
    })
    expect(readFile).toHaveBeenCalledWith(
      'groups_cryoet_cryoet',
      'Samples/samp1/sample.toml',
    )
    expect(writeFile).toHaveBeenCalledTimes(1)
    expect(writeFile).toHaveBeenCalledWith(
      'groups_cryoet_cryoet',
      'Samples/samp1/sample.toml',
      blob,
      { ifMatch: 'W/"etag1"' },
    )
    // readFile precedes writeFile (baseline compare, then guarded write).
    expect(readFile.mock.invocationCallOrder[0]).toBeLessThan(
      writeFile.mock.invocationCallOrder[0],
    )
  })

  it('writes with no ifMatch when the readback carries no etag', async () => {
    const blob = new Blob(['x = 1\n'])
    readFile.mockResolvedValueOnce(readback('same = 1\n'))
    await saveTomlToShare({
      dirPath: '/groups/cryoet/cryoet/Samples/samp1',
      filename: 'sample.toml',
      blob,
      baseline: 'same = 1\n',
    })
    expect(writeFile).toHaveBeenCalledWith(
      'groups_cryoet_cryoet',
      'Samples/samp1/sample.toml',
      blob,
      {},
    )
  })

  it('skips the byte-compare when no baseline is provided', async () => {
    const blob = new Blob(['x = 1\n'])
    readFile.mockResolvedValueOnce(readback('anything = 1\n', 'W/"e"'))
    await saveTomlToShare({
      dirPath: '/groups/cryoet/cryoet/x',
      filename: 'md_run.toml',
      blob,
    })
    expect(writeFile).toHaveBeenCalledWith('groups_cryoet_cryoet', 'x/md_run.toml', blob, {
      ifMatch: 'W/"e"',
    })
  })

  it('throws StaleFileError and does NOT write when the file changed since load', async () => {
    readFile.mockResolvedValueOnce(readback('changed = 2\n', 'W/"etag2"'))
    await expect(
      saveTomlToShare({
        dirPath: '/groups/cryoet/cryoet/Samples/samp1',
        filename: 'sample.toml',
        blob: new Blob(['x = 1\n']),
        baseline: 'original = 1\n',
      }),
    ).rejects.toBeInstanceOf(StaleFileError)
    expect(writeFile).not.toHaveBeenCalled()
  })

  it('throws for a dirPath outside the mount and never reads or writes', async () => {
    await expect(
      saveTomlToShare({
        dirPath: '/groups/other/x',
        filename: 'sample.toml',
        blob: new Blob(),
        baseline: null,
      }),
    ).rejects.toThrow(/not under the Fileglancer data mount/)
    expect(readFile).not.toHaveBeenCalled()
    expect(writeFile).not.toHaveBeenCalled()
  })

  it('lets a write error propagate to the caller', async () => {
    writeFile.mockRejectedValueOnce(new ForbiddenError())
    await expect(
      saveTomlToShare({
        dirPath: '/groups/cryoet/cryoet/x',
        filename: 'md_run.toml',
        blob: new Blob(),
        baseline: null,
      }),
    ).rejects.toBeInstanceOf(ForbiddenError)
  })

  it('propagates a ConflictError (412) from the guarded write', async () => {
    // Byte-compare passes (readback == baseline) so the write is reached; the
    // server then rejects it with a 412 for a race in the read→write window.
    readFile.mockResolvedValueOnce(readback('same = 1\n', 'W/"e"'))
    writeFile.mockRejectedValueOnce(new ConflictError())
    await expect(
      saveTomlToShare({
        dirPath: '/groups/cryoet/cryoet/x',
        filename: 'md_run.toml',
        blob: new Blob(),
        baseline: 'same = 1\n',
      }),
    ).rejects.toBeInstanceOf(ConflictError)
  })

  it('propagates a readback 404 (file deleted since load) and never writes', async () => {
    readFile.mockRejectedValueOnce(new FileglancerError('not found', 404))
    await expect(
      saveTomlToShare({
        dirPath: '/groups/cryoet/cryoet/x',
        filename: 'md_run.toml',
        blob: new Blob(),
        baseline: 'same = 1\n',
      }),
    ).rejects.toBeInstanceOf(FileglancerError)
    expect(writeFile).not.toHaveBeenCalled()
  })
})

describe('describeSaveError', () => {
  it('maps AuthRequiredError to a retry-login message', () => {
    expect(describeSaveError(new AuthRequiredError())).toBe(
      'Fileglancer login was not completed — try again.',
    )
  })

  it('maps ForbiddenError to an allowlist/permission message', () => {
    expect(describeSaveError(new ForbiddenError())).toBe(
      "Not authorized: this app's origin isn't allowlisted on Fileglancer, or you lack permission for that folder.",
    )
  })

  it('maps a ConflictError (412) to the reload message', () => {
    expect(describeSaveError(new ConflictError())).toBe(RELOAD_MESSAGE)
  })

  it('maps a StaleFileError (byte mismatch) to the same reload message', () => {
    expect(describeSaveError(new StaleFileError())).toBe(RELOAD_MESSAGE)
  })

  it('maps a readback 404 to a file-deleted message', () => {
    expect(describeSaveError(new FileglancerError('not found', 404))).toBe(
      'The file no longer exists on the share (deleted since you loaded it).',
    )
  })

  it('maps a generic FileglancerError to message + status', () => {
    expect(describeSaveError(new FileglancerError('boom', 500))).toBe(
      'Save failed (500): boom',
    )
  })

  it('falls back for a plain Error', () => {
    expect(describeSaveError(new Error('nope'))).toBe('Save failed: nope')
  })

  it('falls back for a non-error value', () => {
    expect(describeSaveError('weird')).toBe('Save failed: weird')
  })
})
