import type { FormField, FormKind, FormSection } from '~/utils/formFields'

export type DataSource = 'experimental' | 'simulation'

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
    } else if (f.input === 'boolean') {
      out[f.field] = raw.toLowerCase() === 'true'
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
// Acquisition identity is composite, so a sampleId is passed through as a query
// param (mirrors the acquisition detail route's sampleId search param).
export async function loadToml(
  form: FormKind,
  id: string,
  sampleId?: string,
): Promise<Record<string, unknown>> {
  const qs = sampleId ? `?sample_id=${encodeURIComponent(sampleId)}` : ''
  const res = await fetch(
    `/api/toml/${form}/load/${encodeURIComponent(id)}${qs}`,
  )
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

// First inline message per field, keyed by the full dotted loc path
// (e.g. 'seed', 'acquisition.acquisition_quality', 'tilt_series.0.id'). The
// renderer looks each field up by its section path; errors with no matching
// field (whole-record cross-ref failures, loc=[]) fall through to a summary.
export function errorsByField(
  errors: TomlFieldError[],
): Record<string, string> {
  const out: Record<string, string> = {}
  for (const e of errors) {
    const key = e.loc.join('.')
    if (key && !(key in out)) out[key] = e.msg
  }
  return out
}

// ── Sectioned forms (acquisition): one block per TOML table ─────────────────

export interface SectionState {
  values: Record<string, string>
  customFields: CustomField[]
  passthrough: Record<string, unknown>
}

// Per-section state keyed by section name; repeatable sections hold an array.
export type SectionsState = Record<string, SectionState | SectionState[]>

export function emptySection(): SectionState {
  return { values: {}, customFields: [], passthrough: {} }
}

// Which data_source a seeded file implies: present iff a gated section is
// present (md_source ⇒ simulation). Defaults to experimental otherwise.
export function inferDataSource(
  sections: FormSection[],
  seeded: Record<string, unknown>,
): DataSource {
  for (const s of sections) {
    if (s.requiresDataSource && seeded[s.section] != null) {
      return s.requiresDataSource as DataSource
    }
  }
  return 'experimental'
}

// Rename uploaded TOML keys back to model field names where they differ
// (tilt_series authors its id as `id`, the field is `tilt_series_id`).
function dealias(
  fields: FormField[],
  raw: Record<string, unknown>,
): Record<string, unknown> {
  const out = { ...raw }
  for (const f of fields) {
    if (f.alias && f.alias in out && !(f.field in out)) {
      out[f.field] = out[f.alias]
      delete out[f.alias]
    }
  }
  return out
}

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {}
}

// Seed every section from a parsed/loaded file. Root sections read top-level
// keys; named sections read their table; repeatable sections read their array.
export function hydrateSections(
  sections: FormSection[],
  fieldsFor: (section: string) => FormField[],
  seeded: Record<string, unknown>,
): SectionsState {
  const state: SectionsState = {}
  for (const s of sections) {
    const fields = fieldsFor(s.section)
    if (s.repeatable) {
      const arr = Array.isArray(seeded[s.section])
        ? (seeded[s.section] as unknown[])
        : []
      state[s.section] = arr.map((entry) => {
        const { values, customFields, passthrough } = hydrate(
          fields,
          dealias(fields, asRecord(entry)),
        )
        return { values, customFields, passthrough }
      })
    } else {
      const src = s.root ? seeded : asRecord(seeded[s.section])
      const { values, customFields, passthrough } = hydrate(
        fields,
        dealias(fields, src),
      )
      state[s.section] = { values, customFields, passthrough }
    }
  }
  return state
}

// Build the nested POST payload from section state. Gated sections whose
// data_source is inactive are omitted; empty named sections / repeatable
// entries are dropped so the file carries only filled tables.
export function buildSectionedPayload(
  sections: FormSection[],
  fieldsFor: (section: string) => FormField[],
  state: SectionsState,
  dataSource: DataSource,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const s of sections) {
    if (s.requiresDataSource && s.requiresDataSource !== dataSource) continue
    const fields = fieldsFor(s.section)
    if (s.repeatable) {
      const entries = (state[s.section] as SectionState[] | undefined) ?? []
      const built = entries
        .map((e) => buildPayload(fields, e.values, e.customFields, e.passthrough))
        .filter((o) => Object.keys(o).length > 0)
      if (built.length) out[s.section] = built
    } else {
      const st = (state[s.section] as SectionState | undefined) ?? emptySection()
      const obj = buildPayload(fields, st.values, st.customFields, st.passthrough)
      if (s.root) Object.assign(out, obj)
      else if (Object.keys(obj).length) out[s.section] = obj
    }
  }
  return out
}

// md_source.md_run_id suggestions: the sample's known runs (free text still ok).
export async function fetchMdRunIds(sampleId: string): Promise<string[]> {
  const res = await fetch(`/api/toml/md-run-ids/${encodeURIComponent(sampleId)}`)
  if (!res.ok) return []
  const ids = ((await res.json()) as { ids?: string[] }).ids
  return Array.isArray(ids) ? ids : []
}
