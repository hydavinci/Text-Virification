import { describe, expect, it, vi } from 'vitest'

import { ApiRequestError } from '../src/api/errors'
import { createVerificationApi } from '../src/api/verification'
import type { VerificationResult } from '../src/types/verification'

const resultPayload: VerificationResult = {
  success: true,
  filename: 'sample.txt',
  source_name: 'sample.txt',
  file_type: 'txt',
  text: '帐号测试。',
  blocks: [
    {
      block_id: 'p-0',
      kind: 'paragraph',
      text: '帐号测试。',
      global_start: 0,
      global_end: 5,
      block_start: 0,
      block_end: 5,
      page: null,
      paragraph_index: 0,
      table_index: null,
      row_index: null,
      cell_index: null,
      bbox: null,
      parent_id: null,
      style: {},
      source_locator: { paragraph_index: 0 }
    }
  ],
  parser_name: 'compatibility-flat-text',
  parser_version: '1',
  stats: {
    char_count: 5,
    char_count_no_space: 5,
    line_count: 1,
    paragraph_count: 1,
    language: 'zh',
    primary_count: 5,
    primary_label: '总字数'
  },
  issues: [
    {
      issue_id: '33333333-3333-4333-8333-333333333333',
      document_id: '11111111-1111-4111-8111-111111111111',
      verification_run_id: '22222222-2222-4222-8222-222222222222',
      block_id: 'p-0',
      page: null,
      start: 0,
      end: 2,
      block_start: 0,
      block_end: 2,
      position: 0,
      end_position: 2,
      original: '帐号',
      suggestion: '账号',
      alternatives: ['账号'],
      type: 'typo',
      severity: 'warning',
      layer: 'character',
      message: '疑似错别字',
      description: '疑似错别字',
      rule_id: 'cn_typo',
      rule_version: '1',
      source: 'compatibility.analyzer',
      source_version: '1',
      confidence: 0.8,
      auto_fixable: true,
      context: '这是帐号测试。',
      review: '',
      review_reason: ''
    }
  ],
  summary: {
    total: 1,
    by_type: { typo: 1 },
    by_severity: { warning: 1 },
    by_rule: { cn_typo: 1 },
    by_layer: { character: 1 }
  },
  file_id: null,
  file_ext: null,
  document_id: '11111111-1111-4111-8111-111111111111',
  verification_run_id: '22222222-2222-4222-8222-222222222222',
  source_version: 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  execution_mode: 'synchronous',
  analysis_mode: 'local_only',
  dictionary_versions: {},
  degradation: {
    is_degraded: false,
    reasons: []
  },
  scenario: 'technical'
}

