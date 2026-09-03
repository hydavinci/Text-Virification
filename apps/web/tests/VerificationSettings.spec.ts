import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import VerificationSettings from '../src/components/workspace/VerificationSettings.vue'
import type { AnalyzeOptions } from '../src/types/verification'

function buildOptions(): AnalyzeOptions {
  return {
    scenario: 'general',
    enableSecurity: true,
    enableSensitive: true,
    enableAdExtreme: false,
    glossary: [{ original: 'AI', standard: '人工智能' }],
    bannedWords: ['最好']
  }
}

describe('VerificationSettings', () => {
  it('offers all six scenarios and emits a complete immutable option snapshot', async () => {
    const options = buildOptions()
    const wrapper = mount(VerificationSettings, { props: { options } })

    expect(wrapper.findAll('[data-scenario]')).toHaveLength(6)
    await wrapper.get('[data-scenario="academic"]').trigger('click')

    expect(wrapper.emitted('update:options')?.[0]).toEqual([
      {
        ...options,
        scenario: 'academic',
        glossary: [{ original: 'AI', standard: '人工智能' }],
        bannedWords: ['最好']
      }
    ])
    expect(options.scenario).toBe('general')
  })

  it('updates the three compliance switches independently', async () => {
    const options = buildOptions()
    const wrapper = mount(VerificationSettings, { props: { options } })

    await wrapper.get('#enable-security').setValue(false)
    await wrapper.setProps({
      options: wrapper.emitted('update:options')?.at(-1)?.[0] as AnalyzeOptions
    })
    await wrapper.get('#enable-sensitive').setValue(false)
    await wrapper.setProps({
      options: wrapper.emitted('update:options')?.at(-1)?.[0] as AnalyzeOptions
    })
    await wrapper.get('#enable-ad-extreme').setValue(true)

    expect(wrapper.emitted('update:options')?.map(([value]) => value)).toEqual([
      { ...options, enableSecurity: false },
      {
        ...options,
        enableSecurity: false,
        enableSensitive: false
      },
      {
        ...options,
        enableSecurity: false,
        enableSensitive: false,
        enableAdExtreme: true
      }
    ])
  })
})
