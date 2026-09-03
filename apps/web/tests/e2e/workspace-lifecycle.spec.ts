import { expect, test } from '@playwright/test'
import scannedResult from './fixtures/scanned-result'

const documentId = '11111111-1111-4111-8111-111111111111'
const runId = '22222222-2222-4222-8222-222222222222'
const issueId = '33333333-3333-4333-8333-333333333333'
const jobId = documentId
const artifactId = '66666666-6666-4666-8666-666666666666'
const sourceVersion = `sha256:${'a'.repeat(64)}`

function block(text: string, page: number | null = null) {
  return {
    block_id: 'p-0',
    kind: 'paragraph',
    text,
    global_start: 0,
    global_end: Array.from(text).length,
    block_start: 0,
    block_end: Array.from(text).length,
    page,
    paragraph_index: 0,
    table_index: null,
    row_index: null,
    cell_index: null,
    bbox: page === null ? null : [0, 0, 100, 20],
    parent_id: null,
    style: {},
    source_locator: { paragraph_index: 0 }
  }
}

function issue(text: string) {
  return {
    issue_id: issueId,
    document_id: documentId,
    verification_run_id: runId,
    block_id: 'p-0',
    page: null,
    start: 0,
    end: 2,
    block_start: 0,
    block_end: 2,
    original: text.slice(0, 2),
    suggestion: '账号',
    alternatives: ['账号'],
    type: 'typo',
    severity: 'warning',
    layer: 'character',
    message: '疑似错别字',
    description: '疑似错别字',
    rule_id: 'cn_typo',
    rule_version: '1',
    source: 'fixture',
    source_version: '1',
    confidence: 0.9,
    auto_fixable: true,
    context: text,
    review: null,
    review_reason: null
  }
}

function summary() {
  return {
    total: 1,
    by_type: { typo: 1 },
    by_severity: { warning: 1 },
    by_rule: { cn_typo: 1 },
    by_layer: { character: 1 }
  }
}

function stats(text: string) {
  const length = Array.from(text).length
  return {
    char_count: length,
    char_count_no_space: length,
    line_count: 1,
    paragraph_count: 1,
    language: 'zh',
    primary_count: length,
    primary_label: '总字数'
  }
}

test('direct text review, free edit, and versioned reload restore', async ({
  page
}) => {
  const text = '帐号测试'
  await page.route('**/api/v1/analyze', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        filename: '直接输入文本.txt',
        source_name: '直接输入文本',
        file_type: 'txt',
        text,
        blocks: [block(text)],
        parser_name: 'compatibility-flat-text',
        parser_version: '1',
        stats: stats(text),
        issues: [
          {
            ...issue(text),
            position: 0,
            end_position: 2
          }
        ],
        summary: summary(),
        file_id: null,
        file_ext: null,
        document_id: documentId,
        verification_run_id: runId,
        source_version: sourceVersion,
        execution_mode: 'synchronous',
        analysis_mode: 'local_only',
        dictionary_versions: {},
        degradation: { is_degraded: false, reasons: [] },
        scenario: 'general'
      })
    })
  })
  page.on('dialog', (dialog) => dialog.accept())

  await page.goto('/')
  await page.getByRole('button', { name: '粘贴文本' }).click()
  const input = page.getByLabel('待检查文本')
  await input.fill(text)
  await input.press('Control+Enter')
  await expect(page.getByText('发现问题')).toBeVisible()
  await page.getByRole('button', { name: '全部接受' }).click()
  await expect(page.locator('[data-count="accepted"]')).toHaveText('1')

  await page.getByRole('button', { name: '编辑原文' }).click()
  await page.getByLabel('编辑文档内容').fill('手工修订文本')
  await page.getByRole('button', { name: '保存编辑' }).click()
  await expect(page.getByText('手工修订文本')).toBeVisible()

  await page.reload()
  await expect(page.getByText('手工修订文本')).toBeVisible()
  await expect(
    page.getByRole('button', { name: '导出修改文件' })
  ).toBeDisabled()
  await expect(page.getByText(/重新检查后再导出/)).toBeVisible()
})

