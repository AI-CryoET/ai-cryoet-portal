import FileglancerClient from '~/lib/fileglancerClient'

// Fileglancer browses by share name: the data mount `/groups/cryoet/cryoet`
// is exposed as the share `groups_cryoet_cryoet`, followed by the path relative
// to that mount. e.g. `/groups/cryoet/cryoet/data/x` ->
// `.../browse/groups_cryoet_cryoet/data/x`.
const FILEGLANCER_BASE = 'https://fileglancer.int.janelia.org/browse'
const FILEGLANCER_MOUNT = '/groups/cryoet/cryoet'
const FILEGLANCER_SHARE = 'groups_cryoet_cryoet'

// Maps an absolute on-disk path under the data mount to its Fileglancer API
// target (file share name + subpath relative to the mount, no leading slash).
// Returns null for paths outside the mount.
export function toFileglancerTarget(
  absPath: string,
): { fsp: string; subpath: string } | null {
  if (
    absPath !== FILEGLANCER_MOUNT &&
    !absPath.startsWith(`${FILEGLANCER_MOUNT}/`)
  )
    return null
  const rel = absPath.slice(FILEGLANCER_MOUNT.length) // leading '/' or empty
  const subpath = rel.startsWith('/') ? rel.slice(1) : rel
  return { fsp: FILEGLANCER_SHARE, subpath }
}

// Maps an absolute on-disk path under the data mount to its Fileglancer browse
// URL. Returns null for paths outside the mount (nothing to link to).
export function toFileglancerUrl(absPath: string): string | null {
  const target = toFileglancerTarget(absPath)
  if (!target) return null
  const { fsp, subpath } = target
  return subpath
    ? `${FILEGLANCER_BASE}/${fsp}/${subpath}`
    : `${FILEGLANCER_BASE}/${fsp}`
}

let client: FileglancerClient | undefined

// Lazy module-level singleton for the vendored Fileglancer API client. Callers
// should only invoke this from event handlers / effects, not at module load
// time (the client itself is SSR-safe, but there's no reason to construct it
// before it's needed).
export function getFileglancerClient(): FileglancerClient {
  if (!client) {
    client = new FileglancerClient({
      baseUrl:
        import.meta.env.VITE_FILEGLANCER_URL ??
        'https://fileglancer.int.janelia.org',
    })
  }
  return client
}
