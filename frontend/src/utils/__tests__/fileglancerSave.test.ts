import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the vendored client module: a constructable class whose writeFile is a
// shared mock (so the lazy singleton in ~/utils/fileglancer exposes it), plus
// real-enough error classes so `instanceof` mapping works end to end.
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
  class FileglancerClient {
    writeFile = vi.fn().mockResolvedValue({ bytes_written: 42 })
  }
  return {
    default: FileglancerClient,
    FileglancerClient,
    FileglancerError,
    AuthRequiredError,
    ForbiddenError,
  }
})

import {
  AuthRequiredError,
  FileglancerError,
  ForbiddenError,
} from '~/lib/fileglancerClient'
import { getFileglancerClient } from '~/utils/fileglancer'
import { describeSaveError, saveTomlToShare } from '~/utils/fileglancerSave'

// The lazy singleton constructs one mock client; grab its writeFile mock.
const writeFile = vi.mocked(getFileglancerClient().writeFile)

describe('saveTomlToShare', () => {
  beforeEach(() => {
    writeFile.mockClear()
    writeFile.mockResolvedValue({ bytes_written: 42 })
  })

  it('maps an in-mount dirPath to writeFile(fsp, subpath/filename, blob)', async () => {
    const blob = new Blob(['x = 1\n'])
    await saveTomlToShare({
      dirPath: '/groups/cryoet/cryoet/Samples/samp1',
      filename: 'sample.toml',
      blob,
    })
    expect(writeFile).toHaveBeenCalledTimes(1)
    expect(writeFile).toHaveBeenCalledWith(
      'groups_cryoet_cryoet',
      'Samples/samp1/sample.toml',
      blob,
    )
  })

  it('throws for a dirPath outside the mount and never writes', async () => {
    await expect(
      saveTomlToShare({
        dirPath: '/groups/other/x',
        filename: 'sample.toml',
        blob: new Blob(),
      }),
    ).rejects.toThrow(/not under the Fileglancer data mount/)
    expect(writeFile).not.toHaveBeenCalled()
  })

  it('lets a write error propagate to the caller', async () => {
    writeFile.mockRejectedValueOnce(new ForbiddenError())
    await expect(
      saveTomlToShare({
        dirPath: '/groups/cryoet/cryoet/x',
        filename: 'md_run.toml',
        blob: new Blob(),
      }),
    ).rejects.toBeInstanceOf(ForbiddenError)
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
