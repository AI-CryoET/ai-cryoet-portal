import React from 'react'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormLabel,
  IconButton,
  Link,
  MenuItem,
  Radio,
  RadioGroup,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import {
  FORM_META,
  ID_PATTERN,
  fieldsFor,
  fieldsForSection,
  sectionsFor,
  type DataSource,
  type FormField,
  type FormKind,
  type FormSection,
} from '~/utils/formFields'
import { PROJECT_REQUIRES_DATA_SOURCE } from '~/utils/filterFields'
import {
  NotSavedToDiskWarning,
  SectionDivider,
  StaleValuesWarning,
} from './authoringBanners'
import { SaveAndDownloadButtons } from './SaveAndDownloadButtons'
import {
  buildCompositePayload,
  buildSectionedPayload,
  emptyEntry,
  emptySection,
  errorsByField,
  errorsByPath,
  fetchMdRunIds,
  hydrateComposite,
  hydrateSections,
  inferDataSource,
  inferSectionedDataSource,
  loadToml,
  parseToml,
  postToml,
  type CompositeSection,
  type CustomField,
  type CustomFieldType,
  type SectionEntry,
  type SectionsState,
  type SectionState,
  type SubmitResult,
  type TomlFieldError,
} from '~/utils/authoring'
import { getFileglancerClient } from '~/utils/fileglancer'

type Props = {
  form: FormKind
  // Search-param auto-load (ADR-0004): seed from the portal on mount. For the
  // composite-keyed acquisition, initialSampleId resolves the record.
  initialId?: string
  initialSampleId?: string
}

// Sample is a composite form with project-gated sections (requiresProject) and
// arbitrary-block reverse-inference; md_run + acquisition are driven by the
// generic sectioned renderer (root/repeatable/cross-ref/immutable sections).
function isProjectGated(form: FormKind): boolean {
  return sectionsFor(form).some((s) => s.requiresProject != null)
}

// Dispatch to the renderer matching the form's shape. Both consume the same
// authored-field registry (ADR-0002); they differ only in section semantics.
export function AuthoringForm({ form, initialId, initialSampleId }: Props) {
  // Pre-warm the Fileglancer session on mount (hidden iframe, no popup) so a
  // logged-in user's "Save to file share" is popup-free. Runs once for whichever
  // renderer is dispatched below; failures are ignored (Save's connect() retries
  // from a user gesture).
  React.useEffect(() => {
    getFileglancerClient()
      .connectSilently()
      .catch(() => {})
  }, [])
  return isProjectGated(form) ? (
    <CompositeAuthoringForm form={form} autoLoadId={initialId} />
  ) : (
    <SectionedAuthoringForm
      form={form}
      initialId={initialId}
      initialSampleId={initialSampleId}
    />
  )
}

// Dotted error/lookup path mirroring the backend loc: root fields are bare,
// named-table fields are `section.field`, repeatable are `section.i.field`.
function pathFor(section: FormSection, field: string, index?: number): string {
  if (section.root) return field
  if (index !== undefined) return `${section.section}.${index}.${field}`
  return `${section.section}.${field}`
}

// Options for a cross-ref dropdown: the field's section literals (e.g. "Frames")
// plus every in-form id in the named namespace. A field whose own section feeds
// the same namespace excludes its own id (no self-reference).
function crossRefOptionsFor(
  field: FormField,
  section: FormSection,
  namespaces: Record<string, string[]>,
  ownId: string,
): string[] {
  const ids = field.crossRef ? (namespaces[field.crossRef] ?? []) : []
  const pool =
    section.idNamespace === field.crossRef
      ? ids.filter((id) => id !== ownId)
      : ids
  return [...section.crossRefLiterals, ...pool]
}