test('ordinary DOCX job persists its revision before job-owned original-format export', async ({
  page
}) => {
  const text = '帐号测试'
  const revisionRequests: Record<string, unknown>[] = []
  const exportRequests: Record<string, unknown>[] = []
  await page.route('**/api/v1/jobs', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: jobId,
        source_name: 'sample.docx',
        file_type: 'docx',
        size_bytes: 36580,
        status: 'queued',
        stage: 'queued',
        progress: 0,
        error_code: null,
        error_message: null,
        error_stage: null,
        error_retryable: null,
        created_at: '2026-09-03T04:00:00Z',
        expires_at: '2026-09-04T04:00:00Z'
      })
    })
  })
  await page.route(`**/api/v1/jobs/${jobId}/events`, async (route) => {
    await route.fulfill({
      contentType: 'text/event-stream',
      body:
        'id: 1\n' +
        'event: progress\n' +
        `data: ${JSON.stringify({
          status: 'completed',
          stage: 'completed',
          progress: 100,
          message: '处理完成',
          created_at: '2026-09-03T04:01:00Z'
        })}\n\n` +
        'event: done\n' +
        'data: {"event":"done"}\n\n'
    })
  })
  await page.route(`**/api/v1/jobs/${jobId}/result`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        verification_run_id: runId,
        document_id: documentId,
        source_version: sourceVersion,
        source_name: 'sample.docx',
        file_type: 'docx',
        scenario: 'general',
        text,
        blocks: [block(text)],
        parser_name: 'docx',
        parser_version: '1',
        metadata: { pdf: null },
        ocr_requirement: null,
        stats: stats(text),
        issues: [issue(text)],
        summary: { ...summary(), llm_review: null },
        execution_mode: 'asynchronous',
        analysis_mode: 'local_only',
        dictionary_versions: {},
        degradation: { is_degraded: false, reasons: [] }
      })
    })
  })
  await page.route(`**/api/v1/jobs/${jobId}/revisions`, async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    revisionRequests.push(body)
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        ...body,
        revision_number: revisionRequests.length,
        created_at: '2026-09-03T04:02:00Z',
        persistence_state: 'persisted'
      })
    })
  })
  await page.route(`**/api/v1/jobs/${jobId}/exports`, async (route) => {
    exportRequests.push(
      route.request().postDataJSON() as Record<string, unknown>
    )
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        export_artifact_id: artifactId,
        job_id: jobId,
        verification_run_id: runId,
        format: 'original_format',
        file_type: 'docx',
        file_name: 'sample-modified.docx',
        media_type:
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        size_bytes: 9,
        content_sha256: 'b'.repeat(64),
        status: 'ready',
        created_at: '2026-09-03T04:03:00Z'
      })
    })
  })
  await page.route(
    `**/api/v1/jobs/${jobId}/exports/${artifactId}`,
    async (route) => {
      await route.fulfill({
        contentType:
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers: {
          'Content-Disposition':
            "attachment; filename*=UTF-8''sample-modified.docx"
        },
        body: 'fixture-docx'
      })
    }
  )
  page.on('dialog', (dialog) => dialog.accept())

  await page.goto('/')
  await page
    .locator('input[type="file"]')
    .setInputFiles('tests/e2e/fixtures/sample.docx')
  await expect(page.getByText('sample.docx')).toBeVisible()
  await page.getByRole('button', { name: '全部接受' }).click()
  await expect(page.locator('[data-count="accepted"]')).toHaveText('1')

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出修改文件' }).click()
  const download = await downloadPromise

  expect(revisionRequests).toHaveLength(1)
  expect(revisionRequests[0]).toMatchObject({
    document_id: documentId,
    verification_run_id: runId,
    source_version: sourceVersion,
    parent_revision_id: null,
    kind: 'review',
    text: '账号测试'
  })
  expect(revisionRequests[0]).not.toHaveProperty('revision_number')
  expect(exportRequests).toEqual([
    {
      format: 'original_format',
      revision_id: revisionRequests[0].revision_id,
      track_changes: true
    }
  ])
  expect(download.suggestedFilename()).toBe('sample-modified.docx')
})

