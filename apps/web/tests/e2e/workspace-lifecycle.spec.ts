import { expect, test } from '@playwright/test'
import scannedResult from './fixtures/scanned-result'

const documentId = '11111111-1111-4111-8111-111111111111'
const runId = '22222222-2222-4222-8222-222222222222'
const issueId = '33333333-3333-4333-8333-333333333333'
const jobId = documentId
const artifactId = '66666666-6666-4666-8666-666666666666'
const sourceVersion = `sha256:${'a'.repeat(64)}`

test('minimal setup preserves advanced options and remains usable at desktop and mobile widths', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('文档场景').selectOption('academic')
  await page.locator('[data-open-settings]').click()
  const dialog = page.getByRole('dialog', { name: '检查设置', exact: true })
  await expect(dialog.getByLabel('文档场景')).toHaveValue('academic')
  await dialog.getByLabel('个人信息与凭证扫描').uncheck()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(page.locator('[data-open-settings]')).toBeFocused()
  await expect(page.locator('.options-summary')).not.toContainText('个人信息')
  await expect(page.getByLabel('文档场景')).toHaveValue('academic')

  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.locator('[data-submit-source]')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.locator('[data-open-settings]').click()
    await expect(dialog).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.keyboard.press('Escape')
  }
  await page.locator('[data-toggle-theme]').click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})

