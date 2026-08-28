import { describe, expect, it, vi } from 'vitest'

import { createVerificationApi } from '../src/api/verification'
import type { VerificationResult } from '../src/types/verification'

const resultPayload: VerificationResult = {
  success: true,
  filename: 'sample.txt',
  text: '这是测试。',
  stats: {
    char_count: 5,
    char_count_no_space: 5,
    line_count: 1,
    paragraph_count: 1,
    language: 'zh',
    primary_count: 5,
    primary_label: '总字数'
  },
  issues: [],
  summary: {
    total: 0,
    by_type: {},
    by_severity: {},
    by_rule: {},
    by_layer: {}
  },
  file_id: null,
  file_ext: null,
  scenario: 'technical'
}

describe('createVerificationApi', () => {
  it('submits direct text with all verification settings', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => resultPayload
    })
    const api = createVerificationApi(fetchMock as typeof fetch)

    const result = await api.analyzeText('这是测试。', {
      scenario: 'technical',
      enableSecurity: true,
      enableSensitive: false,
      enableAdExtreme: true,
      glossary: [{ original: 'AI', standard: '人工智能' }],
      bannedWords: ['最好']
    })

    expect(result.scenario).toBe('technical')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/analyze', expect.objectContaining({
      method: 'POST'
    }))
    const body = fetchMock.mock.calls[0]?.[1]?.body as FormData
    expect(body.get('text')).toBe('这是测试。')
    expect(body.get('scenario')).toBe('technical')
    expect(body.get('enable_sensitive')).toBe('false')
    expect(body.get('enable_ad_extreme')).toBe('true')
    expect(body.get('custom_glossary')).toBe('[{"original":"AI","standard":"人工智能"}]')
    expect(body.get('banned_words')).toBe('["最好"]')
  })

  it('submits a file without changing its name', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...resultPayload, filename: 'source.docx', file_id: 'file-1' })
    })
    const api = createVerificationApi(fetchMock as typeof fetch)
    const file = new File(['document'], 'source.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    })

    await api.analyzeFile(file, {
      scenario: 'general',
      enableSecurity: true,
      enableSensitive: true,
      enableAdExtreme: false,
      glossary: [],
      bannedWords: []
    })

    const body = fetchMock.mock.calls[0]?.[1]?.body as FormData
    expect((body.get('file') as File).name).toBe('source.docx')
  })

  it('exports the complete edited text with positioned replacements', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['账号']),
      headers: new Headers()
    })
    const api = createVerificationApi(fetchMock as typeof fetch)
    const createObjectUrl = vi.fn(() => 'blob:test')
    const revokeObjectUrl = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectUrl })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    await api.exportOriginal(
      { ...resultPayload, file_id: 'file-1' },
      [{ original: '帐号', suggestion: '账号', position: 0, end_position: 2 }],
      '账号',
      false
    )

    const request = fetchMock.mock.calls[0]?.[1]
    expect(JSON.parse(String(request?.body))).toMatchObject({
      file_id: 'file-1',
      modified_text: '账号',
      replacements: [
        { original: '帐号', suggestion: '账号', position: 0, end_position: 2 }
      ]
    })
    delete (URL as Partial<typeof URL>).createObjectURL
    delete (URL as Partial<typeof URL>).revokeObjectURL
    click.mockRestore()
  })
})
