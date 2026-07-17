import {
  AuthRequiredError,
  FileglancerError,
  ForbiddenError,
} from '~/lib/fileglancerClient'
import { getFileglancerClient, toFileglancerTarget } from '~/utils/fileglancer'

// Write a validated TOML blob to a record's on-disk directory via Fileglancer.
// The blob MUST be the exact bytes the backend returned (backend-authoritative,
// ADR-0001) so "Save to file share" and "Download" produce identical files.
//
// connect() is deliberately NOT called here: the form invokes it synchronously
// from the Confirm click handler (to keep the user gesture alive for the login
// popup) and then awaits this helper. The client's typed errors propagate to the
// caller, which maps them via describeSaveError.
export async function saveTomlToShare(opts: {
  dirPath: string
  filename: string
  blob: Blob
}): Promise<void> {
  const target = toFileglancerTarget(opts.dirPath)
  if (!target) {
    throw new Error(
      `Cannot save: ${opts.dirPath} is not under the Fileglancer data mount.`,
    )
  }
  // writeFile does not create parent dirs; edit records already have theirs.
  await getFileglancerClient().writeFile(
    target.fsp,
    `${target.subpath}/${opts.filename}`,
    opts.blob,
  )
}

// Map a save failure to a user-facing message. Subclasses of FileglancerError
// are checked first (they carry more specific guidance) before the generic case.
export function describeSaveError(err: unknown): string {
  if (err instanceof AuthRequiredError) {
    return 'Fileglancer login was not completed — try again.'
  }
  if (err instanceof ForbiddenError) {
    return "Not authorized: this app's origin isn't allowlisted on Fileglancer, or you lack permission for that folder."
  }
  if (err instanceof FileglancerError) {
    return `Save failed (${err.status}): ${err.message}`
  }
  if (err instanceof Error) {
    return `Save failed: ${err.message}`
  }
  return `Save failed: ${String(err)}`
}
