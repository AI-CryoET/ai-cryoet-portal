import React from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Link,
} from '@mui/material'
import { getFileglancerClient, toFileglancerUrl } from '~/utils/fileglancer'
import { describeSaveError, saveTomlToShare } from '~/utils/fileglancerSave'
import type { SubmitResult, TomlFieldError } from '~/utils/authoring'

// Primary "Save to file share" action, shared by both authoring renderers. Owns
// the confirm dialog, the success/error alert, and the connect → write
// orchestration. Backend validation stays in the renderer: this component only
// triggers it via `validate` and hands invalid results back through `onInvalid`
// so each renderer renders field/record errors exactly as it does for Download.
export function SaveToShareButton({
  dirPath,
  filename,
  baseline,
  validate,
  onInvalid,
  onValid,
}: {
  // On-disk directory holding the record's TOML (already confirmed in-mount by
  // the caller). The file is written as `{dirPath}/{filename}`.
  dirPath: string
  filename: string
  // Raw text of the file as loaded (optimistic-concurrency baseline). Non-null
  // ⇒ Save refuses to clobber a file that changed since load (byte-compare).
  // Null (catalog fallback / upload) ⇒ no byte-compare, but If-Match still runs.
  baseline?: string | null
  // Runs the renderer's build + postToml (identical bytes to Download).
  validate: () => Promise<SubmitResult>
  // Invalid (422 or a client-side gate) → the renderer sets its error state.
  onInvalid: (errors: TomlFieldError[]) => void
  // Valid → let the renderer clear any stale errors before the dialog opens.
  onValid?: () => void
}) {
  // The validated blob awaiting confirmation; non-null ⇒ the dialog is open.
  const [pending, setPending] = React.useState<Blob | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [result, setResult] = React.useState<
    { ok: true } | { ok: false; message: string } | null
  >(null)

  const destination = `${dirPath}/${filename}`
  const viewUrl = toFileglancerUrl(destination)

  async function handleSaveClick() {
    const r = await validate()
    if (r.status === 'invalid') {
      onInvalid(r.errors)
      return
    }
    onValid?.()
    setResult(null)
    setPending(r.blob)
  }

  async function handleConfirm() {
    // Reserve the login popup synchronously to preserve the user gesture: call
    // connect() BEFORE any await, then await its promise.
    const fg = getFileglancerClient()
    const connectPromise = fg.connect()
    const blob = pending
    setSaving(true)
    try {
      await connectPromise
      if (blob) await saveTomlToShare({ dirPath, filename, blob, baseline })
      setResult({ ok: true })
    } catch (err) {
      setResult({ ok: false, message: describeSaveError(err) })
    } finally {
      setSaving(false)
      setPending(null)
    }
  }

  return (
    <>
      <Button variant="contained" onClick={handleSaveClick}>
        Save to file share
      </Button>

      <Dialog open={pending !== null} onClose={() => !saving && setPending(null)}>
        <DialogTitle>Save to file share?</DialogTitle>
        <DialogContent>
          <DialogContentText component="div">
            Write the validated file to:
            <br />
            <code>{destination}</code>
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPending(null)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={handleConfirm} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      {result?.ok && (
        <Alert severity="success">
          Saved to <code>{destination}</code>.{' '}
          {viewUrl && (
            <Link href={viewUrl} target="_blank" rel="noopener">
              View in Fileglancer
            </Link>
          )}{' '}
          The portal reflects this change after the next scan.
        </Alert>
      )}
      {result && !result.ok && <Alert severity="error">{result.message}</Alert>}
    </>
  )
}
