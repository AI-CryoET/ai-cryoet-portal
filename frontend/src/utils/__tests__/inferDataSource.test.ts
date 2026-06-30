import { describe, expect, it } from 'vitest'
import {
  buildCompositePayload,
  hydrateComposite,
  inferDataSource,
} from '~/utils/authoring'

describe('inferDataSource', () => {
  it('detects simulation-only signals (single-sided -> lock)', () => {
    expect(inferDataSource({ simulation: {} })).toEqual({ kind: 'simulation' })
    expect(inferDataSource({ md_run: [{ id: 'r1' }] })).toEqual({
      kind: 'simulation',
    })
    expect(inferDataSource({ md_source: { md_run_id: 'r1' } })).toEqual({
      kind: 'simulation',
    })
    expect(
      inferDataSource({ sample: { data_source: 'simulation' } }),
    ).toEqual({ kind: 'simulation' })
  })

  it('detects experimental-only signals (single-sided -> lock)', () => {
    expect(inferDataSource({ freezing: { method: 'HPF' } })).toEqual({
      kind: 'experimental',
    })
    expect(inferDataSource({ milling: { scheme: 'cryo-FIB' } })).toEqual({
      kind: 'experimental',
    })
    expect(inferDataSource({ label: [{ label_target: 'AMPAR' }] })).toEqual({
      kind: 'experimental',
    })
    expect(inferDataSource({ fiducial: { vendor: 'X' } })).toEqual({
      kind: 'experimental',
    })
    expect(inferDataSource({ sample: { project: 'synapse' } })).toEqual({
      kind: 'experimental',
    })
  })

  it('does not treat [chromatin] as a signal (either arm)', () => {
    expect(
      inferDataSource({ sample: { project: 'chromatin' }, chromatin: { buffer: 'x' } }),
    ).toEqual({ kind: 'ambiguous', reason: 'none' })
  })

  it('flags a contradictory file as ambiguous/conflict', () => {
    expect(
      inferDataSource({ simulation: {}, freezing: { method: 'HPF' } }),
    ).toEqual({ kind: 'ambiguous', reason: 'conflict' })
    // data_source says experimental, but a [simulation] block is present.
    expect(
      inferDataSource({ sample: { data_source: 'experimental' }, simulation: {} }),
    ).toEqual({ kind: 'ambiguous', reason: 'conflict' })
  })

  it('returns ambiguous/none when no signal is present', () => {
    expect(inferDataSource({ sample: { project: 'nanogold' } })).toEqual({
      kind: 'ambiguous',
      reason: 'none',
    })
    expect(inferDataSource({})).toEqual({ kind: 'ambiguous', reason: 'none' })
  })

  it('ignores empty blocks (an empty [[label]] is not a signal)', () => {
    expect(inferDataSource({ label: [] })).toEqual({
      kind: 'ambiguous',
      reason: 'none',
    })
  })
})

describe('composite payload + hydrate round-trip', () => {
  it('nests sections, serializes list + repeatable, omits empties', () => {
    const hydrated = hydrateComposite('sample', {
      sample: { sample_id: 'samp1', data_source: 'experimental', project: 'chromatin' },
      chromatin: { linker_pattern: [20, 50, 20], buffer: '2mM MgCl2' },
      milling: { date: '2024-01-02', scheme: 'cryo-FIB' },
      label: [{ label_target: 'AMPAR', aunp_size_nm: [1.4, 2.2] }],
    })
    // data_source is surfaced for arm-locking; the id rides in section values
    // (rendered, drives the placement hint) but is dropped from the payload.
    expect(hydrated.dataSource).toBe('experimental')
    const samp = hydrated.state.sample as { values: Record<string, string> }
    expect(samp.values.sample_id).toBe('samp1')
    // list field is shown as a comma string for editing.
    const chrom = hydrated.state.chromatin as { values: Record<string, string> }
    expect(chrom.values.linker_pattern).toBe('20, 50, 20')

    const payload = buildCompositePayload('sample', hydrated.state, hydrated.passthrough)
    expect(payload).toEqual({
      sample: { project: 'chromatin' }, // id + data_source not written
      chromatin: { linker_pattern: [20, 50, 20], buffer: '2mM MgCl2' },
      milling: { date: '2024-01-02', scheme: 'cryo-FIB' },
      label: [{ label_target: 'AMPAR', aunp_size_nm: [1.4, 2.2] }],
    })
  })

  it('keeps unknown sections as passthrough for round-trip', () => {
    const hydrated = hydrateComposite('sample', {
      sample: { project: 'nanogold' },
      simulation: { dataset_type: 'bulk' },
    })
    expect(hydrated.passthrough).toEqual({ simulation: { dataset_type: 'bulk' } })
    const payload = buildCompositePayload('sample', hydrated.state, hydrated.passthrough)
    expect(payload.simulation).toEqual({ dataset_type: 'bulk' })
  })
})
