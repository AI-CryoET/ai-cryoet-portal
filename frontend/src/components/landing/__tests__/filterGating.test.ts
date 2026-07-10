import { describe, expect, it } from 'vitest'
import type { SamplesSearchParams } from '~/utils/samplesSearch'
import { computeDisabledGroups } from '../filterGating'

const search = (o: Record<string, unknown>) => o as SamplesSearchParams

describe('computeDisabledGroups — synapse ⇒ experimental (ADR-0003)', () => {
  it('disables the simulation arm when project is synapse', () => {
    expect(computeDisabledGroups(search({ project: ['synapse'] }))).toContain(
      'simulation',
    )
  })

  it('keeps the simulation arm for chromatin (unconstrained project)', () => {
    expect(
      computeDisabledGroups(search({ project: ['chromatin'] })),
    ).not.toContain('simulation')
  })

  it('keeps the simulation arm when synapse is mixed with an unconstrained project', () => {
    expect(
      computeDisabledGroups(search({ project: ['synapse', 'chromatin'] })),
    ).not.toContain('simulation')
  })

  it('does not disable the experimental-only groups for synapse', () => {
    const disabled = computeDisabledGroups(search({ project: ['synapse'] }))
    expect(disabled).not.toContain('labels')
    expect(disabled).not.toContain('freezing')
  })
})
