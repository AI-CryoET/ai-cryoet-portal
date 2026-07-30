import React from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Link,
  Stack,
} from "@mui/material";
import {
  getFileglancerClient,
  toFileglancerTarget,
  toFileglancerUrl,
} from "~/utils/fileglancer";
import { describeSaveError, saveTomlToShare } from "~/utils/fileglancerSave";
import type { SubmitResult, TomlFieldError } from "~/utils/authoring";

// The "Save to file share" + "Download" action row, shared by both authoring
// renderers. Save owns the confirm dialog and the connect → write
// orchestration; both buttons post identical bytes via `validate` (ADR-0001).
// Backend validation stays in the renderer: this component only triggers it via
// `validate` and hands invalid results back through `onInvalid`. The save
// success/error alert renders below the row (left-aligned) so it doesn't split
// the two buttons.
export function SaveAndDownloadButtons({
  dirPath,
  filename,
  baseline,
  validate,
  onInvalid,
  onValid,
}: {
  // On-disk directory holding the record's TOML (already confirmed in-mount by
  // the caller). The file is written as `{dirPath}/{filename}`. Null when the
  // record has no known location (upload/parse/clear) — Save is hidden then.
  dirPath: string | null;
  filename: string;
  // Raw text of the file as loaded (optimistic-concurrency baseline). Non-null
  // ⇒ Save refuses to clobber a file that changed since load (byte-compare).
  // Null (catalog fallback / upload) ⇒ no byte-compare, but If-Match still runs.
  baseline?: string | null;
  // Runs the renderer's build + postToml (identical bytes to Download).
  validate: () => Promise<SubmitResult>;
  // Invalid (422 or a client-side gate) → the renderer sets its error state.
  onInvalid: (errors: TomlFieldError[]) => void;
  // Valid → let the renderer clear any stale errors before the dialog opens.
  onValid?: () => void;
}) {
  // The validated blob awaiting confirmation; non-null ⇒ the dialog is open.
  const [pending, setPending] = React.useState<Blob | null>(null);
  // 'connecting' = waiting on the Fileglancer login/session — cancellable, since
  // the popup may never resolve; 'writing' = the save is in flight (a mutation),
  // not cancellable.
  const [phase, setPhase] = React.useState<"idle" | "connecting" | "writing">(
    "idle",
  );
  // Monotonic token: a cancel (or a fresh confirm) bumps it, so an abandoned
  // in-flight connect() sees a changed id after its await and bails out instead
  // of writing.
  const runIdRef = React.useRef(0);
  const [result, setResult] = React.useState<
    { ok: true } | { ok: false; message: string } | null
  >(null);

  const canSaveToShare = !!dirPath && toFileglancerTarget(dirPath) !== null;
  const destination = `${dirPath}/${filename}`;
  const viewUrl = toFileglancerUrl(destination);

  async function handleSaveClick() {
    const r = await validate();
    if (r.status === "invalid") {
      onInvalid(r.errors);
      return;
    }
    onValid?.();
    setResult(null);
    setPending(r.blob);
  }

  function handleCancel() {
    // Abandon any in-flight connect() (invalidate its run) and close the dialog,
    // so a login popup that never resolves can't trap the user.
    runIdRef.current += 1;
    setPhase("idle");
    setPending(null);
  }

  async function handleConfirm() {
    // Reserve the login popup synchronously to preserve the user gesture: call
    // connect() BEFORE any await, then await its promise.
    const fg = getFileglancerClient();
    const connectPromise = fg.connect();
    const blob = pending;
    const runId = (runIdRef.current += 1);
    setPhase("connecting");
    try {
      await connectPromise;
      if (runIdRef.current !== runId) return; // cancelled while authenticating
      setPhase("writing");
      if (blob)
        await saveTomlToShare({ dirPath: dirPath!, filename, blob, baseline });
      if (runIdRef.current !== runId) return;
      setResult({ ok: true });
      setPending(null);
    } catch (err) {
      if (runIdRef.current !== runId) return; // cancelled → ignore its failure
      setResult({ ok: false, message: describeSaveError(err) });
      setPending(null);
    } finally {
      if (runIdRef.current === runId) setPhase("idle");
    }
  }

  return (
    <>
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
        {canSaveToShare && (
          <Button variant="contained" onClick={handleSaveClick}>
            Save to file share
          </Button>
        )}
        <Button
          type="submit"
          variant={canSaveToShare ? "outlined" : "contained"}
        >
          Download {filename}
        </Button>
      </Stack>

      <Dialog
        open={pending !== null}
        onClose={() => phase !== "writing" && handleCancel()}
      >
        <DialogTitle>Save to file share?</DialogTitle>
        <DialogContent>
          <DialogContentText component="div">
            Write the validated file to:
            <br />
            <code>{destination}</code>
            {phase === "connecting" && (
              <>
                <br />
                <br />
                Waiting for Fileglancer sign-in — complete it in the popup
                window, or Cancel.
              </>
            )}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          {/* Cancel stays live through sign-in so a missing/blocked popup can't
              trap the user; it's disabled only once the write is in flight. */}
          <Button onClick={handleCancel} disabled={phase === "writing"}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleConfirm}
            disabled={phase !== "idle"}
          >
            {phase === "idle" ? "Save" : "Saving…"}
          </Button>
        </DialogActions>
      </Dialog>

      {result?.ok && (
        <Alert severity="success">
          Saved to <code>{destination}</code>. The portal will reflect this
          change after the next scan.
          {viewUrl && (
            <Link href={viewUrl} target="_blank" rel="noopener">
              View now in Fileglancer.
            </Link>
          )}{" "}
        </Alert>
      )}
      {result && !result.ok && <Alert severity="error">{result.message}</Alert>}
    </>
  );
}