// Generic renderer: builds a form from the authored-field registry (ADR-0002).
// One root section is a flat file (md_run.toml); named + repeatable sections
// compose acquisition.toml's [acquisition] / [md_source] / [[tilt_series]] /
// processing log. Required + IdStr structural checks happen here; all schema
// rules on submit (backend-authoritative, ADR-0001).
function SectionedAuthoringForm({ form, initialId, initialSampleId }: Props) {
  const meta = FORM_META[form]
  const sections = sectionsFor(form)
  const idField = fieldsFor(form).find((f) => f.isId)
  const idSection = idField
    ? sections.find((s) => s.section === idField.section)
    : undefined
  const gated = sections.some((s) => s.requiresDataSource)
  const needsSampleId = meta.placement.includes('{sample_id}')
  const wantsMdRunIds = fieldsFor(form).some((f) => f.apiSuggest === 'md_run')
  const sectionFields = React.useCallback(
    (section: string) => fieldsForSection(form, section),
    [form],
  )

  const [state, setState] = React.useState<SectionsState>(() =>
    hydrateSections(sections, sectionFields, {}),
  )
  const [dataSource, setDataSource] = React.useState<DataSource>('experimental')
  const [sampleId, setSampleId] = React.useState(initialSampleId ?? '')
  const [mdRunIds, setMdRunIds] = React.useState<string[]>([])
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [recordErrors, setRecordErrors] = React.useState<string[]>([])
  const [done, setDone] = React.useState(false)
  // Set on pull-from-API load: data may lag the on-disk file (ADR-0004). Drives
  // apiLoaded/isId-disable/placement/arm-lock — kept overloaded on `fromApi`.
  const [stale, setStale] = React.useState(false)
  // Set only when a portal load fell back to the catalog DB (source='catalog');
  // gates the "may lag the on-disk file" warning, which is moot for a disk read.
  const [catalogFallback, setCatalogFallback] = React.useState(false)
  // Raw text of the on-disk file at load (optimistic-concurrency baseline);
  // non-null only for a disk-sourced portal load. Threaded into Save.
  const [baseline, setBaseline] = React.useState<string | null>(null)
  // True whenever an existing record is loaded (disk upload OR portal); drives
  // the "not saved to disk" banner. Cleared to empty resets it.
  const [loaded, setLoaded] = React.useState(false)
  const [seedError, setSeedError] = React.useState<string | undefined>()
  // On-disk directory of a portal-loaded record (ADR-0004 `path`); drives the
  // "Save to file share" destination. Null for upload/parse/clear (no known
  // location) — Save is hidden then.
  const [recordPath, setRecordPath] = React.useState<string | null>(null)

  // In-form id namespaces feeding cross-ref dropdowns: each section's
  // required-id field contributes to its namespace ("tomogram" pools raw +
  // post-processed ids). Includes locked (loaded) ids so a new annotation can
  // target an existing tomogram.
  const namespaces = React.useMemo(() => {
    const ns: Record<string, string[]> = {}
    for (const s of sections) {
      if (!s.idNamespace) continue
      const idField = sectionFields(s.section).find((f) => f.required)?.field
      if (!idField) continue
      const entries = state[s.section]
      const list = Array.isArray(entries) ? entries : entries ? [entries] : []
      for (const e of list) {
        const v = (e.values[idField] ?? '').trim()
        if (v) (ns[s.idNamespace] ??= []).push(v)
      }
    }
    return ns
  }, [sections, sectionFields, state])

  // Replace form state from a seeded source (upload / API load). A portal load
  // (fromApi) carries the record's on-disk directory so Save can target it;
  // upload/parse/clear have no known location.
  const seed = (
    seeded: Record<string, unknown>,
    fromApi: boolean,
    path: string | null = null,
    source?: 'disk' | 'catalog',
    baseline: string | null = null,
  ) => {
    setState(hydrateSections(sections, sectionFields, seeded))
    setDataSource(inferSectionedDataSource(sections, seeded))
    setErrors({})
    setRecordErrors([])
    setDone(false)
    setSeedError(undefined)
    setStale(fromApi)
    // Only a catalog-sourced load can lag the file; a disk read is fresh.
    setCatalogFallback(fromApi && source === 'catalog')
    setBaseline(fromApi ? baseline : null)
    setLoaded(Object.keys(seeded).length > 0)
    setRecordPath(fromApi ? path : null)
  }

  // Auto-load once on mount when the route supplies an id (edit links).
  React.useEffect(() => {
    if (!initialId) return
    loadToml(form, initialId, initialSampleId)
      .then((result) =>
        seed(result.fields, true, result.path, result.source, result.baseline),
      )
      .catch((err) =>
        setSeedError(err instanceof Error ? err.message : String(err)),
      )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // md_run_id suggestions once a sample context exists.
  React.useEffect(() => {
    if (!wantsMdRunIds || !sampleId.trim()) return
    fetchMdRunIds(sampleId.trim())
      .then(setMdRunIds)
      .catch(() => setMdRunIds([]))
  }, [wantsMdRunIds, sampleId])

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-uploading the same file
    if (!file) return
    try {
      seed(await parseToml(form, await file.text()), false)
    } catch (err) {
      setSeedError(toErrorMessage(err))
    }
  }

  const [loadId, setLoadId] = React.useState('')
  async function handleLoad() {
    const id = loadId.trim()
    if (!id) return
    try {
      const result = await loadToml(form, id, sampleId.trim() || undefined)
      seed(result.fields, true, result.path, result.source, result.baseline)
    } catch (err) {
      setSeedError(toErrorMessage(err))
    }
  }

  // Reset to an empty form, dropping the loaded id and every field value.
  const handleClear = () => {
    seed({}, false)
    setSampleId('')
    setLoadId('')
  }

  // Update one scalar (or one repeatable entry's) field value.
  const setValue = (section: string, field: string, v: string, index?: number) => {
    setDone(false)
    setState((prev) => {
      const next = { ...prev }
      if (index === undefined) {
        const st = (next[section] as SectionState) ?? emptySection()
        next[section] = { ...st, values: { ...st.values, [field]: v } }
      } else {
        const arr = [...((next[section] as SectionState[]) ?? [])]
        const e = arr[index] ?? emptySection()
        arr[index] = { ...e, values: { ...e.values, [field]: v } }
        next[section] = arr
      }
      return next
    })
  }

  const setCustom = (section: string, custom: CustomField[]) => {
    setDone(false)
    setState((prev) => ({
      ...prev,
      [section]: { ...(prev[section] as SectionState), customFields: custom },
    }))
  }

  const addEntry = (section: string) => {
    setDone(false)
    setState((prev) => ({
      ...prev,
      [section]: [...((prev[section] as SectionState[]) ?? []), emptySection()],
    }))
  }
  const removeEntry = (section: string, index: number) => {
    setDone(false)
    setState((prev) => ({
      ...prev,
      [section]: ((prev[section] as SectionState[]) ?? []).filter(
        (_, i) => i !== index,
      ),
    }))
  }

  const idValue =
    (idSection &&
      (state[idSection.section] as SectionState | undefined)?.values[
        idField!.field
      ]?.trim()) ||
    ''

  // Build + validate via the backend (backend-authoritative, ADR-0001). Shared
  // by Download (handleSubmit) and Save (SaveToShareButton) so both post the
  // same payload and receive identical bytes.
  async function validate(): Promise<SubmitResult> {
    const payload = buildSectionedPayload(
      sections,
      sectionFields,
      state,
      dataSource,
      form,
    )
    // The directory-identity id is no longer a form field (it IS the folder
    // name), but a flat form's model still requires it (md_run). Inject a
    // placeholder the endpoint strips from the output so validation passes.
    if (idField && idSection?.root && payload[idField.field] === undefined) {
      payload[idField.field] = 'placeholder'
    }
    return postToml(form, payload, meta.filename)
  }

  // Surface a 422 exactly as before: inline field errors + a record-level list.
  const applyInvalid = (errs: TomlFieldError[]) => {
    setErrors(errorsByField(errs))
    setRecordErrors(errs.filter((er) => er.loc.length === 0).map((er) => er.msg))
  }
  const clearErrors = () => {
    setErrors({})
    setRecordErrors([])
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setDone(false)
    const result = await validate()
    if (result.status === 'invalid') {
      applyInvalid(result.errors)
      return
    }
    clearErrors()
    triggerDownload(result.blob, result.filename)
    setDone(true)
  }

  const dirPath = recordPath

  // Loaded from the portal → concrete path with the known id; new file →
  // template showing the id the user must assign as the folder name.
  const placement = stale
    ? meta.placement
        .replace('{id}', idValue || '<id>')
        .replace('{sample_id}', sampleId.trim() || '<sample_id>')
    : meta.placement
        .replace('{id}', idField ? `{${idField.field}}` : '<id>')
        .replace('{sample_id}', sampleId.trim() || '{sample_id}')

  return (
    <Box component="form" onSubmit={handleSubmit} noValidate>
      <Stack spacing={2}>
        {loaded && <NotSavedToDiskWarning />}
        <UploadLoadToolbar
          filename={meta.filename}
          onUpload={handleUpload}
          loadId={loadId}
          onLoadIdChange={setLoadId}
          onLoad={handleLoad}
          // md_run has no portal load path — nothing loaded, nothing to clear.
          onClear={form === 'md_run' ? undefined : handleClear}
          // md_run has no portal load-by-id path yet.
          showLoadById={form !== 'md_run'}
          extra={
            needsSampleId && (
              <TextField
                label="Sample id"
                value={sampleId}
                onChange={(e) => setSampleId(e.target.value)}
                size="small"
              />
            )
          }
        />

        {gated && (
          <DataSourceRadio value={dataSource} onChange={setDataSource} />
        )}

        {seedError && <Alert severity="error">{seedError}</Alert>}
        {catalogFallback && <StaleValuesWarning />}

        {sections.map((s) => {
          if (s.requiresDataSource && s.requiresDataSource !== dataSource)
            return null
          return s.repeatable ? (
            <RepeatableSection
              key={s.section}
              section={s}
              fields={sectionFields(s.section)}
              entries={(state[s.section] as SectionState[]) ?? []}
              errors={errors}
              namespaces={namespaces}
              onAdd={() => addEntry(s.section)}
              onRemove={(i) => removeEntry(s.section, i)}
              onChange={(i, field, v) => setValue(s.section, field, v, i)}
            />
          ) : (
            <ScalarSection
              key={s.section}
              section={s}
              sectionName={s.title || meta.title}
              fields={sectionFields(s.section)}
              state={(state[s.section] as SectionState) ?? emptySection()}
              errors={errors}
              mdRunIds={mdRunIds}
              namespaces={namespaces}
              apiLoaded={stale}
              onChange={(field, v) => setValue(s.section, field, v)}
              onCustomChange={(c) => setCustom(s.section, c)}
            />
          )
        })}

        {recordErrors.length > 0 && (
          <Alert severity="error">
            {recordErrors.map((m, i) => (
              <div key={i}>{m}</div>
            ))}
          </Alert>
        )}

        {/* Close the fields off with a rule before the saving hint. Titled
            sections lead with one each; md_run (untitled) gets its only one here. */}
        <SectionDivider />
        {loaded && <NotSavedToDiskWarning />}
        {idField && (
          <PlacementHint
            loaded={stale}
            noun={meta.title.toLowerCase()}
            placement={placement}
          />
        )}

        <SaveAndDownloadButtons
          dirPath={dirPath}
          filename={meta.filename}
          baseline={baseline}
          validate={validate}
          onInvalid={(errs) => {
            setDone(false)
            applyInvalid(errs)
          }}
          onValid={clearErrors}
        />

        {done && <Alert severity="success">Downloaded {meta.filename}.</Alert>}
      </Stack>
    </Box>
  )
}

function ScalarSection({
  section,
  sectionName,
  fields,
  state,
  errors,
  mdRunIds,
  namespaces,
  apiLoaded,
  onChange,
  onCustomChange,
}: {
  section: FormSection
  sectionName: string
  fields: FormField[]
  state: SectionState
  errors: Record<string, string>
  mdRunIds: string[]
  namespaces: Record<string, string[]>
  apiLoaded: boolean
  onChange: (field: string, v: string) => void
  onCustomChange: (next: CustomField[]) => void
}) {
  const locked = state.locked ?? false
  const idFieldName = fields.find((f) => f.required)?.field
  const ownId = idFieldName ? (state.values[idFieldName] ?? '').trim() : ''
  return (
    <Box>
      {section.title && (
        <>
          <SectionDivider />
          <Typography variant="h6" gutterBottom sx={{ fontWeight: 700 }}>
            {section.title}
            {locked && ' (read-only)'}
          </Typography>
        </>
      )}
      <Stack spacing={2}>
        {/* The directory-identity id is not authored here (it IS the folder
            name); the placement hint covers it instead. */}
        {fields.filter((f) => !f.isId).map((f) => (
          <Field
            key={f.field}
            field={f}
            value={state.values[f.field] ?? ''}
            error={errors[pathFor(section, f.field)]}
            mdRunIds={mdRunIds}
            // The intended-id field is pre-filled read-only once pulled from
            // the API (ADR-0004): its value drives identity, not editable content.
            disabled={locked || (f.isId && apiLoaded)}
            crossRefOptions={
              f.crossRef
                ? crossRefOptionsFor(f, section, namespaces, ownId)
                : undefined
            }
            onChange={(v) => onChange(f.field, v)}
          />
        ))}
        {/* ponytail: a loaded immutable section is read-only — no append UI.
            Any uploaded scalar extras still round-trip via build, just hidden. */}
        {!locked && (
          <CustomFields
            fields={state.customFields}
            onChange={onCustomChange}
            sectionName={sectionName}
          />
        )}
      </Stack>
    </Box>
  )
}

// Gate a destructive action behind a confirm dialog. A consumer renders the
// returned `dialog` once and calls `confirm(message, action)` from its delete
// handler; `action` runs only if the user confirms. One pending action at a
// time is enough — the dialog is modal.
function useConfirmDelete() {
  const [pending, setPending] = React.useState<{
    message: string
    onConfirm: () => void
  } | null>(null)
  const confirm = (message: string, onConfirm: () => void) =>
    setPending({ message, onConfirm })
  const dialog = (
    <Dialog open={pending !== null} onClose={() => setPending(null)}>
      <DialogTitle>Delete?</DialogTitle>
      <DialogContent>
        <DialogContentText>{pending?.message}</DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setPending(null)}>Cancel</Button>
        <Button
          color="error"
          variant="contained"
          onClick={() => {
            pending?.onConfirm()
            setPending(null)
          }}
        >
          Delete
        </Button>
      </DialogActions>
    </Dialog>
  )
  return { confirm, dialog }
}

