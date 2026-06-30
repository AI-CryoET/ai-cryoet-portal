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

// Build the POST payload from raw string form values: omit empties (TOML has
// no null; empties are simply absent), coerce numeric inputs. Bad numeric text
// is dropped so the backend reports a clean required/type error rather than
// choking on a string.
export function buildPayload(
  fields: FormField[],
  values: Record<string, string>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
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
  return out
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
