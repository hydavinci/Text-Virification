import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import VerificationSettings from '../src/components/workspace/VerificationSettings.vue'
import PrivacyDialog from '../src/components/workspace/PrivacyDialog.vue'
import type { AnalyzeOptions } from '../src/types/verification'
import { scenarioCatalogKey } from '../src/api/scenarioCatalog'
import { scenarioCatalogFixture } from './fixtures/scenarioCatalog'

function verificationOptionsBytes(options: AnalyzeOptions): number {
  return new TextEncoder().encode(
    JSON.stringify({
      scenario: options.scenario,
      enable_security: options.enableSecurity,
      enable_sensitive: options.enableSensitive,
      enable_ad_extreme: options.enableAdExtreme,
      ocr_language: options.ocrLanguage ?? 'zh',
      enable_extended_rules: options.enableExtendedRules ?? false,
      enable_semantic_discovery: options.enableSemanticDiscovery ?? false,
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
  it('shows the rule package name without its internal version', async () => {
    const wrapper = mount(VerificationSettings, {
      props: { options: buildOptions() },
      global: { provide: { [scenarioCatalogKey as symbol]: async () => scenarioCatalogFixture() } }
    })
    await flushPromises()
    expect(wrapper.get('.scenario-rules > p strong').text()).toBe('通用文档规则包')
    wrapper.unmount()
  })

  it('omits the redundant setup caption while keeping the selector accessible', async () => {
    const wrapper = mount(VerificationSettings, {
      props: { options: buildOptions(), compact: true },
      global: { provide: { [scenarioCatalogKey as symbol]: async () => scenarioCatalogFixture() } }
    })
    await flushPromises()
    expect(wrapper.find('.scenario-header .scenario-field > span').exists()).toBe(false)
    expect(wrapper.get('select[aria-label="文档场景"]').element).toHaveProperty('value', 'general')
    await wrapper.setProps({ compact: false })
    expect(wrapper.get('.scenario-header .scenario-field > span').text()).toBe('文档场景')
    wrapper.unmount()
  })

  it('shows only the selected server rule package, including compact setup', async () => {
    const options = { ...buildOptions(), scenario: 'academic' as const }
    const wrapper = mount(VerificationSettings, {
      props: { options, compact: true },
      global: { provide: { [scenarioCatalogKey as symbol]: async () => scenarioCatalogFixture() } }
    })
    await flushPromises()
    const checklist = wrapper.get('[aria-label="场景规则"]')
    expect(checklist.text()).toContain('学术论文专用检查')
    expect(checklist.text()).toContain('完整文本')
    expect(checklist.text()).not.toContain('商务文档专用检查')
    expect(checklist.text()).not.toContain('扩展英文检查')
    await wrapper.setProps({ options: { ...options, scenario: 'business', enableExtendedRules: true } })
    expect(checklist.text()).toContain('商务文档专用检查')
    expect(checklist.text()).not.toContain('学术论文专用检查')
    expect(checklist.text()).toContain('扩展英文检查')
    expect(wrapper.emitted('update:options')).toBeUndefined()
    wrapper.unmount()
  })

  it('shows a failed catalog explicitly and can retry without changing options', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(scenarioCatalogFixture())
    const wrapper = mount(VerificationSettings, {
      props: { options: buildOptions() },
      global: { provide: { [scenarioCatalogKey as symbol]: load } }
    })
    await flushPromises()
    expect(wrapper.text()).toContain('规则清单加载失败')
    await wrapper.get('[aria-label="重试加载规则清单"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('通用文档的独立规则')
    expect(wrapper.text()).not.toContain('规则清单加载失败')
    expect(wrapper.emitted('update:options')).toBeUndefined()
    wrapper.unmount()
  })

  it('discloses discovery excerpts beyond rule hits in the privacy dialog', () => {
    const wrapper = mount(PrivacyDialog, { props: { open: true } })
    expect(wrapper.text()).toContain('隐私说明')
    expect(wrapper.text()).toContain('抽样')
    expect(wrapper.text()).toContain('费用')
    wrapper.unmount()
  })

  it('makes semantic discovery an explicit informed opt-in', async () => {
    const options = buildOptions()
    const wrapper = mount(VerificationSettings, { props: { options } })
    expect(wrapper.get('#enable-semantic-discovery').element).toHaveProperty('checked', false)
    expect(wrapper.text()).toContain('局部片段')
    expect(wrapper.text()).toContain('费用')
    expect(wrapper.text()).toContain('不自动')
    await wrapper.get('#enable-semantic-discovery').setValue(true)
    expect(wrapper.emitted('update:options')?.[0]).toEqual([
      { ...options, enableSemanticDiscovery: true }
    ])
  })

  it('offers English spelling and grammar with extended formatting as an opt-in', async () => {
    const options = buildOptions()
    const wrapper = mount(VerificationSettings, { props: { options } })
    expect(wrapper.get('#enable-extended-rules').element).toHaveProperty('checked', false)
    expect(wrapper.get('label[for="enable-extended-rules"]').text()).toContain('英文拼写与语法')
    expect(wrapper.text()).toContain('英文词典拼写与保守语法检查')
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
