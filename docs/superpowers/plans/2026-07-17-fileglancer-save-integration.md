# Fileglancer Save Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the download-then-manually-copy loop in the `/manage/author` TOML forms with an in-app **"Save to file share"** action that writes the validated TOML directly to the filestore through Fileglancer's programmatic API (`https://fileglancer.int.janelia.org`). Auth is Fileglancer's own session cookie (SameSite=Lax under `janelia.org`) — this app handles **no tokens or credentials**; a login popup opens only when needed.

**Architecture:** The Fileglancer JS client (framework-agnostic TS, zero deps) is vendored into `frontend/src/lib/fileglancerClient.ts`. `frontend/src/utils/fileglancer.ts` — which already owns the mount→share mapping (`/groups/cryoet/cryoet` → `groups_cryoet_cryoet`) — grows a `(fsp, subpath)` target mapper and a lazy client singleton. TOML content stays backend-authoritative (ADR-0001): the form still POSTs to `/api/toml/{kind}` and the browser writes the returned bytes verbatim via `writeFile()`. The save destination comes from the record's scanner-recorded absolute path (edit flow; `GET /api/toml/{kind}/load/{id}` is extended to return it) or is derived from the on-disk layout rules for new records. Download remains as a fallback everywhere.

**Tech Stack:** React 19 + MUI v6 + TanStack Start (frontend, Vitest/jsdom tests); FastAPI + SQLAlchemy (backend, pytest via pixi `test` env).

