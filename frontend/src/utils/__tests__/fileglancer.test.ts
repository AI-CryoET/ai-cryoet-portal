import { describe, expect, it } from 'vitest'
import {
  getFileglancerClient,
  toFileglancerTarget,
  toFileglancerUrl,
} from '~/utils/fileglancer'

describe('toFileglancerTarget', () => {
  it('maps an inside-mount file to its share + subpath', () => {
    expect(toFileglancerTarget('/groups/cryoet/cryoet/data/x')).toEqual({
      fsp: 'groups_cryoet_cryoet',
      subpath: 'data/x',
    })
  })

  it('maps the mount root to an empty subpath', () => {
    expect(toFileglancerTarget('/groups/cryoet/cryoet')).toEqual({
      fsp: 'groups_cryoet_cryoet',
      subpath: '',
    })
  })

  it('returns null for a path outside the mount', () => {
    expect(toFileglancerTarget('/groups/other/x')).toBeNull()
  })

  it('returns null for a path that is a prefix-but-not-child of the mount', () => {
    expect(toFileglancerTarget('/groups/cryoet/cryootherthing')).toBeNull()
  })
})

describe('toFileglancerUrl', () => {
  it('builds a browse URL for an inside-mount file', () => {
    expect(toFileglancerUrl('/groups/cryoet/cryoet/data/x')).toBe(
      'https://fileglancer.int.janelia.org/browse/groups_cryoet_cryoet/data/x',
    )
  })

  it('builds a browse URL for the mount root with NO trailing slash', () => {
    expect(toFileglancerUrl('/groups/cryoet/cryoet')).toBe(
      'https://fileglancer.int.janelia.org/browse/groups_cryoet_cryoet',
    )
  })

  it('preserves a trailing slash on the mount path (byte-identical to old impl)', () => {
    expect(toFileglancerUrl('/groups/cryoet/cryoet/')).toBe(
      'https://fileglancer.int.janelia.org/browse/groups_cryoet_cryoet/',
    )
    // distinct from the mount-root (no trailing slash) case above
    expect(toFileglancerUrl('/groups/cryoet/cryoet/')).not.toBe(
      toFileglancerUrl('/groups/cryoet/cryoet'),
    )
  })

  it('returns null for a path outside the mount', () => {
    expect(toFileglancerUrl('/groups/other/x')).toBeNull()
  })
})

describe('getFileglancerClient', () => {
  it('returns the same cached instance on repeated calls', () => {
    const a = getFileglancerClient()
    const b = getFileglancerClient()
    expect(a).toBe(b)
  })
})