test('removing a focused term keeps keyboard focus inside the settings drawer', async ({ page }) => {
  await page.goto('/')
  await page.locator('[data-open-settings]').click()
  const dialog = page.getByRole('dialog', { name: '检查设置', exact: true })
  await dialog.getByRole('button', { name: '术语 0', exact: true }).click()
  await dialog.locator('#term-original').fill('AI')
  await dialog.locator('#term-standard').fill('人工智能')
  await dialog.locator('[data-action="add-glossary"]').click()
  await dialog.getByRole('button', { name: '删除术语 AI', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(dialog.getByRole('button', { name: '删除术语 AI', exact: true })).toHaveCount(0)
  await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Tab')
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(page.locator('[data-open-settings]')).toBeFocused()
})

for (const [width, height] of [
  [1440, 900], [390, 900], [320, 900], [320, 568], [844, 390], [390, 400]
]) {
  test(`long document preserves pane scrolling and selected-issue navigation at ${width}x${height}`, async ({ page }) => {
    const longParagraph = '用于检查长段落自动换行和段间距的文档内容。'.repeat(24)
    const prefix = `😀热点首段\n${longParagraph}\n` + '用于检查滚动和定位的文档段落。\n'.repeat(100)
    const text = `${prefix}帐号测试 热点`
    const start = Array.from(prefix).length
    await page.setViewportSize({ width, height })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.route('**/api/v1/analyze', (route) => route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        filename: '长文档.txt',
        source_name: '长文档.txt',
        file_type: 'txt',
        text,
        blocks: [block(text)],
        parser_name: 'compatibility-flat-text',
        parser_version: '1',
        stats: stats(text),
        issues: [{
          ...issue('帐号测试'),
          suggestion: '中国账号',
          start,
          end: start + 2,
          block_start: start,
          block_end: start + 2,
          position: start,
          end_position: start + 2
        }],
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
    }))
    await page.goto('/')
    await page.getByRole('button', { name: '粘贴文本' }).click()
    await page.getByLabel('待检查文本').fill(text)
    await page.locator('[data-submit-source]').click()
    await expect(page.locator('.review-grid')).toBeVisible()
    await expect(page.getByText('长文档.txt', { exact: true })).toHaveCount(1)
    await expect(page.locator('.edit-actions').getByText('当前文档', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '编辑正文', exact: true })).toBeVisible()
    expect(await page.locator('.review-grid').evaluate(
      (element) => element.getBoundingClientRect().bottom
    )).toBeLessThanOrEqual(height)
    const content = page.locator('.edit-preview > .document-content')
    await expect(page.locator('[data-line-number]')).toHaveCount(0)
    const paragraphs = page.locator('[data-source-paragraph]')
    await expect(paragraphs).toHaveCount(103)
    const layout = await page.locator('[data-source-text]').evaluate((element) => {
      const paragraphs = element.querySelectorAll('[data-source-paragraph]')
      const long = paragraphs[1].getBoundingClientRect()
      const next = paragraphs[2].getBoundingClientRect()
      const box = element.getBoundingClientRect()
      const parent = element.parentElement!.getBoundingClientRect()
      return {
        width: box.width,
        longHeight: long.height,
        lineHeight: parseFloat(getComputedStyle(element).lineHeight),
        gap: next.top - long.bottom,
        font: getComputedStyle(element).fontFamily,
        bodyFont: getComputedStyle(document.body).fontFamily,
        centering: (box.left - parent.left) - (parent.right - box.right)
      }
    })
    expect(layout.width).toBeLessThanOrEqual(Math.min(width, 840))
    expect(layout.longHeight).toBeGreaterThan(layout.lineHeight * 2)
    expect(layout.gap).toBeGreaterThanOrEqual(10)
    expect(layout.font).toBe(layout.bodyFont)
    expect(Math.abs(layout.centering)).toBeLessThan(1)
    expect(await content.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    expect(await content.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true)
    expect(await page.locator('.review-grid').evaluate((element) => element.clientHeight)).toBeLessThan(900)
    const reviewLayout = () => page.evaluate(() => {
      const selectors = ['.review-summary', '.review-grid']
      return {
        boxes: selectors.map((selector) => {
          const box = document.querySelector(selector)!.getBoundingClientRect()
          return { x: box.x, y: box.y, width: box.width, height: box.height }
        }),
        pageScroll: window.scrollY,
        documentScroll: document.querySelector('.edit-preview > .document-content')!.scrollTop
      }
    })
    const search = page.locator('.issues-panel [data-search-input]')
    await expect(page.locator('[data-action="toggle-search-replace"]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^(段落|紧凑)视图$/ })).toHaveCount(0)
    await page.keyboard.press('Control+f')
    await expect(search).toBeFocused()
    expect(await page.locator('.issue-list').evaluate(
      (element) => element.clientHeight
    )).toBeGreaterThanOrEqual(100)
    const beforeSearch = await reviewLayout()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.keyboard.press('Escape')
    await expect(search).toBeVisible()
    expect(await reviewLayout()).toEqual(beforeSearch)
    await page.keyboard.press('Meta+f')
    await expect(search).toBeFocused()
    expect(await reviewLayout()).toEqual(beforeSearch)

    const pageScrollBeforeNavigation = await page.evaluate(() => window.scrollY)
    await page.locator('[data-issue-role="list"]').click()
    if (width <= 760) {
      await page.getByRole('button', { name: '文档', exact: true }).click()
    }
    await expect(page.locator('.source-segment.highlighted.selected')).toBeInViewport()
    expect(await content.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
    expect(await page.evaluate(() => window.scrollY)).toBe(pageScrollBeforeNavigation)

    const focusSearch = async () => {
      await page.keyboard.press('Control+f')
      await expect(search).toBeFocused()
    }
    const showDocument = async () => {
      if (width <= 760) {
        await page.getByRole('button', { name: '文档', exact: true }).click()
      }
    }
    await focusSearch()
    const expectMatchUncovered = async () => {
      await expect.poll(() => page.locator('.active-search-match').first().evaluate((element) => {
        const bounds = element.getBoundingClientRect()
        const hit = document.elementFromPoint(
          bounds.left + bounds.width / 2,
          bounds.top + bounds.height / 2
        )
        return hit !== null && (hit === element || element.contains(hit))
      })).toBe(true)
    }
    await search.fill('热点')
    await expect(search).toBeFocused()
    await expect(search).toBeVisible()
    await showDocument()
    await expect(page.locator('.document-panel')).toBeVisible()
    await expect(page.locator('.search-match')).toHaveCount(2)
    await expect(page.locator('.active-search-match')).toHaveAttribute('data-search-match', '0')
    await expect(page.locator('.active-search-match')).toBeInViewport()
    await expectMatchUncovered()
    const pageScrollBeforeSearchNavigation = await page.evaluate(() => window.scrollY)
    await focusSearch()
    await page.locator('[data-action="search-next"]').click()
    await showDocument()
    await expect(page.locator('.active-search-match')).toHaveAttribute('data-search-match', '1')
    await expect(page.locator('.active-search-match')).toBeInViewport()
    await expectMatchUncovered()
    expect(await content.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
    expect(await page.evaluate(() => window.scrollY)).toBe(pageScrollBeforeSearchNavigation)
    await focusSearch()
    await page.locator('[data-action="search-previous"]').click()
    await showDocument()
    await expect(page.locator('.active-search-match')).toHaveAttribute('data-search-match', '0')
    await expect(page.locator('.active-search-match')).toBeInViewport()
    await expectMatchUncovered()

    const visibleMatchScroll = await content.evaluate((element) => element.scrollTop)
    await focusSearch()
    await search.fill('热点首段')
    await showDocument()
    await expect(page.locator('.active-search-match')).toHaveText('热点首段')
    expect(await content.evaluate((element) => element.scrollTop)).toBe(visibleMatchScroll)
    expect(await page.evaluate(() => window.scrollY)).toBe(pageScrollBeforeSearchNavigation)

    await page.locator('.review-disclosure > summary').click()
    await page.locator('[data-action="accept-selected"]').click()
    await page.locator('.review-disclosure > summary').click()
    await expect(page.locator('[data-source-text]')).toHaveText(`${prefix}中国账号测试 热点`)
    await focusSearch()
    await search.fill('中国账号')
    await showDocument()
    await expect(page.locator('.active-search-match')).toHaveText('中国账号')
    await expect(page.locator('.active-search-match')).toBeInViewport()
    const highlight = page.locator('.source-segment.accepted')
    await expect(page.locator('.issue-marker')).toHaveCount(0)
    const textLeft = await page.locator('.source-segment').first().evaluate(
      (element) => element.getBoundingClientRect().left
    )
    expect(await highlight.evaluate((element) => element.getBoundingClientRect().left))
      .toBeCloseTo(textLeft, 1)
    await highlight.click()
    await expect(highlight).toHaveAttribute('aria-current', 'true')
    await highlight.focus()
    await page.keyboard.press('Enter')
    await expect(highlight).toHaveAttribute('aria-current', 'true')
    await page.locator('.review-disclosure > summary').click()
    await page.locator('[data-action="reset-selected"]').click()
    await page.locator('.review-disclosure > summary').click()
    await expect(page.locator('[data-source-text]')).toHaveText(text)
    await expect(page.locator('.search-match')).toHaveCount(0)
    await focusSearch()
    await search.fill('')
    await showDocument()
    await expect(page.locator('.search-match')).toHaveCount(0)
    const markers = page.getByRole('checkbox', { name: '显示问题标记', exact: true })
    const scrollBeforeToggle = await content.evaluate((element) => element.scrollTop)
    await markers.uncheck()
    await expect(page.locator('[data-issue-role="source"]')).toHaveCount(0)
    await expect(paragraphs).toHaveCount(103)
    await expect(page.locator('[data-source-text]')).toHaveText(text)
    expect(await content.evaluate((element) => element.scrollTop)).toBe(scrollBeforeToggle)
    await markers.check()
    await expect(page.locator('[data-issue-role="source"]')).toHaveCount(1)
    await expect(page.locator('[data-view-mode="sentence"]')).toBeVisible()
    await expect(page.locator('[data-source-text]')).toHaveText(text)
    await expect(paragraphs).toHaveCount(103)
  })
}

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
  await page.locator('.review-disclosure > summary').click()
  await page.getByRole('button', { name: '全部接受' }).click()
  await expect(page.locator('[data-count="accepted"]')).toHaveText('1')
  await page.locator('.review-disclosure > summary').click()
  await page.setViewportSize({ width: 390, height: 900 })
  await page.getByRole('button', { name: '问题 1', exact: true }).click()
  await expect(page.locator('.issues-panel')).toBeVisible()
  await expect(page.locator('.document-panel')).not.toBeVisible()
  await page.locator('[data-issue-role="list"]').click()
  await expect(page.locator('.issue-actions')).toBeVisible()
  await page.getByRole('button', { name: '文档', exact: true }).click()
  await expect(page.locator('.document-panel')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)

  await page.getByRole('button', { name: '编辑正文' }).click()
  await page.getByLabel('编辑文档内容').fill('手工修订文本')
  await page.getByRole('button', { name: '保存编辑' }).click()
  await expect(page.getByText('手工修订文本')).toBeVisible()

  await page.reload()
  await expect(page.getByText('手工修订文本')).toBeVisible()
  await page.locator('[data-toggle-export]').click()
  await expect(
    page.getByRole('button', { name: '导出修改文件' })
  ).toBeDisabled()
  await expect(page.getByText(/重新检查后再导出/)).toBeVisible()
  await page.locator('[data-toggle-export]').click()
  await page.keyboard.press('Control+f')
  const undo = page.getByRole('button', { name: '撤销修改', exact: true })
  await expect(undo).toBeEnabled()
  await undo.click()
  await expect(undo).toBeDisabled()
  await expect(page.locator('[data-count="accepted"]')).toHaveText('1')
  await expect(page.locator('.reverification-state')).toHaveCount(0)
  await page.getByRole('button', { name: '文档', exact: true }).click()
  await expect(page.locator('[data-source-text]')).toHaveText('账号测试')
  await page.reload()
  await expect(page.locator('[data-source-text]')).toHaveText('账号测试')
  await page.keyboard.press('Control+f')
  await expect(undo).toBeDisabled()
  await page.getByRole('button', { name: '文档', exact: true }).click()
  await page.getByRole('button', { name: '编辑正文' }).click()
  await page.getByLabel('编辑文档内容').fill('账号测试 😀账号测试')
  await page.getByRole('button', { name: '保存编辑' }).click()
  await page.keyboard.press('Control+f')
  await page.getByLabel('查找内容').fill('账号')
  await page.getByLabel('替换内容').fill('X')
  await page.getByRole('button', { name: '全部替换', exact: true }).click()
  await page.getByRole('button', { name: '文档', exact: true }).click()
  await expect(page.locator('[data-source-text]')).toHaveText('X测试 😀X测试')
  await page.reload()
  await page.keyboard.press('Control+f')
  await undo.click()
  await expect(undo).toBeEnabled()
  await page.getByRole('button', { name: '文档', exact: true }).click()
  await expect(page.locator('[data-source-text]')).toHaveText('账号测试 😀账号测试')
  await page.keyboard.press('Control+f')
  await undo.click()
  await expect(undo).toBeDisabled()
  await expect(page.locator('[data-count="accepted"]')).toHaveText('1')
  await page.getByRole('button', { name: '文档', exact: true }).click()
  await expect(page.locator('[data-source-text]')).toHaveText('账号测试')
})

for (const [sourceType, exportFormat] of [
  ['docx', 'original_format'],
  ['png', 'docx_reconstruction']
] as const) {
for (const undoBeforeExport of [false, true]) {
test(`${sourceType} job persists its revision before ${exportFormat} export${undoBeforeExport ? ' after text undo' : ''}`, async ({
  page
}) => {
  const text = '帐号测试'
  const revisionRequests: Record<string, unknown>[] = []
  const exportRequests: Record<string, unknown>[] = []
  let jobSubmissions = 0
  await page.route('**/api/v1/jobs', async (route) => {
    jobSubmissions += 1
    if (sourceType === 'png') {
      expect(route.request().postData()).toContain('name="ocr_language"\r\n\r\nja')
      expect(route.request().postData()).toContain('name="enable_extended_rules"\r\n\r\ntrue')
    }
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: jobId,
        source_name: `sample.${sourceType}`,
        file_type: sourceType,
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
        source_name: `sample.${sourceType}`,
        file_type: sourceType,
        scenario: 'general',
        text,
        blocks: [block(text)],
        parser_name: sourceType === 'png' ? 'image-ocr' : 'docx',
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
        format: exportFormat,
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
  if (sourceType === 'png') {
    await page.locator('[data-open-settings]').click()
    await page.getByLabel('OCR 识别语言').selectOption('ja')
    await page.locator('#enable-extended-rules').check()
    await page.keyboard.press('Escape')
    await page.locator('input[type="file"]').setInputFiles('tests/e2e/fixtures/sample.png')
  } else {
    await page.locator('input[type="file"]').setInputFiles('tests/e2e/fixtures/sample.docx')
  }
  await expect(page.locator('[data-selected-file]')).toContainText(`sample.${sourceType}`)
  expect(jobSubmissions).toBe(0)
  await page.locator('[data-submit-source]').click()
  await expect(
    page.locator('.review-summary').getByTitle(`sample.${sourceType}`, { exact: true })
  ).toBeVisible()
  await page.locator('.review-disclosure > summary').click()
  await page.getByRole('button', { name: '全部接受' }).click()
  await expect(page.locator('[data-count="accepted"]')).toHaveText('1')

  if (undoBeforeExport) {
    await page.locator('.review-disclosure > summary').click()
    await page.getByLabel('查找内容').fill('账号')
    await page.getByLabel('替换内容').fill('临时😀')
    await page.getByRole('button', { name: '替换当前', exact: true }).click()
    await expect(page.locator('[data-source-text]')).toHaveText('临时😀测试')
    await page.getByRole('button', { name: '撤销修改', exact: true }).click()
    await expect(page.locator('[data-source-text]')).toHaveText('账号测试')
    await expect(page.locator('[data-count="accepted"]')).toHaveText('1')
  }

  const downloadPromise = page.waitForEvent('download')
  await page.locator('[data-toggle-export]').click()
  await page.getByRole('button', { name: '导出修改文件' }).click()
  const download = await downloadPromise

  expect(revisionRequests).toHaveLength(undoBeforeExport ? 3 : 1)
  expect(revisionRequests[0]).toMatchObject({
    document_id: documentId,
    verification_run_id: runId,
    source_version: sourceVersion,
    parent_revision_id: null,
    kind: 'review',
    text: '账号测试'
  })
  expect(revisionRequests[0]).not.toHaveProperty('revision_number')
  if (undoBeforeExport) {
    expect(revisionRequests[1]).toMatchObject({
      parent_revision_id: revisionRequests[0].revision_id,
      kind: 'manual',
      text: '临时😀测试'
    })
    expect(revisionRequests[2]).toMatchObject({
      parent_revision_id: revisionRequests[1].revision_id,
      kind: 'review',
      text: '账号测试'
    })
  }
  expect(exportRequests).toEqual([
    {
      format: exportFormat,
      revision_id: revisionRequests.at(-1)?.revision_id,
      track_changes: true
    }
  ])
  expect(download.suggestedFilename()).toBe('sample-modified.docx')
})
}
}

test('job recheck preserves exact multiline text and retained authority across reload', async ({ page }) => {
  const text = '第一段\n\n第二段\r\n第三段\r末尾 & + = % 😀\n'
  const freshDocumentId = '77777777-7777-4777-8777-777777777777'
  const received: string[] = []
  const emptySummary = {
    total: 0, by_type: {}, by_severity: {}, by_rule: {}, by_layer: {}
  }
  const original = {
    verification_run_id: runId,
    document_id: jobId,
    source_version: sourceVersion,
    source_name: '多段.docx',
    file_type: 'docx',
    scenario: 'general',
    text,
    blocks: [block(text)],
    parser_name: 'docx',
    parser_version: '1',
    metadata: { pdf: null },
    ocr_requirement: null,
    stats: stats(text),
    issues: [],
    summary: emptySummary,
    execution_mode: 'asynchronous',
    analysis_mode: 'local_only',
    dictionary_versions: {},
    degradation: { is_degraded: false, reasons: [] }
  }
  await page.route('**/api/v1/jobs**', async route => {
    const request = route.request()
    if (request.url().endsWith('/events')) {
      await route.fulfill({
        contentType: 'text/event-stream',
        body: 'id: 1\nevent: progress\n' +
          `data: ${JSON.stringify({
            status: 'completed', stage: 'completed', progress: 100,
            message: '处理完成', created_at: new Date().toISOString()
          })}\n\nevent: done\ndata: {"event":"done"}\n\n`
      })
    } else if (request.url().endsWith('/result')) {
      await route.fulfill({ json: original })
    } else if (request.url().endsWith('/recheck')) {
      const form = await new Response(request.postData(), {
        headers: { 'Content-Type': request.headers()['content-type'] }
      }).formData()
      const submitted = form.get('text')
      if (typeof submitted !== 'string') throw new Error('Expected recheck text')
      received.push(submitted)
      await route.fulfill({ json: {
        result: {
          ...original,
          success: true,
          filename: '直接输入文本',
          source_name: '直接输入文本',
          file_type: 'txt',
          file_id: null,
          file_ext: null,
          document_id: freshDocumentId,
          verification_run_id: '88888888-8888-4888-8888-888888888888',
          source_version: `sha256:${'b'.repeat(64)}`,
          execution_mode: 'synchronous',
          text: submitted,
          blocks: [block(submitted)],
          stats: stats(submitted)
        },
        grant: 'server-issued-recheck-grant'
      } })
    } else {
      await route.fulfill({ json: {
        job_id: jobId, source_name: '多段.docx', file_type: 'docx',
        size_bytes: 36580, status: 'queued', stage: 'queued', progress: 0,
        error_code: null, error_message: null, error_stage: null, error_retryable: null,
        created_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 86_400_000).toISOString()
      } })
    }
  })
  await page.goto('/')
  await page.locator('input[type="file"]').setInputFiles('tests/e2e/fixtures/sample.docx')
  await page.locator('[data-submit-source]').click()
  await expect(page.locator('.review-summary').getByTitle('多段.docx')).toBeVisible()
  await page.getByRole('button', { name: '重新检查', exact: true }).click()
  await expect.poll(() => received.length).toBe(1)
  expect(received[0]).toBe(text)
  const saved = () => page.evaluate(() =>
    JSON.parse(sessionStorage.getItem('text-verification-session') ?? 'null')
  )
  await expect.poll(async () => (await saved())?.workspace.result.document_id)
    .toBe(freshDocumentId)
  expect((await saved()).workspace.result.text).toBe(text)
  expect((await saved()).exportAuthority).toMatchObject({
    jobId, documentId: jobId, sourceVersion,
    recheckGrant: 'server-issued-recheck-grant'
  })
  await page.reload()
  await expect(page.locator('.review-summary').getByTitle('多段.docx')).toBeVisible()
  expect((await saved()).workspace.result.text).toBe(text)
  await page.getByRole('button', { name: '重新检查', exact: true }).click()
  await expect.poll(() => received.length).toBe(2)
  expect(received[1]).toBe(text)
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
  await page.locator('[data-submit-source]').click()
  await expect(
    page.getByText('Status: parsing · 40% · 正在执行扫描件 OCR')
  ).toBeVisible()
  await page.evaluate(() => {
    ;(window as unknown as { __finishOcrJob: () => void }).__finishOcrJob()
  })
  await expect(page.locator('.document-identity > strong')).toHaveText(
    'scanned-page.pdf'
  )
  await expect(page.getByText('test@example.com')).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await page.locator('[data-toggle-export]').click()
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
