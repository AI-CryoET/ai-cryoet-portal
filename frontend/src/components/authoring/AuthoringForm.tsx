import React from 'react'
import { Alert, Box, Button, Stack, TextField, Typography } from '@mui/material'
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
  postToml,
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
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [done, setDone] = React.useState(false)

  const set = (field: string, v: string) => {
    setValues((prev) => ({ ...prev, [field]: v }))
    setDone(false)
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
    const result = await postToml(form, buildPayload(fields, values), meta.filename)
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
        {fields.map((f) => (
          <Field
            key={f.field}
            field={f}
            value={values[f.field] ?? ''}
            error={errors[f.field]}
            onChange={(v) => set(f.field, v)}
          />
        ))}

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
