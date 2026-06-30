import { describe, expect, it } from 'vitest'
import {
  buildPayload,
  buildSectionedPayload,
  hydrate,
  hydrateSections,
  inferDataSource,
  type SectionState,
  type SectionsState,
} from '~/utils/authoring'
import { fieldsFor, fieldsForSection, sectionsFor } from '~/utils/formFields'

const fields = fieldsFor('md_run')

const acqSections = sectionsFor('acquisition')
const acqFields = (s: string) => fieldsForSection('acquisition', s)
const section = (values: Record<string, string>): SectionState => ({
  values,
  customFields: [],
  passthrough: {},
})

describe('buildPayload custom fields', () => {
  it('coerces each custom field to its chosen TOML type', () => {
    const out = buildPayload(fields, { md_run_id: 'run01' }, [
      { key: 'replicate', value: '3', type: 'number' },
      { key: 'is_final', value: 'true', type: 'boolean' },
      { key: 'note', value: 'hi', type: 'string' },
    ])
    expect(out).toEqual({
      md_run_id: 'run01',
      replicate: 3,
      is_final: true,
      note: 'hi',
    })
  })

  it('drops empty keys and non-numeric number values', () => {
    const out = buildPayload(fields, {}, [
      { key: '', value: 'x', type: 'string' },
      { key: 'bad', value: 'abc', type: 'number' },
    ])
    expect(out).toEqual({})
  })

  it('carries passthrough (non-scalar) extras verbatim', () => {
    const out = buildPayload(fields, {}, [], { tags: ['a', 'b'] })
    expect(out).toEqual({ tags: ['a', 'b'] })
  })
})

describe('buildSectionedPayload (acquisition)', () => {
  it('nests tables, drops empties, gates md_source on data source', () => {
    const state: SectionsState = {
      acquisition: section({ acquisition_id: 'Pos1', resolution: '3.4' }),
      md_source: section({ md_run_id: 'run01' }),
      tilt_series: [
        section({ tilt_series_id: 'ts_raw', derived_from: 'Frames' }),
        section({}), // entirely empty entry is dropped
      ],
    }
    // Experimental: md_source omitted even though it has a value.
    expect(
      buildSectionedPayload(acqSections, acqFields, state, 'experimental'),
    ).toEqual({
      acquisition: { acquisition_id: 'Pos1', resolution: 3.4 },
      tilt_series: [{ tilt_series_id: 'ts_raw', derived_from: 'Frames' }],
    })
    // Simulation: md_source included.
    expect(
      buildSectionedPayload(acqSections, acqFields, state, 'simulation').md_source,
    ).toEqual({ md_run_id: 'run01' })
  })

  it('coerces booleans client-side; selects pass through (backend coerces)', () => {
    const state: SectionsState = {
      acquisition: section({
        acquisition_id: 'Pos1',
        phase_plate: 'true',
        acquisition_quality: '4',
      }),
      tilt_series: [],
    }
    const out = buildSectionedPayload(
      acqSections,
      acqFields,
      state,
      'experimental',
    ).acquisition as Record<string, unknown>
    expect(out.phase_plate).toBe(true)
    // Quality is a string-valued select; pydantic coerces '4' → int 4 + enforces 1–5.
    expect(out.acquisition_quality).toBe('4')
  })
})

describe('hydrateSections + inferDataSource (acquisition)', () => {
  it('splits an uploaded file into sections and dealiases tilt-series id', () => {
    const seeded = {
      acquisition: { acquisition_id: 'Pos1', resolution: 3.4 },
      md_source: { md_run_id: 'run01' },
      tilt_series: [{ id: 'ts_raw', derived_from: 'Frames' }],
    }
    const state = hydrateSections(acqSections, acqFields, seeded)
    expect((state.acquisition as SectionState).values.resolution).toBe('3.4')
    expect((state.tilt_series as SectionState[])[0].values.tilt_series_id).toBe(
      'ts_raw',
    )
    expect(inferDataSource(acqSections, seeded)).toBe('simulation')
  })

  it('infers experimental when no md_source is present', () => {
    expect(
      inferDataSource(acqSections, { acquisition: { acquisition_id: 'Pos1' } }),
    ).toBe('experimental')
  })
})

describe('hydrate', () => {
  it('splits registry fields, scalar extras, and non-scalar passthrough', () => {
    const { values, customFields, passthrough } = hydrate(fields, {
      seed: 42,
      custom_note: 'keep me',
      flag: false,
      tags: ['a', 'b'],
    })
    expect(values).toEqual({ seed: '42' })
    expect(customFields).toEqual([
      { key: 'custom_note', value: 'keep me', type: 'string' },
      { key: 'flag', value: 'false', type: 'boolean' },
    ])
    expect(passthrough).toEqual({ tags: ['a', 'b'] })
  })
})
