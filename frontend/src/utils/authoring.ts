import {
  fieldsForSection,
  sectionsFor,
  type DataSource,
  type FormField,
  type FormKind,
  type FormSection,
} from '~/utils/formFields'

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
    if (f.input === 'multiselect') {
      // Cross-ref list (tomogram derived_from): stored comma-joined in form
      // state — ids are IdStr (no commas), so split round-trips losslessly.
      const arr = raw.split(',').map((s) => s.trim()).filter(Boolean)
      if (arr.length) out[f.field] = arr
    } else if (f.input === 'boolean') {
      out[f.field] = raw.toLowerCase() === 'true'
    } else {
      const v = coerceValue(f.input, raw)
      if (v === undefined) continue
      if (Array.isArray(v) && v.length === 0) continue
      out[f.field] = v
    }
  }
  applyCustomFields(out, customFields)
  return out
}

// Merge custom-field rows into a payload object, coercing each to its chosen
// TOML type (ADR-0004). Shared by the flat and composite payload builders.
export function applyCustomFields(
  out: Record<string, unknown>,
  customFields: CustomField[],
): void {
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
}

// Classify an unregistered seeded value as an editable custom field (scalar)
// or `undefined` (list/table — not custom-field-editable). Shared by `hydrate`
// and `splitEntry`, which differ only in what they do with the `undefined` case.
function classifyExtra(k: string, v: unknown): CustomField | undefined {
  if (typeof v === 'boolean') return { key: k, value: String(v), type: 'boolean' }
  if (typeof v === 'number') return { key: k, value: String(v), type: 'number' }
  if (typeof v === 'string') return { key: k, value: v, type: 'string' }
  return undefined
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
  const known = new Map(fields.map((f) => [f.field, f]))
  const values: Record<string, string> = {}
  const customFields: CustomField[] = []
  const passthrough: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(seeded)) {
    const f = known.get(k)
    if (f) {
      // A 'list' field is shown comma-joined for editing; everything else is
      // stringified.
      values[k] =
        f.input === 'list' && Array.isArray(v) ? v.join(', ') : String(v)
      continue
    }
    const extra = classifyExtra(k, v)
    if (extra) customFields.push(extra)
    else passthrough[k] = v // list/table — preserved, hand-edited elsewhere
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
// param (mirrors the acquisition detail route's sampleId search param). `path`
// is the on-disk directory holding the record's TOML (null if unknown) — used
// by the "save to file share" action to know where to write it back.
//
// `source` records where the seed came from: 'disk' means the backend read the
// live on-disk file (fields are fresh and `baseline` is its raw text, used for
// the optimistic-concurrency byte-compare on save); 'catalog' means it fell back
// to the DB reconstruction (may lag the file → the renderer warns; no baseline).
export async function loadToml(
  form: FormKind,
  id: string,
  sampleId?: string,
): Promise<{
  fields: Record<string, unknown>
  path: string | null
  source: 'disk' | 'catalog'
  baseline: string | null
}> {
  const qs = sampleId ? `?sample_id=${encodeURIComponent(sampleId)}` : ''
  const res = await fetch(
    `/api/toml/${form}/load/${encodeURIComponent(id)}${qs}`,
  )
  if (res.status === 404) throw new Error(`No ${form} found with id "${id}"`)
  if (!res.ok) throw new Error(`load failed: ${res.status}`)
  const json = (await res.json()) as {
    fields: Record<string, unknown>
    path?: string | null
    source?: 'disk' | 'catalog'
    baseline?: string | null
  }
  return {
    fields: json.fields,
    path: json.path ?? null,
    source: json.source ?? 'catalog',
    baseline: json.baseline ?? null,
  }
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
// (e.g. 'seed', 'acquisition.acquisition_quality', 'tilt_series.0.id',
// 'label.0.aunp_size_nm'). The renderer looks each field up by its section
// path; an error with no matching field (whole-record cross-ref failures,
// loc=[] -> key '') falls through to a record-level summary.
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

// Like errorsByField, but keeps the empty-loc key ('') so a composite form can
// surface a model-level error (e.g. a cross-section invariant) as a general
// message rather than dropping it.
export function errorsByPath(
  errors: TomlFieldError[],
): Record<string, string> {
  const out: Record<string, string> = {}
  for (const e of errors) {
    const key = e.loc.join('.')
    if (!(key in out)) out[key] = e.msg
  }
  return out
}

// ── Sectioned forms (md_run / acquisition): one block per TOML table ─────────
// The generic renderer drives these: a root section is a flat file (md_run);
// named + repeatable sections compose acquisition.toml.

export interface SectionState {
  values: Record<string, string>
  customFields: CustomField[]
  passthrough: Record<string, unknown>
  // Present when the file was loaded → read-only (ADR-0004 immutability).
  // Session-added entries are unlocked. Does not affect the built payload.
  locked?: boolean
}

// Per-section state keyed by section name; repeatable sections hold an array.
export type SectionsState = Record<string, SectionState | SectionState[]>

export function emptySection(): SectionState {
  return { values: {}, customFields: [], passthrough: {} }
}

// Which data_source a seeded sectioned file implies: present iff a gated
// section is present (md_source ⇒ simulation). Defaults to experimental.
export function inferSectionedDataSource(
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
      // Every loaded entry of an immutable section is read-only (append-only).
      state[s.section] = arr.map((entry) => ({
        ...hydrate(fields, dealias(fields, asRecord(entry))),
        locked: s.immutableOnLoad,
      }))
    } else {
      const present = !s.root && seeded[s.section] != null
      const src = s.root ? seeded : asRecord(seeded[s.section])
      state[s.section] = {
        ...hydrate(fields, dealias(fields, src)),
        // A loaded named entry (raw_tomogram) is read-only; an absent one
        // stays editable so the user can author it.
        locked: s.immutableOnLoad && present,
      }
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

// ── Composite (sectioned) form state: sample ─────────────────────────────────
// The sample form posts nested `{section: data}` and renders per-section, with
// repeatable array sections. One section instance is a set of scalar values
// plus its custom/extra fields. A repeatable section holds an array of these.

export interface SectionEntry {
  values: Record<string, string>
  custom: CustomField[]
}
export type CompositeSection = SectionEntry | SectionEntry[]

export const emptyEntry = (): SectionEntry => ({ values: {}, custom: [] })

// Coerce a raw string input to its TOML value by the field's input type.
// Numerics drop on NaN (the backend then reports a clean type error); lists
// split on commas, numeric tokens becoming numbers; text/select/date pass
// through as strings (the backend parses dates).
function coerceValue(input: string, raw: string): unknown {
  if (input === 'integer' || input === 'number') {
    const n = Number(raw)
    return Number.isNaN(n) ? undefined : n
  }
  if (input === 'list') {
    return raw
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s !== '')
      .map((tok) => {
        const n = Number(tok)
        return Number.isNaN(n) ? tok : n
      })
  }
  return raw
}

// Build one section object from its fields + entry, omitting empties. The
// intended-id and derived fields are collected for the UI but never written.
export function buildSectionObject(
  fields: FormField[],
  entry: SectionEntry,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of fields) {
    if (f.derived || f.isId) continue
    const raw = (entry.values[f.field] ?? '').trim()
    if (raw === '') continue
    const v = coerceValue(f.input, raw)
    if (v === undefined) continue
    if (Array.isArray(v) && v.length === 0) continue
    out[f.field] = v
  }
  applyCustomFields(out, entry.custom)
  return out
}

// Nested payload for a composite form. The primary (first non-repeatable)
// section is always included so a missing required field (project) surfaces as
// a backend 422 rather than being silently dropped. Unknown uploaded sections
// ride along in `passthrough` for round-trip preservation.
export function buildCompositePayload(
  form: FormKind,
  state: Record<string, CompositeSection>,
  passthrough: Record<string, unknown> = {},
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...passthrough }
  const sections = sectionsFor(form)
  const primary = sections.find((s) => !s.repeatable)?.section
  for (const s of sections) {
    const fields = fieldsForSection(form, s.section)
    const st = state[s.section]
    if (s.repeatable) {
      const entries = (Array.isArray(st) ? st : [])
        .map((e) => buildSectionObject(fields, e))
        .filter((o) => Object.keys(o).length > 0)
      if (entries.length) out[s.section] = entries
    } else {
      const obj = buildSectionObject(fields, (st as SectionEntry) ?? emptyEntry())
      if (Object.keys(obj).length > 0 || s.section === primary) out[s.section] = obj
    }
  }
  return out
}

