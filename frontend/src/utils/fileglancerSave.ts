import {
  AuthRequiredError,
  ConflictError,
  FileglancerError,
  ForbiddenError
} from '~/lib/fileglancerClient';
import { getFileglancerClient, toFileglancerTarget } from '~/utils/fileglancer';

// Thrown when the on-disk file differs from the baseline captured at load —
// i.e. it changed in the load→save window. Distinct from the client's
// ConflictError (a server-enforced If-Match failure in the read→write window);
// both surface the same "reload" guidance via describeSaveError.
export class StaleFileError extends Error {
  constructor(message = 'The file changed since it was loaded.') {
    super(message);
    this.name = 'StaleFileError';
  }
}

// Write a validated TOML blob to a record's on-disk directory via Fileglancer,
// with optimistic-concurrency protection. The blob MUST be the exact bytes the
// backend returned (backend-authoritative, ADR-0001) so "Save to file share"
// and "Download" produce identical files.
//
// Two guards prevent clobbering a file that changed since it was loaded:
//   1. Byte-compare (load→save window): read the current file back and require
//      it byte-for-byte identical to `baseline` (the raw text captured at load);
//      a mismatch throws StaleFileError before any write.
//   2. If-Match (read→write window): the readback's etag is sent as `ifMatch`,
//      so the server rejects the PUT with a 412 ConflictError if the file
//      changed between the readback and the write.
//
// connect() is deliberately NOT called here: the form invokes it synchronously
// from the Confirm click handler (to keep the user gesture alive for the login
// popup) and then awaits this helper. The client's typed errors (including a
// readback 404 for a since-deleted file) propagate to the caller, which maps
// them via describeSaveError.
export async function saveTomlToShare(opts: {
  dirPath: string;
  filename: string;
  blob: Blob;
  baseline?: string | null;
}): Promise<void> {
  const target = toFileglancerTarget(opts.dirPath);
  if (!target) {
    throw new Error(
      `Cannot save: ${opts.dirPath} is not under the Fileglancer data mount.`
    );
  }
  const subpath = `${target.subpath}/${opts.filename}`;
  const client = getFileglancerClient();
  // Read the current file back first (a 404 here means it was deleted since
  // load); its etag pins the exact version for the write's If-Match.
  const res = await client.readFile(target.fsp, subpath);
  const current = await res.text();
  const etag = res.headers.get('etag') ?? undefined;
  if (opts.baseline != null && current !== opts.baseline) {
    throw new StaleFileError();
  }
  // writeFile does not create parent dirs; edit records already have theirs.
  await client.writeFile(
    target.fsp,
    subpath,
    opts.blob,
    etag ? { ifMatch: etag } : {}
  );
}

// Map a save failure to a user-facing message. Subclasses of FileglancerError
// (and the local StaleFileError) are checked first — they carry more specific
// guidance — before the generic FileglancerError case.
export function describeSaveError(err: unknown): string {
  if (err instanceof AuthRequiredError) {
    return 'Fileglancer login was not completed — try again.';
  }
  if (err instanceof ForbiddenError) {
    return "Not authorized: this app's origin isn't allowlisted on Fileglancer, or you lack permission for that folder.";
  }
  // Both concurrency guards resolve to the same "reload and re-apply" guidance:
  // the byte-compare (StaleFileError) and the server's If-Match (ConflictError).
  if (err instanceof ConflictError || err instanceof StaleFileError) {
    return 'The file on the share changed since you loaded it. Reload to get the latest, then re-apply your edits.';
  }
  if (err instanceof FileglancerError) {
    if (err.status === 404) {
      return 'The file no longer exists on the share (deleted since you loaded it).';
    }
    return `Save failed (${err.status}): ${err.message}`;
  }
  if (err instanceof Error) {
    return `Save failed: ${err.message}`;
  }
  return `Save failed: ${String(err)}`;
}
