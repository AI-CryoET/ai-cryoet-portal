import type { FormField, FormKind } from '~/utils/formFields'

// Field-level error from the backend (POST /toml/{kind} -> 422). `loc` is
// normalized to model field names server-side, so loc[0] keys a form field.
export interface TomlFieldError {
  loc: (string | number)[]
  msg: string
  type: string
}

export type SubmitResult =
  | { status: 'ok'; blob: Blob; filename: string }
  | { status: 'invalid'; errors: TomlFieldError[] }

// A user-added (or uploaded scalar extra) custom field. The 3-way type selector
// drives how `value` serializes as TOML (ADR-0004); list/date are hand-edited
// so they're not offered here.
export type CustomFieldType = 'string' | 'number' | 'boolean'
export interface CustomField {
  key: string
  value: string
  type: CustomFieldType
}

// Build the POST payload from raw string form values: omit empties (TOML has
// no null; empties are simply absent), coerce numeric inputs. Bad numeric text
// is dropped so the backend reports a clean required/type error rather than
// choking on a string. `customFields` serialize as their chosen TOML type;
// `passthrough` carries non-scalar uploaded extras (lists/tables) verbatim so
// they survive the round-trip without a UI (ADR-0004).
export function buildPayload(
  fields: FormField[],
  values: Record<string, string>,
  customFields: CustomField[] = [],
  passthrough: Record<string, unknown> = {},
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...passthrough }
  for (const f of fields) {
    const raw = (values[f.field] ?? '').trim()
    if (raw === '') continue
    if (f.input === 'integer' || f.input === 'number') {
      const n = Number(raw)
      if (Number.isNaN(n)) continue
      out[f.field] = n
    } else {
      out[f.field] = raw
    }
  }
  for (const c of customFields) {
    const key = c.key.trim()
    if (!key) continue
    const raw = c.value.trim()
    if (c.type === 'number') {
      const n = Number(raw)
      if (raw === '' || Number.isNaN(n)) continue
      out[key] = n
    } else if (c.type === 'boolean') {
      out[key] = raw.toLowerCase() === 'true'
    } else {
      if (raw === '') continue
      out[key] = raw
    }
  }
  return out
}

// Split seeded fields (from upload/API-load) into form state: registry fields
// populate scalar inputs; scalar extras become editable custom-field rows;
// non-scalar extras (lists/tables) go to opaque passthrough for round-trip
// preservation.
export function hydrate(
  fields: FormField[],
  seeded: Record<string, unknown>,
): {
  values: Record<string, string>
  customFields: CustomField[]
  passthrough: Record<string, unknown>
} {
  const known = new Set(fields.map((f) => f.field))
  const values: Record<string, string> = {}
  const customFields: CustomField[] = []
  const passthrough: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(seeded)) {
    if (known.has(k)) {
      values[k] = String(v)
    } else if (typeof v === 'boolean') {
      customFields.push({ key: k, value: String(v), type: 'boolean' })
    } else if (typeof v === 'number') {
      customFields.push({ key: k, value: String(v), type: 'number' })
    } else if (typeof v === 'string') {
      customFields.push({ key: k, value: v, type: 'string' })
    } else {
      passthrough[k] = v // list/table — preserved, hand-edited elsewhere
    }
  }
  return { values, customFields, passthrough }
}

// Seed mode: upload. Parse a .toml file's text via the backend tomllib loader.
export async function parseToml(
  form: FormKind,
  text: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`/api/toml/${form}/parse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toml: text }),
  })
  if (res.status === 422) {
    const body = (await res.json()) as { errors: TomlFieldError[] }
    throw new Error(body.errors[0]?.msg ?? 'Could not parse TOML')
  }
  if (!res.ok) throw new Error(`parse failed: ${res.status}`)
  return ((await res.json()) as { fields: Record<string, unknown> }).fields
}

// Seed mode: pull-from-API. Load an existing record's authored fields by id.
export async function loadToml(
  form: FormKind,
  id: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`/api/toml/${form}/load/${encodeURIComponent(id)}`)
  if (res.status === 404) throw new Error(`No ${form} found with id "${id}"`)
  if (!res.ok) throw new Error(`load failed: ${res.status}`)
  return ((await res.json()) as { fields: Record<string, unknown> }).fields
}

export async function postToml(
  form: FormKind,
  payload: Record<string, unknown>,
  filename: string,
): Promise<SubmitResult> {
  const res = await fetch(`/api/toml/${form}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (res.status === 422) {
    const body = (await res.json()) as { errors: TomlFieldError[] }
    return { status: 'invalid', errors: body.errors }
  }
  if (!res.ok) {
    throw new Error(`POST /api/toml/${form} failed: ${res.status}`)
  }
  return { status: 'ok', blob: await res.blob(), filename }
}

// First inline message per field, keyed by loc[0].
export function errorsByField(
  errors: TomlFieldError[],
): Record<string, string> {
  const out: Record<string, string> = {}
  for (const e of errors) {
    const key = String(e.loc[0] ?? '')
    if (key && !(key in out)) out[key] = e.msg
  }
  return out
}
