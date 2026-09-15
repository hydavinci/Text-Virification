import { describe, expect, it, vi } from 'vitest'

import { fetchScenarioCatalog } from '../src/api/scenarioCatalog'
import { scenarioCatalogFixture } from './fixtures/scenarioCatalog'

describe('scenario catalog API', () => {
  it('fetches the running server catalog including rule conditions', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(
      JSON.stringify({ scenarios: scenarioCatalogFixture() })
    ))
    const result = await fetchScenarioCatalog(fetchImpl)
    expect(fetchImpl.mock.calls[0]?.[0]).toBe('/api/v1/scenarios')
    expect(result.find((profile) => profile.id === 'academic')?.rules[0]).toMatchObject({
      id: 'scenario.academic.example',
      requires_complete_structure: true,
      manual_only: true
    })
  })

  it.each(['missing', 'duplicate', 'wrong-rule-owner', 'invalid-condition'])(
    'rejects a %s catalog rather than inventing fallback rules', async (failure) => {
      const profiles = scenarioCatalogFixture()
      if (failure === 'missing') profiles.pop()
      if (failure === 'duplicate') profiles[5] = profiles[0]!
      if (failure === 'wrong-rule-owner') profiles[1]!.rules[0]!.id = 'scenario.legal.example'
      const payload = JSON.parse(JSON.stringify({ scenarios: profiles }))
      if (failure === 'invalid-condition') payload.scenarios[1].rules[0].requires_complete_structure = 'true'
      const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(payload)))
      await expect(fetchScenarioCatalog(fetchImpl)).rejects.toThrow('规则清单')
    }
  )

  it('surfaces server errors', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('unavailable', { status: 503 }))
    await expect(fetchScenarioCatalog(fetchImpl)).rejects.toThrow()
  })
})
