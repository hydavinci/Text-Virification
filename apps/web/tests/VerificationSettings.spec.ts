import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import VerificationSettings from '../src/components/workspace/VerificationSettings.vue'
import type { AnalyzeOptions } from '../src/types/verification'

function verificationOptionsBytes(options: AnalyzeOptions): number {
  return new TextEncoder().encode(
    JSON.stringify({
      scenario: options.scenario,
      enable_security: options.enableSecurity,
      enable_sensitive: options.enableSensitive,
      enable_ad_extreme: options.enableAdExtreme,
      ocr_language: options.ocrLanguage ?? 'zh',
      enable_extended_rules: options.enableExtendedRules ?? false,
      custom_glossary: options.glossary,
      banned_words: options.bannedWords
    })
  ).byteLength
}

function buildOptionsAtSerializedSize(targetBytes: number): AnalyzeOptions {
  const options: AnalyzeOptions = {
    scenario: 'general',
    enableSecurity: true,
    enableSensitive: true,
    enableAdExtreme: false,
    glossary: [],
    bannedWords: []
  }
  const requiredValueBytes = targetBytes - verificationOptionsBytes(options)

  for (let count = 1; count <= 500; count += 1) {
    const totalWordLength = requiredValueBytes - 3 * count + 1
    if (totalWordLength < 3 * count || totalWordLength > 200 * count) {
      continue
    }
    let remaining = totalWordLength
    options.bannedWords = Array.from({ length: count }, (_, index) => {
      const slotsAfter = count - index - 1
      const length = Math.min(200, remaining - 3 * slotsAfter)
      remaining -= length
      return `${index.toString(36).padStart(3, '0')}${'x'.repeat(length - 3)}`
    })
    return options
  }

  throw new Error('Unable to construct boundary options.')
}

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
  it('offers extended formatting rules as an opt-in setting', async () => {
    const options = buildOptions()
    const wrapper = mount(VerificationSettings, { props: { options } })
    expect(wrapper.get('#enable-extended-rules').element).toHaveProperty('checked', false)
    await wrapper.get('#enable-extended-rules').setValue(true)
    expect(wrapper.emitted('update:options')?.[0]).toEqual([
      { ...options, enableExtendedRules: true }
    ])
  })

  it('selects Japanese OCR without changing proofreading or compliance settings', async () => {
    const options = buildOptions()
    const wrapper = mount(VerificationSettings, { props: { options } })
    await wrapper.get('[aria-label="OCR 识别语言"]').setValue('ja')
    expect(wrapper.emitted('update:options')?.[0]).toEqual([
      { ...options, ocrLanguage: 'ja' }
    ])
    expect(wrapper.text()).toContain('不包含日文纠错')
  })

  it('offers all six scenarios and emits a complete immutable option snapshot', async () => {
    const options = buildOptions()
    const wrapper = mount(VerificationSettings, { props: { options } })

    expect(wrapper.findAll('[data-scenario]')).toHaveLength(6)
    await wrapper.get('[aria-label="文档场景"]').setValue('academic')

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

  it('rejects a settings change that would exceed the complete 64 KiB snapshot', async () => {
    const options = buildOptionsAtSerializedSize(64 * 1024)
    expect(verificationOptionsBytes(options)).toBe(64 * 1024)
    const wrapper = mount(VerificationSettings, { props: { options } })

    await wrapper.get('[aria-label="文档场景"]').setValue('technical')

    expect(wrapper.emitted('update:options')).toBeUndefined()
    expect(wrapper.get('[role="alert"]').text()).toBe(
      '完整检查设置不能超过 64 KiB。'
    )
  })
})