function splitEntry(fields: FormField[], obj: Record<string, unknown>): SectionEntry {
  const byName = new Map(fields.map((f) => [f.field, f]))
  const entry = emptyEntry()
  for (const [k, v] of Object.entries(obj)) {
    const f = byName.get(k)
    if (f) {
      if (f.derived) continue // derived (e.g. data_source) is not an input
      // The is_id field IS rendered (and drives the placement hint); it's just
      // excluded from the posted payload by buildSectionObject.
      entry.values[k] =
        f.input === 'list' && Array.isArray(v) ? v.join(', ') : String(v)
      continue
    }
    const extra = classifyExtra(k, v)
    if (extra) entry.custom.push(extra)
    // ponytail: a non-scalar section-level extra (list/table) is dropped — no
    // per-section UI for it; add passthrough-by-section only if real data needs it.
  }
  return entry
}

export interface HydratedComposite {
  state: Record<string, CompositeSection>
  passthrough: Record<string, unknown>
  dataSource?: DataSource
}

// Split a seeded (uploaded/API-loaded) object into composite section state.
// Registry sections become scalar/custom entries (the is_id field included, so
// the placement hint reflects a loaded id); unknown sections go to passthrough.
// data_source is derived (never an input) but surfaced so the caller can lock
// the arm from a record.
export function hydrateComposite(
  form: FormKind,
  seeded: Record<string, unknown>,
): HydratedComposite {
  const sections = sectionsFor(form)
  const known = new Map(sections.map((s) => [s.section, s]))
  const state: Record<string, CompositeSection> = {}
  for (const s of sections) state[s.section] = s.repeatable ? [] : emptyEntry()
  const passthrough: Record<string, unknown> = {}
  let dataSource: DataSource | undefined

  for (const [name, raw] of Object.entries(seeded)) {
    const s = known.get(name)
    if (!s) {
      passthrough[name] = raw
      continue
    }
    const fields = fieldsForSection(form, name)
    if (s.repeatable) {
      const arr = Array.isArray(raw) ? raw : [raw]
      state[name] = arr
        .filter((it) => it && typeof it === 'object')
        .map((it) => splitEntry(fields, it as Record<string, unknown>))
    } else if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
      const obj = raw as Record<string, unknown>
      state[name] = splitEntry(fields, obj)
      const ds = obj['data_source']
      if (ds === 'experimental' || ds === 'simulation') dataSource = ds
    }
  }
  return { state, passthrough, dataSource }
}