test('scanned PDF exposes OCR progress, canonical result, and reconstruction export', async ({
  page
}) => {
  await page.addInitScript(() => {
    type Listener = (event: Event) => void
    const listeners = new Map<string, Set<Listener>>()
    const emit = (
      type: string,
      data: Record<string, unknown>,
      lastEventId = ''
    ) => {
      const event = new MessageEvent(type, {
        data: JSON.stringify(data),
        lastEventId
      })
      for (const listener of listeners.get(type) ?? []) {
        listener(event)
      }
    }
    class FixtureEventSource {
      static readonly CONNECTING = 0
      static readonly OPEN = 1
      static readonly CLOSED = 2
      readonly CONNECTING = 0
      readonly OPEN = 1
      readonly CLOSED = 2
      readonly url: string
      readonly withCredentials = false
      readyState = 1
      onerror: ((event: Event) => void) | null = null

      constructor(url: string) {
        this.url = url
        window.setTimeout(() => {
          emit(
            'progress',
            {
              status: 'parsing',
              stage: 'ocr',
              progress: 40,
              message: '正在执行扫描件 OCR',
              created_at: '2026-09-03T04:00:30Z'
            },
            '1'
          )
        }, 0)
      }

      addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
        const callback =
          typeof listener === 'function'
            ? listener
            : (event: Event) => listener.handleEvent(event)
        const current = listeners.get(type) ?? new Set<Listener>()
        current.add(callback)
        listeners.set(type, current)
      }

      removeEventListener(
        type: string,
        listener: EventListenerOrEventListenerObject
      ) {
        if (typeof listener === 'function') {
          listeners.get(type)?.delete(listener)
        }
      }

      dispatchEvent(): boolean {
        return true
      }

      close() {
        this.readyState = 2
      }
    }
    Object.defineProperty(window, 'EventSource', {
      configurable: true,
      value: FixtureEventSource
    })
    Object.assign(window, {
      __finishOcrJob() {
        emit(
          'progress',
          {
            status: 'completed',
            stage: 'completed',
            progress: 100,
            message: 'OCR 处理完成',
            created_at: '2026-09-03T04:01:00Z'
          },
          '2'
        )
        emit('done', { event: 'done' })
      }
    })
  })
  const exportRequests: Record<string, unknown>[] = []
  await page.route('**/api/v1/jobs', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: jobId,
        source_name: 'scanned-page.pdf',
        file_type: 'pdf',
        size_bytes: 1352,
        status: 'queued',
        stage: 'queued',
        progress: 0,
        error_code: null,
        error_message: null,
        error_stage: null,
        error_retryable: null,
        created_at: '2026-09-03T04:00:00Z',
        expires_at: '2026-09-04T04:00:00Z'
      })
    })
  })
  await page.route(`**/api/v1/jobs/${jobId}/result`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(scannedResult)
    })
  })
  await page.route(`**/api/v1/jobs/${jobId}/exports`, async (route) => {
    exportRequests.push(
      route.request().postDataJSON() as Record<string, unknown>
    )
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        export_artifact_id: artifactId,
        job_id: jobId,
        verification_run_id: runId,
        format: 'docx_reconstruction',
        file_type: 'docx',
        file_name: 'scanned-page-reconstructed.docx',
        media_type:
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        size_bytes: 9,
        content_sha256: 'c'.repeat(64),
        status: 'ready',
        created_at: '2026-09-03T04:03:00Z'
      })
    })
  })
  await page.route(
    `**/api/v1/jobs/${jobId}/exports/${artifactId}`,
    async (route) => {
      await route.fulfill({
        contentType:
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers: {
          'Content-Disposition':
            "attachment; filename*=UTF-8''scanned-page-reconstructed.docx"
        },
        body: 'fixture-docx'
      })
    }
  )
  page.on('dialog', (dialog) => dialog.accept())

  await page.goto('/')
  await page
    .locator('input[type="file"]')
    .setInputFiles('tests/e2e/fixtures/scanned-page.pdf')
  await expect(
    page.getByText('Status: parsing · 40% · 正在执行扫描件 OCR')
  ).toBeVisible()
  await page.evaluate(() => {
    ;(window as unknown as { __finishOcrJob: () => void }).__finishOcrJob()
  })
  await expect(page.locator('.stats-strip .filename')).toHaveText(
    'scanned-page.pdf'
  )
  await expect(page.getByText('test@example.com')).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出修改文件' }).click()
  const download = await downloadPromise

  expect(exportRequests).toEqual([
    {
      format: 'docx_reconstruction',
      revision_id: null,
      track_changes: true
    }
  ])
  expect(download.suggestedFilename()).toBe(
    'scanned-page-reconstructed.docx'
  )
})

test('reduced viewport keeps header controls and privacy dialog usable', async ({
  page
}) => {
  await page.setViewportSize({ width: 360, height: 640 })
  await page.goto('/')

  await expect(page.getByLabel('打开隐私说明')).toBeVisible()
  await page.getByLabel('打开隐私说明').click()
  await expect(page.getByRole('dialog', { name: '隐私说明' })).toBeVisible()
  await expect(page.getByLabel('关闭隐私说明')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '隐私说明' })).toBeHidden()
  await expect(page.getByLabel('打开隐私说明')).toBeFocused()
})