// Repeatable [[table]] (tilt_series / tomograms / annotations): add/remove
// entries. Cross-ref fields offer the section literals plus in-form ids from
// the field's namespace. Loaded entries are read-only; only session-added
// entries are editable and removable (ADR-0004 append-only).
function RepeatableSection({
  section,
  fields,
  entries,
  errors,
  namespaces,
  onAdd,
  onRemove,
  onChange,
}: {
  section: FormSection
  fields: FormField[]
  entries: SectionState[]
  errors: Record<string, string>
  namespaces: Record<string, string[]>
  onAdd: () => void
  onRemove: (index: number) => void
  onChange: (index: number, field: string, v: string) => void
}) {
  const idFieldName = fields.find((f) => f.required)?.field
  const { confirm, dialog } = useConfirmDelete()
  return (
    <Box>
      <SectionDivider />
      <Typography variant="h6" gutterBottom sx={{ fontWeight: 700 }}>
        {section.title}
      </Typography>
      <Stack spacing={2}>
        {entries.map((entry, i) => {
          const locked = entry.locked ?? false
          const ownId = idFieldName ? (entry.values[idFieldName] ?? '').trim() : ''
          return (
            <Box
              key={i}
              sx={{ border: 2, borderColor: 'divider', borderRadius: 1, p: 2 }}
            >
              <Stack direction="row" justifyContent="flex-end" alignItems="center">
                {locked && (
                  <Typography variant="caption" color="text.secondary">
                    read-only
                  </Typography>
                )}
                {!locked && (
                  <IconButton
                    aria-label={`Remove ${section.title} entry`}
                    onClick={() =>
                      confirm(
                        `Delete this ${section.title} entry?`,
                        () => onRemove(i),
                      )
                    }
                    size="small"
                  >
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                )}
              </Stack>
              <Stack spacing={2}>
                {fields.map((f) => (
                  <Field
                    key={f.field}
                    field={f}
                    value={entry.values[f.field] ?? ''}
                    error={errors[pathFor(section, f.field, i)]}
                    disabled={locked}
                    crossRefOptions={
                      f.crossRef
                        ? crossRefOptionsFor(f, section, namespaces, ownId)
                        : undefined
                    }
                    onChange={(v) => onChange(i, f.field, v)}
                  />
                ))}
              </Stack>
            </Box>
          )
        })}
      </Stack>
      <Button onClick={onAdd} size="small" sx={{ mt: 1 }}>
        Add {section.title.toLowerCase()}
      </Button>
      {dialog}
    </Box>
  )
}

