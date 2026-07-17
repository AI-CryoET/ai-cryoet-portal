import FileglancerClient from '~/lib/fileglancerClient'

// Fileglancer browses by share name: the data mount `/groups/cryoet/cryoet`
// is exposed as the share `groups_cryoet_cryoet`, followed by the path relative
// to that mount. e.g. `/groups/cryoet/cryoet/data/x` ->
// `.../browse/groups_cryoet_cryoet/data/x`.
const FILEGLANCER_DOMAIN = 'https://fileglancer.int.janelia.org'
const FILEGLANCER_BASE = `${FILEGLANCER_DOMAIN}/browse`
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
// Delegates the in-mount check to toFileglancerTarget, but rebuilds the URL
// from the raw remainder (leading '/' or empty) so trailing slashes are
// preserved verbatim — the browse URL must be byte-identical for all inputs.
export function toFileglancerUrl(absPath: string): string | null {
  if (!toFileglancerTarget(absPath)) return null
  const rel = absPath.slice(FILEGLANCER_MOUNT.length) // leading '/' or empty
  return `${FILEGLANCER_BASE}/${FILEGLANCER_SHARE}${rel}`
}

let client: FileglancerClient | undefined

// Lazy module-level singleton for the vendored Fileglancer API client. Callers
// should only invoke this from event handlers / effects, not at module load
// time (the client itself is SSR-safe, but there's no reason to construct it
// before it's needed).
export function getFileglancerClient(): FileglancerClient {
  if (!client) {
    client = new FileglancerClient({
      baseUrl: import.meta.env.VITE_FILEGLANCER_URL ?? FILEGLANCER_DOMAIN,
    })
  }
  return client
}
