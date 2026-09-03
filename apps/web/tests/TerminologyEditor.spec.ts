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
      'banned.csv',
      { type: 'text/csv' }
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