function Field({
  field,
  value,
  error,
  onChange,
  mdRunIds = [],
  crossRefOptions,
  disabled = false,
}: {
  field: FormField
  value: string
  error?: string
  onChange: (v: string) => void
  mdRunIds?: string[]
  crossRefOptions?: string[]
  disabled?: boolean
}) {
  const help = error ?? field.help

  // API-assisted free text (md_run_id): suggestions + free entry.
  if (field.apiSuggest) {
    return (
      <Autocomplete
        freeSolo
        disabled={disabled}
        options={mdRunIds}
        value={value}
        onInputChange={(_, v) => onChange(v)}
        renderInput={(params) => (
          <TextField
            {...params}
            label={field.label}
            helperText={help}
            error={Boolean(error)}
            size="small"
          />
        )}
      />
    )
  }

  // Cross-ref list (tomogram derived_from): multi-select of in-form ids,
  // stored comma-joined in form state.
  if (field.input === 'multiselect') {
    const selected = value
      ? value.split(',').map((s) => s.trim()).filter(Boolean)
      : []
    return (
      <Autocomplete
        multiple
        disabled={disabled}
        options={crossRefOptions ?? []}
        value={selected}
        onChange={(_, v) => onChange(v.join(','))}
        renderInput={(params) => (
          <TextField
            {...params}
            label={field.label}
            helperText={help}
            error={Boolean(error)}
            size="small"
          />
        )}
      />
    )
  }

  // Cross-ref (derived_from) or fixed-option (quality) dropdown.
  if (field.crossRef || field.input === 'select' || field.input === 'boolean') {
    const options =
      field.input === 'boolean'
        ? [
            { value: 'true', label: 'Yes' },
            { value: 'false', label: 'No' },
          ]
        : (crossRefOptions ?? field.options).map((o) => ({ value: o, label: o }))
    return (
      <TextField
        select
        label={field.label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={field.required}
        disabled={disabled}
        helperText={help}
        error={Boolean(error)}
        fullWidth
        size="small"
      >
        <MenuItem value="">
          <em>—</em>
        </MenuItem>
        {options.map((o) => (
          <MenuItem key={o.value} value={o.value}>
            {o.label}
          </MenuItem>
        ))}
      </TextField>
    )
  }

  // select / boolean / cross-ref are handled by the dropdown branch above; this
  // covers text / integer / number / date / list (list = comma-separated text).
  const numeric = field.input === 'integer' || field.input === 'number'
  const slotProps: Record<string, unknown> = {}
  if (field.input === 'integer') slotProps.htmlInput = { step: 1 }
  if (field.input === 'date') slotProps.inputLabel = { shrink: true }
  return (
    <TextField
      label={field.label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      required={field.required}
      disabled={disabled}
      type={field.input === 'date' ? 'date' : numeric ? 'number' : 'text'}
      slotProps={Object.keys(slotProps).length ? slotProps : undefined}
      // 'list' inputs are comma-separated; the help text explains the format.
      helperText={help}
      error={Boolean(error)}
      fullWidth
      size="small"
    />
  )
}

// Per-section custom fields (ADR-0004): key/value rows with a string/number/
// boolean type selector. List/date are hand-edited, so no UI for them.
// No top border (custom fields join the section above); a bottom border closes
// the section off.
function CustomFields({
  fields,
  onChange,
  sectionName,
}: {
  fields: CustomField[]
  onChange: (next: CustomField[]) => void
  // Human-readable section name, used only in the guidance text below.
  sectionName: string
}) {
  const { confirm, dialog } = useConfirmDelete()
  const update = (i: number, patch: Partial<CustomField>) =>
    onChange(fields.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const remove = (i: number) => onChange(fields.filter((_, j) => j !== i))
  // Skip the prompt for an untouched (empty) row — nothing to lose.
  const removeField = (i: number) => {
    const c = fields[i]
    if (c.key || c.value) confirm('Delete this custom field?', () => remove(i))
    else remove(i)
  }
  const add = () =>
    onChange([...fields, { key: '', value: '', type: 'string' }])

  return (
    <Box sx={{ borderTop: 1, borderColor: 'grey.400', pt: 2 }}>
      <Typography variant="subtitle2">Custom fields</Typography>
      <Typography
        variant="caption"
        color="text.secondary"
        display="block"
        sx={{ mb: 1.5 }}
      >
        Optional: add custom fields to the {sectionName} metadata. Before adding
        fields, ensure you look at the full list of metadata fields, especially
        those that are automatically populated during the data scanning process
        (
        <Link
          href="https://github.com/JaneliaSciComp/ai-cryoet/blob/main/docs/schema.md"
          target="_blank"
          rel="noopener"
        >
          schema.md
        </Link>
        ).
      </Typography>
      <Stack spacing={1}>
        {fields.map((c, i) => (
          <Stack key={i} direction="row" spacing={1} alignItems="center">
            <TextField
              label="Key"
              value={c.key}
              onChange={(e) => update(i, { key: e.target.value })}
              size="small"
            />
            <TextField
              label="Value"
              value={c.value}
              onChange={(e) => update(i, { value: e.target.value })}
              size="small"
              fullWidth
            />
            <TextField
              select
              label="Type"
              value={c.type}
              onChange={(e) =>
                update(i, { type: e.target.value as CustomFieldType })
              }
              size="small"
              sx={{ minWidth: 120 }}
            >
              <MenuItem value="string">string</MenuItem>
              <MenuItem value="number">number</MenuItem>
              <MenuItem value="boolean">boolean</MenuItem>
            </TextField>
            <IconButton
              aria-label="Remove custom field"
              onClick={() => removeField(i)}
              size="small"
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Stack>
        ))}
      </Stack>
      <Button onClick={add} size="small" >
        Add custom field
      </Button>
      {dialog}
    </Box>
  )
}

function toErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

// Save-location hint. The directory-identity id is not a form field (it IS the
// folder name), so a new file guides the user to name that folder (dark green,
// more visible). A file loaded from the portal already knows its id → show the
// concrete path.
function PlacementHint({
  loaded,
  noun,
  placement,
}: {
  loaded: boolean
  noun: string
  placement: string
}) {
  if (loaded) {
    return (
      <Typography variant="body2" color="text.secondary">
        Save as <code>{placement}</code>
      </Typography>
    )
  }
  return (
    <Typography variant="body2" sx={{ color: 'primary.main', fontWeight: 500 }}>
      Save the downloaded file inside a {noun} folder named with the {noun} id. For example: <code>{placement}</code>.
    </Typography>
  )
}

// Experimental/simulation selector shared by both renderers. Sits under the
// upload toolbar and drives which metadata sections show (not written to file).
function DataSourceRadio({
  value,
  onChange,
  disabled = false,
}: {
  value: DataSource
  onChange: (v: DataSource) => void
  disabled?: boolean
}) {
  return (
    <FormControl disabled={disabled}>
      <FormLabel>
        Select which metadata sections to show in the below form:
      </FormLabel>
      <RadioGroup
        row
        value={value}
        onChange={(e) => onChange(e.target.value as DataSource)}
      >
        <FormControlLabel
          value="experimental"
          control={<Radio />}
          label="Experimental"
        />
        <FormControlLabel
          value="simulation"
          control={<Radio />}
          label="Simulation"
        />
      </RadioGroup>
    </FormControl>
  )
}

// Shared upload/load-by-id chrome for both renderers (ADR-0004 seed modes:
// upload + pull-from-API). `extra` slots in a form-specific control between
// the upload button and the load-by-id field (e.g. sample id for acquisition).
function UploadLoadToolbar({
  filename,
  onUpload,
  loadId,
  onLoadIdChange,
  onLoad,
  onClear,
  extra,
  showLoadById = true,
}: {
  filename: string
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void
  loadId: string
  onLoadIdChange: (v: string) => void
  onLoad: () => void
  // Reset the form to empty, dropping any loaded id. Omitted where clearing
  // isn't offered (md_run).
  onClear?: () => void
  extra?: React.ReactNode
  // md_run has no portal load-by-id path yet — hide the field there.
  showLoadById?: boolean
}) {
  return (
    <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
      <Button variant="outlined" component="label" size="small">
        Upload {filename}
        <input
          type="file"
          accept=".toml,text/plain"
          hidden
          onChange={onUpload}
        />
      </Button>
      {extra}
      {showLoadById && (
        <>
          <TextField
            label="Load from portal by id"
            value={loadId}
            onChange={(e) => onLoadIdChange(e.target.value)}
            size="small"
          />
          <Button variant="outlined" size="small" onClick={onLoad}>
            Load
          </Button>
        </>
      )}
      {onClear && (
        <Button variant="text" size="small" onClick={onClear}>
          Clear
        </Button>
      )}
    </Stack>
  )
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ── Composite (sectioned) form: sample ───────────────────────────────────────
// Nested sections with conditional gating reused from the filter model
// (requiresDataSource / requiresProject + the synapse rule, ADR-0003) and
// repeatable array sections. The non-persisted data_source toggle plus the
// project drive which sections show; on upload the arm is reverse-inferred
// (ADR-0004).

function initState(form: FormKind): Record<string, CompositeSection> {
  const out: Record<string, CompositeSection> = {}
  for (const s of sectionsFor(form)) out[s.section] = s.repeatable ? [] : emptyEntry()
  return out
}

function CompositeAuthoringForm({
  form,
  autoLoadId,
}: {
  form: FormKind
  autoLoadId?: string
}) {
  const meta = FORM_META[form]
  const sections = sectionsFor(form)

  const [state, setState] = React.useState<Record<string, CompositeSection>>(() =>
    initState(form),
  )
  const [arm, setArm] = React.useState<DataSource>('experimental')
  const [armLocked, setArmLocked] = React.useState(false)
  const [passthrough, setPassthrough] = React.useState<Record<string, unknown>>(
    {},
  )
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [generalError, setGeneralError] = React.useState<string | undefined>()
  const [done, setDone] = React.useState(false)
  const [stale, setStale] = React.useState(false)
  // Set only when a portal load fell back to the catalog DB (source='catalog');
  // gates the "may lag the on-disk file" warning, which is moot for a disk read.
  const [catalogFallback, setCatalogFallback] = React.useState(false)
  // Raw text of the on-disk file at load (optimistic-concurrency baseline);
  // non-null only for a disk-sourced portal load. Threaded into Save.
  const [baseline, setBaseline] = React.useState<string | null>(null)
  // True whenever an existing record is loaded (disk upload OR portal); drives
  // the "not saved to disk" banner. Cleared to empty resets it.
  const [loaded, setLoaded] = React.useState(false)
  const [conflict, setConflict] = React.useState(false)
  const [seedError, setSeedError] = React.useState<string | undefined>()
  const [loadId, setLoadId] = React.useState(autoLoadId ?? '')
  // On-disk directory of a portal-loaded record (ADR-0004 `path`); drives the
  // "Save to file share" destination. Null for upload/clear (Save hidden then).
  const [recordPath, setRecordPath] = React.useState<string | null>(null)

  const sampleEntry = state['sample'] as SectionEntry
  const project = sampleEntry.values['project'] ?? ''
  const requiredArm = PROJECT_REQUIRES_DATA_SOURCE[project] as DataSource | undefined
  const effectiveArm = requiredArm ?? arm // synapse ⇒ experimental (ADR-0003)
  const armDisabled = Boolean(requiredArm) || armLocked
  const idValue = (sampleEntry.values['sample_id'] ?? '').trim()

  // Replace form state from a seeded source (upload / API load). A portal load
  // (fromApi) carries the record's on-disk directory so Save can target it.
  const seed = (
    seeded: Record<string, unknown>,
    fromApi: boolean,
    path: string | null = null,
    source?: 'disk' | 'catalog',
    baseline: string | null = null,
  ) => {
    const h = hydrateComposite(form, seeded)
    setState(h.state)
    setPassthrough(h.passthrough)
    setErrors({})
    setGeneralError(undefined)
    setDone(false)
    setSeedError(undefined)
    setLoaded(Object.keys(seeded).length > 0)
    setRecordPath(fromApi ? path : null)
    // Only a catalog-sourced load can lag the file; a disk read is fresh.
    setCatalogFallback(fromApi && source === 'catalog')
    setBaseline(fromApi ? baseline : null)
    if (fromApi) {
      // API-seeded: locked from the record + staleness warning (ADR-0004).
      setStale(true)
      setConflict(false)
      if (h.dataSource) {
        setArm(h.dataSource)
        setArmLocked(true)
      } else {
        setArmLocked(false)
      }
    } else {
      setStale(false)
      const inferred = inferDataSource(seeded)
      if (inferred.kind === 'ambiguous') {
        setArmLocked(false) // conflict / none → editable
        setConflict(inferred.reason === 'conflict')
      } else {
        setArm(inferred.kind) // single-sided → infer + lock
        setArmLocked(true)
        setConflict(false)
      }
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-uploading the same file
    if (!file) return
    try {
      seed(await parseToml(form, await file.text()), false)
    } catch (err) {
      setSeedError(toErrorMessage(err))
    }
  }

  async function handleLoad(id: string) {
    const trimmed = id.trim()
    if (!trimmed) return
    try {
      const result = await loadToml(form, trimmed)
      seed(result.fields, true, result.path, result.source, result.baseline)
    } catch (err) {
      setSeedError(toErrorMessage(err))
    }
  }

  // Reset to an empty form, dropping the loaded id and every field value.
  const handleClear = () => {
    seed({}, false)
    setLoadId('')
    setArm('experimental')
    setArmLocked(false)
  }

  // Deep-link auto-load (?id=…): pull from the API once on mount.
  React.useEffect(() => {
    if (autoLoadId) handleLoad(autoLoadId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLoadId, form])

  // One update path for both repeatable (by idx) and single sections.
  const updateEntry = (
    section: string,
    idx: number | undefined,
    patch: (e: SectionEntry) => SectionEntry,
  ) =>
    setState((prev) => {
      const cur = prev[section]
      if (Array.isArray(cur)) {
        return { ...prev, [section]: cur.map((e, i) => (i === idx ? patch(e) : e)) }
      }
      return { ...prev, [section]: patch(cur as SectionEntry) }
    })

  const setEntryValue = (
    section: string,
    field: string,
    v: string,
    idx?: number,
  ) => {
    setDone(false)
    updateEntry(section, idx, (e) => ({
      ...e,
      values: { ...e.values, [field]: v },
    }))
  }

  const setEntryCustom = (section: string, custom: CustomField[], idx?: number) =>
    updateEntry(section, idx, (e) => ({ ...e, custom }))

  const addEntry = (section: string) =>
    setState((prev) => ({
      ...prev,
      [section]: [...(prev[section] as SectionEntry[]), emptyEntry()],
    }))
  const removeEntry = (section: string, idx: number) =>
    setState((prev) => ({
      ...prev,
      [section]: (prev[section] as SectionEntry[]).filter((_, i) => i !== idx),
    }))
  const { confirm, dialog: confirmDialog } = useConfirmDelete()

  // Build + validate, shared by Download (handleSubmit) and Save
  // (SaveToShareButton) so both post the same payload. The thin client-side id
  // gate (full IdStr rules run on the backend) is modelled as a synthetic 422 so
  // it flows through the same invalid-handling path.
  async function validate(): Promise<SubmitResult> {
    if (idValue && !ID_PATTERN.test(idValue)) {
      return {
        status: 'invalid',
        errors: [
          {
            loc: ['sample', 'sample_id'],
            msg: 'Invalid id: letters, digits, . _ - only',
            type: 'value_error',
          },
        ],
      }
    }
    const payload = buildCompositePayload(form, state, passthrough)
    return postToml(form, payload, meta.filename)
  }

  const applyInvalid = (errs: TomlFieldError[]) => {
    const byPath = errorsByPath(errs)
    setErrors(byPath)
    setGeneralError(byPath[''])
  }
  const clearErrors = () => {
    setErrors({})
    setGeneralError(undefined)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setDone(false)
    const result = await validate()
    if (result.status === 'invalid') {
      applyInvalid(result.errors)
      return
    }
    clearErrors()
    triggerDownload(result.blob, result.filename)
    setDone(true)
  }

  const dirPath = recordPath

  const fieldKey = (section: string, fieldName: string, idx?: number) =>
    idx === undefined ? `${section}.${fieldName}` : `${section}.${idx}.${fieldName}`

  const visible = (s: FormSection) => {
    if (s.requiresProject === 'chromatin' && project === 'synapse') return false
    if (s.requiresDataSource && s.requiresDataSource !== effectiveArm) return false
    return true
  }
  // chromatin is hidden for synapse (above) and disabled for any other
  // non-chromatin project — gating reused from the filter logic.
  const sectionDisabled = (s: FormSection) =>
    s.requiresProject === 'chromatin' && project !== '' && project !== 'chromatin'

  const renderFields = (
    section: string,
    entry: SectionEntry,
    idx: number | undefined,
    disabled: boolean,
  ) =>
    fieldsForSection(form, section)
      // The directory-identity id is not authored (it IS the folder name); the
      // placement hint covers it. Derived fields are ingest-populated.
      .filter((f) => !f.derived && !f.isId)
      .map((f) => (
        <Field
          key={f.field}
          field={f}
          value={entry.values[f.field] ?? ''}
          error={errors[fieldKey(section, f.field, idx)]}
          onChange={(v) => setEntryValue(section, f.field, v, idx)}
          disabled={disabled}
        />
      ))

  return (
    <Box component="form" onSubmit={handleSubmit} noValidate>
      <Stack spacing={2}>
        {loaded && <NotSavedToDiskWarning />}
        <UploadLoadToolbar
          filename={meta.filename}
          onUpload={handleUpload}
          loadId={loadId}
          onLoadIdChange={setLoadId}
          onLoad={() => handleLoad(loadId)}
          onClear={handleClear}
        />

        <DataSourceRadio
          value={effectiveArm}
          onChange={(v) => {
            setArm(v)
            setDone(false)
          }}
          disabled={armDisabled}
        />

        {seedError && <Alert severity="error">{seedError}</Alert>}
        {conflict && (
          <Alert severity="warning">
            This file has both experimental and simulation blocks. Pick the data
            source manually, then remove whichever blocks don't belong.
          </Alert>
        )}
        {catalogFallback && <StaleValuesWarning />}
        {generalError && <Alert severity="error">{generalError}</Alert>}

        {sections.map((s) => {
          if (!visible(s)) return null
          const disabled = sectionDisabled(s)
          return (
            <Box key={s.section}>
              <SectionDivider />
              <Typography variant="h6" gutterBottom sx={{ fontWeight: 700 }}>
                {s.title}
              </Typography>

              {s.repeatable ? (
                <Stack spacing={2}>
                  {(state[s.section] as SectionEntry[]).map((entry, idx) => (
                    <Box
                      key={idx}
                      sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2 }}
                    >
                      <Stack spacing={2}>
                        {renderFields(s.section, entry, idx, disabled)}
                        <CustomFields
                          fields={entry.custom}
                          onChange={(c) => setEntryCustom(s.section, c, idx)}
                          sectionName={s.title}
                        />
                      </Stack>
                      <Button
                        onClick={() =>
                          confirm(`Delete this ${s.title} entry?`, () =>
                            removeEntry(s.section, idx),
                          )
                        }
                        size="small"
                        color="error"
                        startIcon={<DeleteOutlineIcon />}
                        sx={{ mt: 1 }}
                      >
                        Remove {s.title}
                      </Button>
                    </Box>
                  ))}
                  <Box>
                    <Button onClick={() => addEntry(s.section)} size="small">
                      Add {s.title}
                    </Button>
                  </Box>
                </Stack>
              ) : (
                <Stack spacing={2}>
                  {renderFields(
                    s.section,
                    state[s.section] as SectionEntry,
                    undefined,
                    disabled,
                  )}
                  {!disabled && (
                    <CustomFields
                      fields={(state[s.section] as SectionEntry).custom}
                      onChange={(c) => setEntryCustom(s.section, c)}
                      sectionName={s.title}
                    />
                  )}
                </Stack>
              )}
            </Box>
          )
        })}
        <SectionDivider />
        {loaded && <NotSavedToDiskWarning />}

        <PlacementHint
          loaded={stale}
          noun={meta.title.toLowerCase()}
          placement={
            stale
              ? meta.placement.replace('{id}', idValue || '<id>')
              : meta.placement.replace('{id}', '{sample_id}')
          }
        />

        <SaveAndDownloadButtons
          dirPath={dirPath}
          filename={meta.filename}
          baseline={baseline}
          validate={validate}
          onInvalid={(errs) => {
            setDone(false)
            applyInvalid(errs)
          }}
          onValid={clearErrors}
        />

        {done && <Alert severity="success">Downloaded {meta.filename}.</Alert>}
      </Stack>
      {confirmDialog}
    </Box>
  )
}