// ── Reverse-infer the data source from a parsed file (ADR-0004) ──────────────
// Single-sided signals -> infer + lock; both sides -> ambiguous/conflict (the
// form warns and leaves the toggle editable); neither -> ambiguous/none (the
// user picks). [chromatin] is *not* a signal — chromatin can be either arm.
export type InferResult =
  | { kind: DataSource }
  | { kind: 'ambiguous'; reason: 'conflict' | 'none' }

const SIM_BLOCKS = ['simulation', 'md_run', 'md_source']
const EXP_BLOCKS = ['freezing', 'milling', 'label', 'fiducial']

function blockPresent(parsed: Record<string, unknown>, key: string): boolean {
  const v = parsed[key]
  if (v == null) return false
  // A repeatable block ([[md_run]]) signals only with entries; a table
  // ([simulation], [md_source]) signals by mere presence, even if empty.
  if (Array.isArray(v)) return v.length > 0
  return true
}

function sampleField(parsed: Record<string, unknown>, key: string): unknown {
  const s = parsed['sample']
  return s && typeof s === 'object' ? (s as Record<string, unknown>)[key] : undefined
}

export function inferDataSource(parsed: Record<string, unknown>): InferResult {
  const ds = sampleField(parsed, 'data_source')
  const sim = SIM_BLOCKS.some((b) => blockPresent(parsed, b)) || ds === 'simulation'
  const exp =
    EXP_BLOCKS.some((b) => blockPresent(parsed, b)) ||
    sampleField(parsed, 'project') === 'synapse' ||
    ds === 'experimental'
  if (sim && exp) return { kind: 'ambiguous', reason: 'conflict' }
  if (sim) return { kind: 'simulation' }
  if (exp) return { kind: 'experimental' }
  return { kind: 'ambiguous', reason: 'none' }
}