**Source of truth for the API:** Fileglancer repo `docs/ProgrammaticAPI.md` and `clients/js/README.md` (locally at `/groups/scicompsoft/home/rokickik/dev/fileglancer`, also on Fileglancer PR #409). Do **not** modify the Fileglancer repo.

## Ops prerequisite (flag to a human — cannot be done from this repo)

This app's exact origins must be added to Fileglancer's `api_allowed_origins` server config, or every API call fails with `403 ForbiddenError`:

```yaml
api_allowed_origins:
  - https://ai-cryoet.int.janelia.org        # prod
  # plus any dev origin, exact scheme+host+port, e.g.:
  # - https://<dev-host>.int.janelia.org:<port>
```

Local dev on `localhost` can never work (the session cookie's domain is `janelia.org`, so the browser won't attach it) — the Download button remains the local-dev path.

## Global Constraints

- **Vendored client stays verbatim.** Copy `clients/js/src/index.ts` with its license header; import from it, never rewrite it. If it needs a fix, fix it upstream in the Fileglancer repo first.
- **Backend-authoritative TOML (ADR-0001).** The saved bytes are exactly the blob returned by `POST /api/toml/{kind}` — no client-side TOML serialization.
- **Popups need a user gesture.** `fg.connect()` must be invoked synchronously inside a click handler (the dialog's Confirm click), before any long `await`s.
- **`writeFile` won't create parent directories** — walk-and-`createDirectory()` first for new records.
- **Download must survive** as a visible fallback: local dev, un-allowlisted origins, records with no recorded path, and new md_runs all depend on it.
- **SSR safety.** The client touches `window`; construct it lazily and call it only from event handlers / `useEffect`.
- Run Python tests with the pixi `test` env binary: `.pixi/envs/test/bin/python -m pytest …`. Frontend: `cd frontend && npm test`.

## On-disk layout facts (from `src/schema/layout.py` / `src/catalog/discovery.py`)

```
{CATALOG_DATA_ROOT}/                          # /groups/cryoet/cryoet/data in prod
  Experimental/{sample_id}/sample.toml
  MdSimulation/{Bulk|SingleMolecule|Slab}/{sample_id}/sample.toml
  …/{sample_id}/{acquisition_id}/acquisition.toml
  …/{sample_id}/MdRuns/{md_run_id}/md_run.toml
```

Scanner records absolute dirs: `SampleORM.path`, `AcquisitionORM.path` (both nullable). `MdRunORM` has no path column — derive `{sample.path}/MdRuns/{md_run_id}`.

---

### Task 1: Vendor the Fileglancer client

**Files:**
- Create: `frontend/src/lib/fileglancerClient.ts`

**Steps:**

- [ ] Copy `/groups/scicompsoft/home/rokickik/dev/fileglancer/clients/js/src/index.ts` to `frontend/src/lib/fileglancerClient.ts` unchanged (license header included).
- [ ] Verify it compiles: `cd frontend && npm run build` (tsc runs `--noEmit` as part of build). No behavior tests here — it's vendored code.

### Task 2: Client singleton + target mapping in `utils/fileglancer.ts`

**Files:**
- Modify: `frontend/src/utils/fileglancer.ts`
- Create: `frontend/src/utils/__tests__/fileglancer.test.ts`

**Interfaces:**
- `toFileglancerTarget(absPath: string): { fsp: string; subpath: string } | null` — maps an absolute on-disk path under `/groups/cryoet/cryoet` to the share name + subpath; `null` outside the mount. `toFileglancerUrl` is reimplemented on top of it (same output as today).
- `getFileglancerClient(): FileglancerClient` — lazy singleton; base URL `import.meta.env.VITE_FILEGLANCER_URL ?? 'https://fileglancer.int.janelia.org'` (mirrors the existing hardcoded-constant pattern; the env override serves allowlisted dev origins).

**Steps:**

- [ ] Implement the target mapper + singleton; keep `FILEGLANCER_MOUNT` / `FILEGLANCER_SHARE` as the single source for both browse URLs and API targets.
- [ ] Unit tests: inside-mount file → `{fsp: 'groups_cryoet_cryoet', subpath: 'data/…'}`; mount root; outside-mount → `null`; `toFileglancerUrl` output unchanged for existing cases.

### Task 3: Backend — load endpoint returns the record's directory

**Files:**
- Modify: `src/catalog/api/routes/toml_authoring.py`
- Modify: `tests/catalog/test_api_toml_*.py` (whichever cover `load_toml`)
- Modify: `frontend/src/utils/authoring.ts` (`loadToml` return type)

**Interfaces:**
- `GET /api/toml/{kind}/load/{record_id}` → `{ fields: …, path: string | null }` where `path` is the **directory** holding the TOML:
  - sample → `SampleORM.path`
  - acquisition → `AcquisitionORM.path`
  - md_run → `f"{sample.path}/MdRuns/{md_run_id}"` (join `SampleORM` on `MdRunORM.sample_id`; `null` when `sample.path` is null)

**Steps:**

- [ ] Extend the three `_load_*` call sites (or `load_toml` itself) to fetch and return `path`. Keep `fields` shape untouched.
- [ ] Backend tests: each kind returns the expected `path`; null-path row → `path: null`.
- [ ] Frontend `loadToml()` returns `{ fields, path }`; existing callers destructure `fields` (both renderers' `seed()` paths) — thread `path` into new component state (Task 4).

### Task 4: "Save to file share" for portal-loaded (edit) records

**Files:**
- Create: `frontend/src/utils/fileglancerSave.ts`
- Modify: `frontend/src/components/authoring/AuthoringForm.tsx`
- Modify: `frontend/src/components/authoring/authoringBanners.tsx`
- Modify: `frontend/src/components/authoring/__tests__/AuthoringForm.test.tsx`, `SampleAuthoringForm.test.tsx`

**Interfaces:**
- `saveTomlToShare(opts: { dirPath: string; filename: string; blob: Blob }): Promise<void>` in `fileglancerSave.ts`: maps `dirPath` via `toFileglancerTarget`, calls `writeFile(fsp, `${subpath}/${filename}`, blob)`. Throws typed errors the form renders as messages:
  - `AuthRequiredError` → "Fileglancer login was not completed — try again."
  - `ForbiddenError` → "Not authorized: this app's origin isn't allowlisted on Fileglancer, or you lack permission for that folder."
  - other `FileglancerError` → message + status.
- Note: `connect()` is **not** inside this helper — the form calls it synchronously from the click handler, then awaits the helper.

**UI flow (both renderers — sectioned and composite):**

1. New state: `recordPath: string | null` set by `seed(…, fromApi=true)` from Task 3's `path` (cleared on upload/clear).
2. Button row: primary **"Save to file share"** (rendered when a destination is resolvable) + secondary **"Download {filename}"** (current behavior, always present).
3. Save click → run the existing validate path (`postToml`); on 422 render errors exactly as today; on success open a small confirm dialog showing the destination `code`-styled path (`{recordPath}/{meta.filename}`).
4. Dialog Confirm click → `const fg = getFileglancerClient(); const connectPromise = fg.connect()` **synchronously first**, then `await connectPromise`, then `await saveTomlToShare(...)`.
5. Success → `<Alert severity="success">` "Saved to `{path}`" with a "View in Fileglancer" link (`toFileglancerUrl`) and a note that the portal reflects it after the next scan. Failure → `<Alert severity="error">` with the mapped message.
6. `React.useEffect(() => { getFileglancerClient().connectSilently() }, [])` on the authoring form mount pre-warms the session so Save is popup-free for logged-in users.
7. Reword `NotSavedToDiskWarning`: changes live in the browser until saved to the file share (or downloaded and copied manually).

**Steps:**

- [ ] Implement `fileglancerSave.ts` + message mapping; unit-test with a mocked client module.
- [ ] Wire state/buttons/dialog into `SectionedAuthoringForm` and `CompositeAuthoringForm` (shared subcomponents where practical — e.g. a `SaveToShareButton` owning dialog + alerts, fed `{dirPath, filename, buildBlob: () => postToml(...)}`).
- [ ] Component tests (mock `~/lib/fileglancerClient` and/or `fileglancerSave`): portal-load → Save visible with correct path; confirm → connect called before write; write called with `(fsp, subpath, blob)` derived from the loaded path; 422 keeps current error rendering; Forbidden/AuthRequired render their messages; upload-seeded form (no path yet) hides Save (until Task 5).
- [ ] `npm test` + `npm run build` green.

### Task 5: New-record destinations + directory creation

**Files:**
- Modify: `frontend/src/utils/fileglancer.ts` (add `DATA_ROOT` constant), `fileglancerSave.ts`, `AuthoringForm.tsx`
- Modify: tests from Task 4

**Destination resolution when `recordPath` is null:**

- **acquisition:** requires the form's `sampleId` + the acquisition id field. Fetch `GET /api/samples/{sampleId}` (`SampleDetail.path`, with the existing acquisition-parent fallback from `samples.$sampleId.tsx` extracted into a shared helper if convenient) → `${samplePath}/${acqId}`. Sample missing or pathless → Save disabled with a tooltip pointing at Download.
- **sample:** `DATA_ROOT = '/groups/cryoet/cryoet/data'` (beside the mount constants — same hardcode pattern; revisit as an API-exposed config if envs ever diverge). Experimental arm → `${DATA_ROOT}/Experimental/${sample_id}`; simulation arm → the save dialog gains a required dataset-type select (`Bulk` / `SingleMolecule` / `Slab`, from `DATASET_TYPE_BY_DIR`) → `${DATA_ROOT}/MdSimulation/${subDir}/${sample_id}`.
- **md_run:** stays download-only for new files — the form has no sample context (`FORM_META.md_run.placement` is relative to a sample dir). Follow-up candidate: add a sample-id field to the md_run form, then reuse the acquisition rule with `/MdRuns/`.

**Steps:**

- [ ] `ensureDirectory(fsp, subpath)` in `fileglancerSave.ts`: probe with `listFiles`, `createDirectory` each missing level parent-first (new sample: sample dir; new acquisition: acq dir; both under parents that already exist — but walk generically).
- [ ] Overwrite guard: when the record was *not* portal-loaded, `listFiles` the target file first; if present, the confirm dialog warns "a file already exists at this path and will be overwritten" (portal-loaded edits overwrite silently — that's the point).
- [ ] Extend the save dialog with the dataset-type select (simulation samples only) and the resolved-path preview reacting to it.
- [ ] Tests: destination resolution per kind/arm; ensureDirectory creates only missing levels; overwrite warning shown for existing target; md_run new file shows no Save button.

### Task 6: Deploy config + docs

**Files:**
- Modify: `frontend/Dockerfile` (optional `ARG FILEGLANCER_URL` → `ENV VITE_FILEGLANCER_URL`, mirroring `APP_VERSION`; default keeps prod URL baked)
- Modify: `deploy/DEPLOYMENT.md`

**Steps:**

- [ ] Dockerfile build arg wired (unset ⇒ prod default; used only for allowlisted dev origins).
- [ ] DEPLOYMENT.md: new "Fileglancer write access" section — the `api_allowed_origins` prerequisite (exact origins incl. port), the 403 symptom when missing, the localhost caveat, and that no secrets/config live in this app.

## Verification (end-to-end, per the integration prompt)

- [ ] Edit flow: load a sample/acquisition from the portal → change a field → Save to file share → (popup only if logged out) → file overwritten at the recorded path on the share, owned by the user; success alert links to the file in Fileglancer.
- [ ] Already-logged-in user sees no popup (pre-warm via `connectSilently`).
- [ ] New acquisition under an existing sample: directory created, file written; existing-file overwrite warning fires when re-saving.
- [ ] Logged-out user: Save triggers the login popup; cancelling it surfaces the auth message, not a crash.
- [ ] Un-allowlisted origin (if testable): clear 403 message naming the allowlist.
- [ ] Download flow still works untouched on all three tabs.

## Decision log (defaults taken; flag if wrong)

- Save is **additive**: Download stays as a secondary button everywhere (needed for localhost dev and any 403 situation).
- New **md_run** files are out of scope (no sample context in that form); portal-loaded md_runs do get Save via the derived `MdRuns/` path.
- `DATA_ROOT` / mount / share stay hardcoded frontend constants (existing `fileglancer.ts` pattern) rather than a new config endpoint.
- No scanner/DB write-back on save — the catalog still updates via the normal scan cycle; the success message says so.
