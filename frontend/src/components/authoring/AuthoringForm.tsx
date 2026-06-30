import React from 'react'
import {
  Alert,
  Box,
  Button,
  Divider,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import {
  FORM_META,
  ID_PATTERN,
  fieldsFor,
  type FormField,
  type FormKind,
} from '~/utils/formFields'
import {
  buildPayload,
  errorsByField,
  hydrate,
  loadToml,
  parseToml,
  postToml,
  type CustomField,
  type CustomFieldType,
} from '~/utils/authoring'

type Props = { form: FormKind }

// Generic renderer: builds a form from the authored-field registry (ADR-0002).
// Scalar inputs + enum dropdowns; required + IdStr structural checks happen
// here, all schema rules on submit (backend-authoritative, ADR-0001).
export function AuthoringForm({ form }: Props) {
  const meta = FORM_META[form]
  const fields = fieldsFor(form)
  const idField = fields.find((f) => f.isId)

  const [values, setValues] = React.useState<Record<string, string>>({})
  const [customFields, setCustomFields] = React.useState<CustomField[]>([])
  const [passthrough, setPassthrough] = React.useState<Record<string, unknown>>(
    {},
  )
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [done, setDone] = React.useState(false)
  // Set on pull-from-API load: data may lag the on-disk file (ADR-0004).
  const [stale, setStale] = React.useState(false)
  const [seedError, setSeedError] = React.useState<string | undefined>()

  const set = (field: string, v: string) => {
    setValues((prev) => ({ ...prev, [field]: v }))
    setDone(false)
  }

  // Replace form state from a seeded source (upload / API load).
  const seed = (seeded: Record<string, unknown>, fromApi: boolean) => {
    const next = hydrate(fields, seeded)
    setValues(next.values)
    setCustomFields(next.customFields)
    setPassthrough(next.passthrough)
    setErrors({})
    setDone(false)
    setSeedError(undefined)
    setStale(fromApi)
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-uploading the same file
    if (!file) return
    try {
      seed(await parseToml(form, await file.text()), false)
    } catch (err) {
      setSeedError(err instanceof Error ? err.message : String(err))
    }
  }

  const [loadId, setLoadId] = React.useState('')
  async function handleLoad() {
    const id = loadId.trim()
    if (!id) return
    try {
      seed(await loadToml(form, id), true)
    } catch (err) {
      setSeedError(err instanceof Error ? err.message : String(err))
    }
  }

  const idValue = (idField && values[idField.field]?.trim()) || ''

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setDone(false)
    // Thin structural check on the id (the full IdStr rules run on the backend).
    if (idField) {
      if (!idValue) {
        setErrors({ [idField.field]: 'Required' })
        return
      }
      if (!ID_PATTERN.test(idValue)) {
        setErrors({ [idField.field]: 'Invalid id: letters, digits, . _ - only' })
        return
      }
    }
    const payload = buildPayload(fields, values, customFields, passthrough)
    const result = await postToml(form, payload, meta.filename)
    if (result.status === 'invalid') {
      setErrors(errorsByField(result.errors))
      return
    }
    setErrors({})
    triggerDownload(result.blob, result.filename)
    setDone(true)
  }

  return (
    <Box component="form" onSubmit={handleSubmit} noValidate>
      <Stack spacing={2}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <Button variant="outlined" component="label" size="small">
            Upload {meta.filename}
            <input
              type="file"
              accept=".toml,text/plain"
              hidden
              onChange={handleUpload}
            />
          </Button>
          <TextField
            label="Load from portal by id"
            value={loadId}
            onChange={(e) => setLoadId(e.target.value)}
            size="small"
          />
          <Button variant="outlined" size="small" onClick={handleLoad}>
            Load
          </Button>
        </Stack>

        {seedError && <Alert severity="error">{seedError}</Alert>}
        {stale && (
          <Alert severity="warning">
            Loaded from the portal — this may lag the on-disk file. Re-check
            before saving over newer changes.
          </Alert>
        )}

        {fields.map((f) => (
          <Field
            key={f.field}
            field={f}
            value={values[f.field] ?? ''}
            error={errors[f.field]}
            onChange={(v) => set(f.field, v)}
          />
        ))}

        <CustomFields fields={customFields} onChange={setCustomFields} />

        {idField && (
          <Typography variant="body2" color="text.secondary">
            Save as <code>{meta.placement.replace('{id}', idValue || '<id>')}</code>
          </Typography>
        )}

        <Box>
          <Button type="submit" variant="contained">
            Download {meta.filename}
          </Button>
        </Box>

        {done && (
          <Alert severity="success">Downloaded {meta.filename}.</Alert>
        )}
      </Stack>
    </Box>
  )
}

function Field({
  field,
  value,
  error,
  onChange,
}: {
  field: FormField
  value: string
  error?: string
  onChange: (v: string) => void
}) {
  const numeric = field.input === 'integer' || field.input === 'number'
  return (
    <TextField
      label={field.label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      required={field.required}
      type={numeric ? 'number' : 'text'}
      slotProps={
        field.input === 'integer' ? { htmlInput: { step: 1 } } : undefined
      }
      helperText={error ?? field.help}
      error={Boolean(error)}
      fullWidth
      size="small"
    />
  )
}

// Per-section custom fields (ADR-0004): key/value rows with a string/number/
// boolean type selector. List/date are hand-edited, so no UI for them.
function CustomFields({
  fields,
  onChange,
}: {
  fields: CustomField[]
  onChange: (next: CustomField[]) => void
}) {
  const update = (i: number, patch: Partial<CustomField>) =>
    onChange(fields.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const remove = (i: number) => onChange(fields.filter((_, j) => j !== i))
  const add = () =>
    onChange([...fields, { key: '', value: '', type: 'string' }])

  return (
    <Box>
      <Divider sx={{ mb: 2 }} />
      <Typography variant="subtitle2" gutterBottom>
        Custom fields
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
              onClick={() => remove(i)}
              size="small"
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Stack>
        ))}
      </Stack>
      <Button onClick={add} size="small" sx={{ mt: 1 }}>
        Add custom field
      </Button>
    </Box>
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
