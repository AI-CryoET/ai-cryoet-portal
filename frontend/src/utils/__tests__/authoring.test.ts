import { describe, expect, it } from 'vitest'
import { buildPayload, hydrate } from '~/utils/authoring'
import { fieldsFor } from '~/utils/formFields'

const fields = fieldsFor('md_run')

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
