import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import TerminologyEditor from '../src/components/workspace/TerminologyEditor.vue'
import type { AnalyzeOptions } from '../src/types/verification'

function buildOptions(overrides: Partial<AnalyzeOptions> = {}): AnalyzeOptions {
  return {
    scenario: 'general',
    enableSecurity: true,
    enableSensitive: true,
    enableAdExtreme: false,
    glossary: [],
    bannedWords: [],
    ...overrides
  }
}

function verificationOptionsBytes(options: AnalyzeOptions): number {
  return new TextEncoder().encode(
    JSON.stringify({
      scenario: options.scenario,
      enable_security: options.enableSecurity,
      enable_sensitive: options.enableSensitive,
      enable_ad_extreme: options.enableAdExtreme,
      custom_glossary: options.glossary,
      banned_words: options.bannedWords
    })
  ).byteLength
}

function buildOptionsAtSerializedSize(targetBytes: number): AnalyzeOptions {
  const options = buildOptions({
    scenario: 'technical',
    enableSecurity: false,
    enableSensitive: false,
    enableAdExtreme: true
  })
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

afterEach(() => {
  vi.restoreAllMocks()
})

describe('TerminologyEditor', () => {
  it('adds and removes glossary pairs through complete option snapshots', async () => {
    const wrapper = mount(TerminologyEditor, {
      props: { kind: 'glossary', options: buildOptions() }
    })

    await wrapper.get('#term-original').setValue('AI')
    await wrapper.get('#term-standard').setValue('人工智能')
    await wrapper.get('[data-action="add-glossary"]').trigger('click')

    const added = wrapper.emitted('update:options')?.at(-1)?.[0] as AnalyzeOptions
    expect(added.glossary).toEqual([
      { original: 'AI', standard: '人工智能' }
    ])

    await wrapper.setProps({ options: added })
    await wrapper.get('[aria-label="删除术语 AI"]').trigger('click')

    expect(
      (wrapper.emitted('update:options')?.at(-1)?.[0] as AnalyzeOptions)
        .glossary
    ).toEqual([])
  })

  it('imports banned words and ignores BOM comments and blanks', async () => {
    const wrapper = mount(TerminologyEditor, {
      props: { kind: 'banned', options: buildOptions() }
    })
    const input = wrapper.get('input[type="file"]')
    const file = new File(
      ['\ufeff# comment\n\n最好,第一\n唯一\t顶级'],
      'banned.txt',
      { type: 'text/plain' }
    )
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [file]
    })

    await input.trigger('change')
    await flushPromises()
    await vi.waitFor(() => {
      expect(wrapper.emitted('update:options')).toHaveLength(1)
    })

    expect(
      (wrapper.emitted('update:options')?.at(-1)?.[0] as AnalyzeOptions)
        .bannedWords
    ).toEqual(['最好', '第一', '唯一', '顶级'])
    expect(wrapper.emitted('notify')?.at(-1)).toEqual(['成功导入 4 项'])
  })

  it('passes the detected CSV format through so arrows remain field content', async () => {
    const wrapper = mount(TerminologyEditor, {
      props: { kind: 'glossary', options: buildOptions() }
    })
    const input = wrapper.get('input[type="file"]')
    const file = new File(['AI→ML,人工智能'], 'terms.csv', {
      type: 'text/csv'
    })
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [file]
    })

    await input.trigger('change')
    await flushPromises()
    await vi.waitFor(() => {
      expect(wrapper.emitted('update:options')).toHaveLength(1)
    })

    expect(
      (wrapper.emitted('update:options')?.at(-1)?.[0] as AnalyzeOptions)
        .glossary
    ).toEqual([{ original: 'AI→ML', standard: '人工智能' }])
  })

  it('rejects a manual glossary mutation using the actual scenario and switch context', async () => {
    const options = buildOptionsAtSerializedSize(64 * 1024)
    expect(verificationOptionsBytes(options)).toBe(64 * 1024)
    const wrapper = mount(TerminologyEditor, {
      props: { kind: 'glossary', options }
    })

    await wrapper.get('#term-original').setValue('AI')
    await wrapper.get('#term-standard').setValue('人工智能')
    await wrapper.get('[data-action="add-glossary"]').trigger('click')

    expect(wrapper.emitted('update:options')).toBeUndefined()
    expect(wrapper.get('[role="alert"]').text()).toBe(
      '完整检查设置不能超过 64 KiB。'
    )
  })

  it('accepts exactly 200 astral characters and rejects 201 without mutation', async () => {
    const glossary = mount(TerminologyEditor, {
      props: { kind: 'glossary', options: buildOptions() }
    })
    expect(glossary.get('#term-original').attributes('maxlength')).toBeUndefined()
    expect(glossary.get('#term-standard').attributes('maxlength')).toBeUndefined()
    await glossary.get('#term-original').setValue('😀'.repeat(200))
    await glossary.get('#term-standard').setValue('标准')
    await glossary.get('[data-action="add-glossary"]').trigger('click')
    expect(
      (glossary.emitted('update:options')?.at(-1)?.[0] as AnalyzeOptions)
        .glossary
    ).toHaveLength(1)

    await glossary.get('#term-original').setValue('😀'.repeat(201))
    await glossary.get('#term-standard').setValue('另一个标准')
    await glossary.get('[data-action="add-glossary"]').trigger('click')
    expect(glossary.emitted('update:options')).toHaveLength(1)
    expect(glossary.get('[role="alert"]').text()).toContain('200')

    const banned = mount(TerminologyEditor, {
      props: { kind: 'banned', options: buildOptions() }
    })
    expect(banned.get('#banned-word').attributes('maxlength')).toBeUndefined()
    await banned.get('#banned-word').setValue('😀'.repeat(200))
    await banned.get('[data-action="add-banned"]').trigger('click')
    expect(
      (banned.emitted('update:options')?.at(-1)?.[0] as AnalyzeOptions)
        .bannedWords
    ).toEqual(['😀'.repeat(200)])

    await banned.get('#banned-word').setValue('😀'.repeat(201))
    await banned.get('[data-action="add-banned"]').trigger('click')
    expect(banned.emitted('update:options')).toHaveLength(1)
    expect(banned.get('[role="alert"]').text()).toContain('200')
  })

  it('uses a visible focusable import button and hides the native input from tab order', async () => {
    const wrapper = mount(TerminologyEditor, {
      props: { kind: 'glossary', options: buildOptions() }
    })
    const button = wrapper.get('[data-action="import"]')
    const input = wrapper.get('input[type="file"]')
    const click = vi.spyOn(input.element as HTMLInputElement, 'click')

    expect(button.element.tagName).toBe('BUTTON')
    expect(button.attributes('type')).toBe('button')
    expect(input.attributes('hidden')).toBeDefined()
    expect(input.attributes('tabindex')).toBe('-1')
    expect(input.attributes('aria-hidden')).toBe('true')

    await button.trigger('click')
    expect(click).toHaveBeenCalledTimes(1)
  })

  it('renders imported markup as text rather than unsafe HTML', () => {
    const wrapper = mount(TerminologyEditor, {
      props: {
        kind: 'banned',
        options: buildOptions({
          bannedWords: ['<img src=x onerror=alert(1)>']
        })
      }
    })

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
  })

  it('downloads the BOM-prefixed glossary example', async () => {
    let downloadedBlob: Blob | undefined
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn((blob: Blob) => {
        downloadedBlob = blob
        return 'blob:sample'
      })
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn()
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const wrapper = mount(TerminologyEditor, {
      props: { kind: 'glossary', options: buildOptions() }
    })

    await wrapper.get('[data-action="download-example"]').trigger('click')

    expect(downloadedBlob).toBeDefined()
    const bytes = await new Promise<Uint8Array>((resolve) => {
      const reader = new FileReader()
      reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer))
      reader.readAsArrayBuffer(downloadedBlob!)
    })
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf])
    expect(new TextDecoder().decode(bytes)).toMatch(/^# 原文写法,规范写法/)
  })
})