const nullableSuggestionPayload: VerificationResult = {
  ...resultPayload,
  issues: [
    {
      ...resultPayload.issues[0],
      suggestion: null,
      auto_fixable: false
    }
  ]
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
    expect(result.document_id).toBe('11111111-1111-4111-8111-111111111111')
    expect(result.verification_run_id).toBe('22222222-2222-4222-8222-222222222222')
    expect(result.source_version).toBe(
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    )
    expect(result.execution_mode).toBe('synchronous')
    expect(result.analysis_mode).toBe('local_only')
    expect(result.degradation).toEqual({ is_degraded: false, reasons: [] })
    expect(result.issues[0].issue_id).toBe('33333333-3333-4333-8333-333333333333')
    expect(result.issues[0].block_start).toBe(0)
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
      json: async () => ({
        ...resultPayload,
        filename: 'source.docx',
        file_id: '44444444-4444-4444-8444-444444444444'
      })
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

  it('preserves nullable legacy suggestions', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => nullableSuggestionPayload
    })
    const api = createVerificationApi(fetchMock as typeof fetch)

    const result = await api.analyzeText('这是测试。', {
      scenario: 'general',
      enableSecurity: true,
      enableSensitive: true,
      enableAdExtreme: false,
      glossary: [],
      bannedWords: []
    })

    expect(result.issues[0].suggestion).toBeNull()
  })

  it('rejects a malformed successful direct-analysis response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...resultPayload,
        summary: { ...resultPayload.summary, total: 2 }
      })
    })
    const api = createVerificationApi(fetchMock as typeof fetch)

    await expect(
      api.analyzeText('这是测试。', {
        scenario: 'general',
        enableSecurity: true,
        enableSensitive: true,
        enableAdExtreme: false,
        glossary: [],
        bannedWords: []
      })
    ).rejects.toThrow('Invalid verification result response.')
  })

  it('uses the shared typed API error shape for direct analysis failures', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: {
          code: 'invalid_verification_options',
          stage: 'validation',
          message: 'Verification options are invalid.',
          retryable: false
        }
      })
    })
    const api = createVerificationApi(fetchMock as typeof fetch)

    const request = api.analyzeText('检查文本', {
      scenario: 'general',
      enableSecurity: true,
      enableSensitive: true,
      enableAdExtreme: false,
      glossary: [],
      bannedWords: []
    })

    await expect(request).rejects.toBeInstanceOf(ApiRequestError)
    await expect(request).rejects.toMatchObject({
      status: 422,
      code: 'invalid_verification_options',
      stage: 'validation',
      retryable: false,
      message: 'Verification options are invalid.'
    })
  })

  it('persists a draft revision without sending a client revision number', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        revision_id: '44444444-4444-4444-8444-444444444444',
        document_id: resultPayload.document_id,
        verification_run_id: resultPayload.verification_run_id,
        source_version: resultPayload.source_version,
        revision_number: 3,
        created_at: '2026-09-03T04:00:00Z',
        parent_revision_id: null,
        persistence_state: 'persisted',
        kind: 'review',
        text: '账号测试。'
      })
    })
    const api = createVerificationApi(fetchMock as typeof fetch)

    const persisted = await api.persistRevision(
      '55555555-5555-4555-8555-555555555555',
      {
        revision_id: '44444444-4444-4444-8444-444444444444',
        document_id: resultPayload.document_id,
        verification_run_id: resultPayload.verification_run_id,
        source_version: resultPayload.source_version,
        revision_number: null,
        created_at: '2026-09-03T03:59:00.000Z',
        parent_revision_id: null,
        persistence_state: 'draft',
        kind: 'review',
        text: '账号测试。'
      }
    )

    expect(persisted).toMatchObject({
      revision_number: 3,
      persistence_state: 'persisted',
      created_at: '2026-09-03T04:00:00.000Z'
    })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/55555555-5555-4555-8555-555555555555/revisions',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          revision_id: '44444444-4444-4444-8444-444444444444',
          document_id: resultPayload.document_id,
          verification_run_id: resultPayload.verification_run_id,
          source_version: resultPayload.source_version,
          parent_revision_id: null,
          kind: 'review',
          text: '账号测试。'
        })
      })
    )
  })

  it('submits a guarded job export by persisted revision id and downloads it', async () => {
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {})
    const artifactId = '66666666-6666-4666-8666-666666666666'
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          export_artifact_id: artifactId,
          job_id: '55555555-5555-4555-8555-555555555555',
          verification_run_id: resultPayload.verification_run_id,
          format: 'docx_reconstruction',
          file_type: 'docx',
          file_name: 'sample-reconstructed.docx',
          media_type:
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          size_bytes: 12,
          content_sha256: 'a'.repeat(64),
          status: 'ready',
          created_at: '2026-09-03T04:00:00Z'
        })
      })
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => new Blob(['docx']),
        headers: new Headers({
          'content-disposition':
            "attachment; filename*=UTF-8''sample-reconstructed.docx"
        })
      })
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:reconstruction')
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn()
    })
    const api = createVerificationApi(fetchMock as typeof fetch)

    await api.exportJob(
      '55555555-5555-4555-8555-555555555555',
      'docx_reconstruction',
      '44444444-4444-4444-8444-444444444444',
      true,
      () => true
    )

    expect(fetchMock.mock.calls[0]).toEqual([
      '/api/v1/jobs/55555555-5555-4555-8555-555555555555/exports',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          format: 'docx_reconstruction',
          revision_id: '44444444-4444-4444-8444-444444444444',
          track_changes: true
        })
      }
    ])
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `/api/v1/jobs/55555555-5555-4555-8555-555555555555/exports/${artifactId}`
    )
    anchorClick.mockRestore()
  })

  it('does not download a stale job export after an awaited response', async () => {
    let resolveResponse: (value: unknown) => void = () => {}
    const fetchMock = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveResponse = resolve
        })
    )
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {})
    let current = true
    const api = createVerificationApi(fetchMock as typeof fetch)
    const pending = api.exportJob(
      '55555555-5555-4555-8555-555555555555',
      'original_format',
      null,
      false,
      () => current
    )

    current = false
    resolveResponse({
      ok: true,
      json: async () => ({})
    })
    await pending

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(anchorClick).not.toHaveBeenCalled()
    anchorClick.mockRestore()
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
