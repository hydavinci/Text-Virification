import { expect, test, type Locator } from '@playwright/test'
import scannedResult from './fixtures/scanned-result'
import { scenarioCatalogFixture } from '../fixtures/scenarioCatalog'

const documentId = '11111111-1111-4111-8111-111111111111'
const runId = '22222222-2222-4222-8222-222222222222'
const issueId = '33333333-3333-4333-8333-333333333333'
const jobId = documentId
const artifactId = '66666666-6666-4666-8666-666666666666'
const sourceVersion = `sha256:${'a'.repeat(64)}`

function reviewLayout(text: string) {
  const characters = Array.from(text)
  const pages = []
  for (let offset = 0; offset < Math.max(1, characters.length); offset += 300) {
    const content = characters.slice(offset, offset + 300)
    pages.push({
      width: 600, height: 800,
      image: `data:image/svg+xml;base64,${btoa(
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><path d="M30 60h16v20H30z"/></svg>'
      )}`,
      text: content.join(''),
      glyphs: content.map((_, index) => ({
        start: offset + index, end: offset + index + 1,
        x: 30 + index % 30 * 16, y: 60 + Math.floor(index / 30) * 24, width: 16, height: 20
      }))
    })
  }
  return { pages, revision_applied: true, notice: null }
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/scenarios', (route) =>
    route.fulfill({ json: { scenarios: scenarioCatalogFixture() } }))
  await page.route('**/api/v1/jobs/*/preview/layout', async (route) => {
    await route.fulfill({ json: reviewLayout(route.request().postDataJSON().text) })
  })
})

test('selection menus open below their controls and preserve keyboard selection', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('让每一次交付，更准确。')
  const scenario = page.getByRole('combobox', { name: '文档场景', exact: true })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await scenario.click()
    const menu = page.getByRole('listbox')
    await expect(menu).toBeVisible()
    const anchor = (await scenario.boundingBox())!
    const bounds = (await menu.boundingBox())!
    expect(bounds.y).toBeGreaterThanOrEqual(anchor.y + anchor.height)
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width)
    expect(bounds.width).toBeCloseTo(anchor.width, 0)
    await menu.getByRole('option', { name: '学术论文' }).click()
    await expect(scenario).toHaveValue('academic')
    await expect(menu).toHaveCount(0)
    await scenario.press('ArrowDown')
    await expect(menu).toBeVisible()
    await scenario.press('End')
    await scenario.press('Escape')
    await expect(scenario).toHaveValue('academic')
    await scenario.press('ArrowDown')
    await scenario.press('Home')
    await scenario.press('Enter')
    await expect(scenario).toHaveValue('general')
    await scenario.press('ArrowDown')
    await scenario.press('ArrowDown')
    await scenario.press('Tab')
    await expect(scenario).toHaveValue('academic')
    await expect(menu).toHaveCount(0)
    await expect(scenario.locator('option[aria-hidden]')).toHaveCount(0)
  }
  await page.locator('[data-open-settings]').click()
  const dialog = page.getByRole('dialog', { name: '检查设置', exact: true })
  const language = dialog.getByRole('combobox', { name: 'OCR 识别语言' })
  await language.click()
  await expect(dialog.getByRole('listbox')).toBeVisible()
  await language.press('Escape')
  await expect(dialog).toBeVisible()
  await expect(language).toBeFocused()
  await language.click()
  await dialog.getByRole('option', { name: '日文' }).click()
  await expect(language).toHaveValue('ja')
  await language.click()
  await dialog.getByRole('heading', { name: '检查设置', exact: true }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
})

test('dropdown remains open after scrolling its control away from the viewport edge', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 600 })
  await page.goto('/')
  await page.locator('[data-open-settings]').click()
  const dialog = page.getByRole('dialog', { name: '检查设置', exact: true })
  const language = dialog.getByRole('combobox', { name: 'OCR 识别语言' })
  await language.scrollIntoViewIfNeeded()
  await dialog.evaluate((element) => {
    const control = element.querySelector('[aria-label="OCR 识别语言"]')!
    element.scrollTop += control.getBoundingClientRect().bottom - (window.innerHeight - 52)
  })
  const beforeScroll = await dialog.evaluate((element) => element.scrollTop)
  const before = (await language.boundingBox())!
  expect(600 - before.y - before.height).toBeLessThan(120)
  await language.click()
  await expect.poll(() => dialog.evaluate((element) => element.scrollTop)).toBeGreaterThan(beforeScroll)
  const menu = dialog.getByRole('listbox')
  await expect(menu).toBeVisible()
  const anchor = (await language.boundingBox())!
  expect((await menu.boundingBox())!.y).toBeCloseTo(anchor.y + anchor.height + 2, 0)
  await dialog.evaluate((element) => { element.scrollTop -= 16 })
  await expect.poll(async () => {
    const control = (await language.boundingBox())!
    return Math.abs((await menu.boundingBox())!.y - control.y - control.height - 2)
  }).toBeLessThan(1)
  await language.press('Escape')
  await expect(menu).toHaveCount(0)
  await expect(dialog).toBeVisible()
  await expect(language).toHaveValue('zh')
  await expect(language).toBeFocused()
  await language.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('focus uses existing borders or thin inside indicators across setup and settings', async ({ page }) => {
  await page.goto('/')
  await page.keyboard.press('Tab')
  const primary = await page.locator('[data-submit-source]').evaluate((element) =>
    getComputedStyle(element).backgroundColor
  )
  async function expectBorderFocus(control: Locator) {
    await control.hover()
    await control.focus()
    await expect(control).toHaveCSS('outline-style', 'none')
    await expect(control).toHaveCSS('border-color', primary)
    await expect(control).toHaveCSS('border-width', '1px')
  }
  await expectBorderFocus(page.locator('.dropzone'))
  await expectBorderFocus(page.locator('[data-open-settings]'))
  await page.locator('[data-open-settings]').click()
  const dialog = page.getByRole('dialog', { name: '检查设置', exact: true })
  await expectBorderFocus(dialog.getByLabel('文档场景'))
  const checkbox = dialog.getByLabel('个人信息与凭证扫描')
  await checkbox.focus()
  await expect(checkbox).toHaveCSS('outline-width', '1px')
  await expect(checkbox).toHaveCSS('outline-offset', '-1px')
  const terms = dialog.getByRole('button', { name: /^术语 / })
  await terms.focus()
  await expect(terms).toHaveCSS('outline-width', '1px')
  await expect(terms).toHaveCSS('outline-offset', '-1px')
  await terms.click()
  await expectBorderFocus(dialog.getByLabel('原文写法'))
  await expectBorderFocus(dialog.getByLabel('规范写法'))
  await expectBorderFocus(dialog.locator('[data-action="import"]'))
  await dialog.getByRole('button', { name: /^禁用词 / }).click()
  await expectBorderFocus(dialog.getByLabel('输入禁用词'))
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '粘贴文本' }).click()
  await expectBorderFocus(page.getByLabel('待检查文本'))
  await page.getByLabel('待检查文本').fill('测试文字')
  const submit = page.locator('[data-submit-source]')
  await page.keyboard.press('Tab')
  await submit.focus()
  await expect(submit).toHaveCSS('outline-width', '1px')
  await expect(submit).toHaveCSS('outline-offset', '-3px')
  await expect(submit).toHaveCSS('outline-color',
    await submit.evaluate((element) => getComputedStyle(element).color))
})

test('setup supporting text stays readable and settings controls fit on a narrow screen', async ({ page }, testInfo) => {
  await page.goto('/')
  await page.screenshot({ path: testInfo.outputPath('setup-desktop.png') })
  for (const selector of ['.setup-heading p', '.options-summary', '.privacy-note', '.dropzone small']) {
    expect(await page.locator(selector).evaluate((element) =>
      parseFloat(getComputedStyle(element).fontSize)
    ), selector).toBeGreaterThanOrEqual(12)
  }
  await page.setViewportSize({ width: 320, height: 568 })
  await page.locator('[data-open-settings]').click()
  const dialog = page.getByRole('dialog', { name: '检查设置', exact: true })
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await dialog.getByLabel('个人信息与凭证扫描').uncheck()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-open-settings]')).toBeFocused()
})

test('review controls have readable labels and contrasting primary actions in both themes', async ({ page }, testInfo) => {
  const text = '帐号测试：请核对这份文档中的文字与表达。\n保留原文结构，逐项审阅修改建议。'
  await page.route('**/api/v1/analyze', (route) => route.fulfill({ json: {
    success: true, filename: '交付文档.txt', source_name: '交付文档.txt', file_type: 'txt',
    text, blocks: [block(text)], parser_name: 'compatibility-flat-text', parser_version: '1',
    stats: stats(text), issues: [issue(text)], summary: summary(),
    file_id: null, file_ext: null, document_id: documentId, verification_run_id: runId,
    source_version: sourceVersion, execution_mode: 'synchronous', analysis_mode: 'local_only',
    dictionary_versions: {}, degradation: { is_degraded: false, reasons: [] }, scenario: 'general'
  } }))
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: '粘贴文本' }).click()
  await page.getByLabel('待检查文本').fill(text)
  await page.locator('[data-submit-source]').click()
  await page.locator('[data-issue-role="list"]').click()
  await expect(page.locator('.marker-label')).toHaveText('显示问题标记')
  await expect(page.locator('.marker-label')).toHaveCSS('white-space', 'nowrap')
  await expect(page.getByLabel('查找内容', { exact: true })).not.toBeVisible()
  const documentBox = (await page.locator('.document-panel').boundingBox())!
  const issuesBox = (await page.locator('.issues-panel').boundingBox())!
  expect(documentBox.width).toBeGreaterThan(issuesBox.width * 2)
  expect(issuesBox.width).toBeGreaterThanOrEqual(320)
  expect(issuesBox.width).toBeLessThanOrEqual(360)
  const readingHeight = (await page.locator('.edit-preview > .document-content').boundingBox())!.height
  await page.locator('[data-action="toggle-search-replace"]').click()
  const searchPanel = page.locator('.search-panel')
  expect((await searchPanel.boundingBox())!.height).toBeLessThanOrEqual(100)
  expect(readingHeight - (await page.locator('.edit-preview > .document-content').boundingBox())!.height)
    .toBeLessThanOrEqual(100)
  expect(await searchPanel.evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true)
  await page.getByLabel('查找内容', { exact: true }).fill('文档')
  for (const theme of ['light', 'dark']) {
    if (theme === 'dark') await page.locator('[data-toggle-theme]').click()
    for (const selector of ['[data-search-input]', '[data-replacement-input]']) {
      const field = page.locator(selector)
      await field.hover()
      await field.focus()
      await expect(field).toHaveCSS('outline-style', 'none')
      await expect(field).toHaveCSS('box-shadow', 'none')
      await expect(field).toHaveCSS('border-width', '1px')
      const primary = await page.locator('[data-action="replace-all"]').evaluate((element) =>
        getComputedStyle(element).backgroundColor
      )
      await expect(field).toHaveCSS('border-color', primary)
    }
    await page.screenshot({ path: testInfo.outputPath(`review-${theme}.png`) })
    const selectedCard = page.locator('.issue-card.selected')
    await expect(selectedCard).not.toHaveCSS('box-shadow', /inset/)
    const borders = await selectedCard.evaluate((element) => {
      const style = getComputedStyle(element)
      return { left: parseFloat(style.borderLeftWidth), right: parseFloat(style.borderRightWidth) }
    })
    expect(borders.left).toBeGreaterThan(borders.right)
    expect(borders.left).toBe(1)
    await page.keyboard.press('Tab')
    await selectedCard.locator('.issue-select').focus()
    await expect(selectedCard.locator('.issue-select')).toHaveCSS('outline-width', '1px')
    await expect(selectedCard.locator('.issue-select')).toHaveCSS('outline-offset', '-1px')
    await expect(page.locator('.source-segment.selected').first()).toHaveCSS('outline-width', '1px')
    await expect(page.locator('.source-segment.selected').first()).toHaveCSS('outline-offset', '-1px')
    for (const selector of [
      '.search-replace-panel label', '.filters label', '.issue-meta', '.severity', '.issue-details blockquote'
    ]) {
      const sizes = await page.locator(selector).evaluateAll((elements) =>
        elements.map((element) => parseFloat(getComputedStyle(element).fontSize))
      )
      expect(sizes.length).toBeGreaterThan(0)
      expect(Math.min(...sizes), selector).toBeGreaterThanOrEqual(12)
    }
    const actions = page.locator('.search-replace-panel .actions button, .issue-actions button')
    for (const action of await actions.all()) {
      expect((await action.boundingBox())!.height).toBeGreaterThanOrEqual(36)
    }
    const contrast = await page.locator('[data-action="replace-all"]').evaluate((element) => {
      const style = getComputedStyle(element)
      const luminance = (color: string) => {
        const components = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map((value) => {
          const channel = value / 255
          return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
        })
        return components[0] * 0.2126 + components[1] * 0.7152 + components[2] * 0.0722
      }
      const foreground = luminance(style.color)
      const background = luminance(style.backgroundColor)
      return {
        ratio: (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05),
        color: style.color,
        background: style.backgroundColor,
        animations: element.getAnimations().map((animation) => animation.playState)
      }
    })
    expect(contrast.ratio, `${theme}: ${JSON.stringify(contrast)}`).toBeGreaterThanOrEqual(4.5)
  }
  await page.setViewportSize({ width: 1024, height: 900 })
  expect((await searchPanel.boundingBox())!.height).toBeLessThanOrEqual(100)
  expect(await searchPanel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.setViewportSize({ width: 1440, height: 900 })
  const divider = page.getByRole('separator', { name: '调整问题列表宽度' })
  await divider.focus()
  await page.keyboard.press('ArrowLeft')
  expect((await page.locator('.issues-panel').boundingBox())!.width).toBe(336)
  await page.keyboard.press('ArrowRight')
  expect((await page.locator('.issues-panel').boundingBox())!.width).toBe(320)
  const handle = (await divider.boundingBox())!
  await page.mouse.move(handle.x + handle.width / 2, handle.y + 100)
  await page.mouse.down()
  await page.mouse.move(handle.x + handle.width / 2 - 120, handle.y + 100, { steps: 8 })
  await page.mouse.up()
  expect((await page.locator('.issues-panel').boundingBox())!.width).toBe(440)
  await expect(page.locator('.review-grid')).not.toHaveClass(/is-resizing/)
  await divider.focus()
  await page.keyboard.press('Home')
  expect((await page.locator('.issues-panel').boundingBox())!.width).toBe(260)
  await page.keyboard.press('ArrowRight')
  expect((await page.locator('.issues-panel').boundingBox())!.width).toBe(260)
  await page.keyboard.press('Enter')
  expect((await page.locator('.issues-panel').boundingBox())!.width).toBe(320)
  await page.keyboard.press('End')
  expect((await page.locator('.issues-panel').boundingBox())!.width).toBe(640)
  await page.setViewportSize({ width: 844, height: 900 })
  expect((await page.locator('.document-panel').boundingBox())!.width).toBeGreaterThanOrEqual(360)
  await page.setViewportSize({ width: 1440, height: 900 })
  await divider.dblclick()
  expect((await page.locator('.issues-panel').boundingBox())!.width).toBe(320)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.pane-divider')).not.toBeVisible()
  await page.getByRole('button', { name: /^问题 1$/ }).click()
  await page.screenshot({ path: testInfo.outputPath('review-mobile-dark.png') })
  const utilityRows = await page.locator('.topbar .icon-btn').evaluateAll((buttons) =>
    buttons.map((button) => button.getBoundingClientRect().top)
  )
  expect(new Set(utilityRows).size).toBe(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: '文档', exact: true }).click()
  await page.locator('[data-action="start-edit"]').click()
  await page.locator('[data-edit-input]').fill(`${text}\n补充说明。`)
  await page.locator('[data-action="save-edit"]').click()
  await expect(page.locator('.blocked-reason')).toBeVisible()
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 })
    const opener = page.locator('.topbar [data-open-settings]')
    const box = (await opener.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(width)
    await opener.click()
    await expect(page.getByRole('dialog', { name: '检查设置', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(opener).toBeFocused()
  }
  await page.screenshot({ path: testInfo.outputPath('review-mobile-edited.png') })
})

test('coverage limits stay visible while details collapse and recheck failures preserve the document', async ({ page }) => {
  const text = '帐号测试'
  let failed = false
  await page.route('**/api/v1/analyze', (route) => failed
    ? route.fulfill({ status: 503, json: { detail: '检查服务暂时不可用' } })
    : route.fulfill({ json: {
      success: true, filename: '研究文档.txt', source_name: '研究文档.txt', file_type: 'txt',
      text, blocks: [block(text)], parser_name: 'compatibility-flat-text', parser_version: '1',
      stats: stats(text), issues: [issue(text)], summary: {
        ...summary(), llm_review: { semantic_discovery: {
          enabled: true, sampled_chunks: 3, total_chunks: 20, truncated: true, reason: ''
        } }
      },
      file_id: null, file_ext: null, document_id: documentId, verification_run_id: runId,
      source_version: sourceVersion, execution_mode: 'synchronous', analysis_mode: 'local_only',
      dictionary_versions: {}, scenario: 'academic',
      degradation: { is_degraded: true, reasons: [
        'scenario_rule_skipped:scenario.academic.citation_reference:引文与参考文献对应'
      ] }
    } }))
  await page.setViewportSize({ width: 320, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: '粘贴文本' }).click()
  await page.getByLabel('待检查文本').fill(text)
  await page.locator('[data-submit-source]').click()
  const status = page.locator('[data-verification-status]')
  await expect(status.locator('summary')).toContainText('检查范围受限')
  await expect(status.locator('summary')).toContainText('未检查 1 项')
  await expect(status.locator('summary')).toContainText('3 / 20')
  await expect(page.locator('[data-skipped-rules]')).not.toBeVisible()
  await status.locator('summary').click()
  await expect(page.locator('[data-skipped-rules]')).toBeVisible()
  await expect(page.locator('[data-semantic-status]')).toContainText('非全文覆盖')
  expect((await page.locator('.review-grid').boundingBox())!.height).toBeGreaterThan(150)
  await status.locator('summary').click()
  failed = true
  await page.getByRole('button', { name: '重新检查', exact: true }).click()
  await expect(page.locator('[data-review-execution-error]')).toBeVisible()
  await expect(page.locator('[data-source-text]')).toHaveText(text)
  await expect(status.locator('summary')).toContainText('检查范围受限')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
})

test('minimal setup preserves advanced options and remains usable at desktop and mobile widths', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: /^检查设置/ })).toHaveCount(1)
  await expect(page.locator('.input-card [data-open-settings]')).toBeVisible()
  await expect(page.locator('.topbar [data-open-settings]')).toHaveCount(0)
  await page.getByRole('button', { name: '粘贴文本' }).click()
  await expect(page.getByRole('button', { name: /^检查设置/ })).toHaveCount(1)
  await page.getByRole('button', { name: '上传文件' }).click()
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

test('review settings stay accessible on desktop and mobile and apply only on recheck', async ({ page }) => {
  const text = '帐号测试'
  const submissions: FormData[] = []
  await page.route('**/api/v1/analyze', async (route) => {
    const request = route.request()
    const body = await new Response(request.postDataBuffer(), {
      headers: { 'Content-Type': request.headers()['content-type'] }
    }).formData()
    submissions.push(body)
    const submitted = String(body.get('text'))
    await route.fulfill({ json: {
      success: true,
      filename: '设置检查.txt',
      source_name: '设置检查.txt',
      file_type: 'txt',
      text: submitted,
      blocks: [block(submitted)],
      parser_name: 'compatibility-flat-text',
      parser_version: '1',
      stats: stats(submitted),
      issues: [issue(submitted)],
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
      scenario: body.get('scenario')
    } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '粘贴文本' }).click()
  await page.getByLabel('待检查文本').fill(text)
  await page.locator('[data-submit-source]').click()
  await expect(page.locator('.review-grid')).toBeVisible()
  await expect(page.locator('.review-summary button, .review-summary summary')).toHaveCount(0)
  await expect(page.locator('.document-panel .search-panel [data-search-input]')).toHaveCount(1)
  await expect(page.locator('.issues-panel [data-search-input]')).toHaveCount(0)
  const opener = page.locator('.topbar [data-open-settings]')
  const dialog = page.getByRole('dialog', { name: '检查设置', exact: true })
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await page.locator('.header-document').click()
    await expect(opener).toHaveCSS('border-color', 'rgba(0, 0, 0, 0)')
    const buttonStyles = await page.locator(
      '.topbar [data-open-settings], .topbar [data-action="recheck"], .topbar [data-toggle-export]'
    ).evaluateAll((buttons) => buttons.map((button) => {
      const style = getComputedStyle(button)
      return {
        fontSize: style.fontSize,
        fontWeight: style.fontWeight,
        lineHeight: style.lineHeight,
        padding: style.padding,
        borderRadius: style.borderRadius,
        borderColor: style.borderColor,
        background: style.backgroundColor,
        color: style.color,
        boxShadow: style.boxShadow,
        height: button.getBoundingClientRect().height
      }
    }))
    expect(buttonStyles).toHaveLength(3)
    expect(buttonStyles[0]).toEqual(buttonStyles[1])
    expect(buttonStyles[0]).toEqual(buttonStyles[2])
    await expect(opener).toBeVisible()
    await opener.click()
    await expect(dialog).toBeVisible()
    await dialog.getByLabel('文档场景').selectOption('news')
    await dialog.getByLabel('政治与敏感表述检查').uncheck()
    await dialog.locator('#enable-extended-rules').check()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.keyboard.press('Escape')
    await expect(opener).toBeFocused()
    await expect(page.locator('[data-source-text]')).toHaveText(text)
    expect(submissions).toHaveLength(1)
  }
  await page.reload()
  await expect(page.locator('.review-grid')).toBeVisible()
  await opener.click()
  await expect(dialog.getByLabel('文档场景')).toHaveValue('news')
  await expect(dialog.getByLabel('政治与敏感表述检查')).not.toBeChecked()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '重新检查', exact: true }).click()
  await expect.poll(() => submissions.length).toBe(2)
  expect(submissions[1].get('text')).toBe(text)
  expect(submissions[1].get('scenario')).toBe('news')
  expect(submissions[1].get('enable_sensitive')).toBe('false')
  expect(submissions[1].get('enable_extended_rules')).toBe('true')
})

test('unified layout locates an already-selected restored issue without changing views', async ({ page }) => {
  const prefix = '保留原文段落。\n'.repeat(100)
  const text = `${prefix}帐号测试`
  const start = Array.from(prefix).length
  await page.route('**/api/v1/analyze', (route) => route.fulfill({ json: {
    success: true, filename: 'long.txt', source_name: 'long.txt', file_type: 'txt',
    text, blocks: [block(text)], parser_name: 'compatibility-flat-text', parser_version: '1',
    stats: stats(text), issues: [{
      ...issue('帐号测试'), start, end: start + 2, block_start: start, block_end: start + 2,
      position: start, end_position: start + 2
    }],
    summary: summary(), file_id: null, file_ext: null, document_id: documentId,
    verification_run_id: runId, source_version: sourceVersion,
    execution_mode: 'synchronous', analysis_mode: 'local_only', dictionary_versions: {},
    degradation: { is_degraded: false, reasons: [] }, scenario: 'general'
  } }))
  await page.goto('/')
  await page.getByRole('button', { name: '粘贴文本' }).click()
  await page.getByLabel('待检查文本').fill(text)
  await page.locator('[data-submit-source]').click()
  await page.locator('[data-issue-role="list"]').click()
  await page.evaluate((jobId) => {
    const saved = JSON.parse(sessionStorage.getItem('text-verification-session')!)
    saved.workspace.result.execution_mode = 'asynchronous'
    saved.workspace.result.file_type = 'docx'
    saved.workspace.result.filename = 'long.docx'
    saved.workspace.result.source_name = 'long.docx'
    saved.jobId = jobId
    sessionStorage.setItem('text-verification-session', JSON.stringify(saved))
  }, jobId)
  await page.reload()
  await expect(page.locator('.layout-page').first()).toBeVisible()
  await page.locator('.layout-page img').first().evaluate((image: HTMLImageElement) => image.decode())
  await expect(page.locator('.layout-page img').first()).toHaveAttribute('src', /^data:image\/svg\+xml;base64,/)
  await expect(page.locator('[data-original-layout], [data-text-review]')).toHaveCount(0)
  await page.locator('.layout-scroll').evaluate((element) => { element.scrollTop = 0 })
  await page.locator('[data-issue-role="list"]').click()
  await expect(page.locator('.layout-issue.selected')).toBeVisible()
  await expect.poll(() => page.locator('.layout-scroll').evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0)
  const documentScroll = await page.evaluate(() => window.scrollY)
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (attempt > 0) {
      await page.locator('.layout-scroll').evaluate((element) => {
        element.scrollTop -= element.clientHeight / 4
      })
      await page.locator('[data-issue-role="list"]').click()
    }
    await expect.poll(() => page.locator('.layout-scroll').evaluate((element) => {
      const target = element.querySelector('.layout-issue.selected')!.getBoundingClientRect()
      const center = element.getBoundingClientRect().top + element.clientTop + element.clientHeight / 2
      return Math.abs((target.top + target.bottom) / 2 - center)
    })).toBeLessThan(2)
    expect(await page.evaluate(() => window.scrollY)).toBe(documentScroll)
  }
  const fitWidth = (await page.locator('.layout-page').first().boundingBox())!.width
  for (const scale of [25, 50, 75, 100]) {
    await page.getByRole('combobox', { name: '文档缩放' }).click()
    await page.getByRole('listbox').getByRole('option', { name: `${scale}%`, exact: true }).click()
    await expect.poll(async () =>
      (await page.locator('.layout-page').first().boundingBox())!.width / fitWidth
    ).toBeCloseTo(scale / 100, 2)
    const offset = await page.locator('.layout-scroll').evaluate((element) => {
      const pages = element.querySelector('.layout-pages')!.getBoundingClientRect()
      const viewportLeft = element.getBoundingClientRect().left + element.clientLeft
      return pages.left + pages.width / 2 - (viewportLeft + element.clientWidth / 2)
    })
    expect(Math.abs(offset)).toBeLessThan(1)
    await page.locator('[data-issue-role="list"]').click()
    await expect(page.locator('.layout-issue.selected')).toBeVisible()
  }
  await page.getByLabel('文档缩放').selectOption('fit')
  await expect.poll(async () =>
    (await page.locator('.layout-page').first().boundingBox())!.width
  ).toBeCloseTo(fitWidth, 1)
  await page.getByLabel('文档缩放').selectOption('200')
  await expect.poll(() => page.locator('.layout-scroll').evaluate((element) => element.scrollLeft))
    .toBeGreaterThan(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: /^问题 1$/ }).click()
  await page.locator('[data-issue-role="list"]').click()
  await expect(page.locator('.layout-issue.selected')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
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
    if (width > 760) {
      const panels = await page.locator('.review-grid').evaluate((element) =>
        ['.document-panel', '.issues-panel'].map((selector) => {
          const box = element.querySelector(selector)!.getBoundingClientRect()
          return { x: box.x, right: box.right, y: box.y, height: box.height, width: box.width }
        })
      )
      expect(panels[0].right).toBeLessThan(panels[1].x)
      expect(panels[0].width).toBeGreaterThan(panels[1].width)
      expect(panels[0].y).toBe(panels[1].y)
      expect(panels[0].height).toBe(panels[1].height)
    }
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
    const search = page.locator('.search-panel [data-search-input]')
    await expect(page.locator('[data-action="toggle-search-replace"]')).toHaveCount(1)
    await expect(page.getByRole('button', { name: /^(段落|紧凑)视图$/ })).toHaveCount(0)
    await page.keyboard.press('Control+f')
    await expect(search).toBeFocused()
    if (width > 760) {
      expect(await page.locator('.issue-list').evaluate(
        (element) => element.clientHeight
      )).toBeGreaterThanOrEqual(100)
    } else {
      await expect(page.locator('.search-panel')).toBeVisible()
      await expect(page.locator('.issues-panel')).not.toBeVisible()
    }
    const beforeSearch = await reviewLayout()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.keyboard.press('Escape')
    await expect(search).not.toBeVisible()
    await expect(page.locator('[data-action="toggle-search-replace"]')).toBeFocused()
    expect(await reviewLayout()).toEqual(beforeSearch)
    await page.keyboard.press('Meta+f')
    await expect(search).toBeFocused()
    expect(await reviewLayout()).toEqual(beforeSearch)

    const pageScrollBeforeNavigation = await page.evaluate(() => window.scrollY)
    if (width <= 760) {
      await page.getByRole('button', { name: '问题 1', exact: true }).click()
    }
    await page.locator('[data-issue-role="list"]').click()
    if (width <= 760) {
      await page.getByRole('button', { name: '文档', exact: true }).click()
    }
    const paneHeights = await page.evaluate(() => Object.fromEntries(
      ['.topbar', '.review-workspace', '.review-grid', '.edit-actions', '.search-panel', '.document-content']
        .map((selector) => [selector, document.querySelector(selector)?.getBoundingClientRect().height])
    ))
    expect(await content.evaluate((element) => element.clientHeight), JSON.stringify(paneHeights))
      .toBeGreaterThan(24)
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

    if (width <= 760) {
      await page.getByRole('button', { name: '问题 1', exact: true }).click()
    }
    await page.locator('.issue-actions').getByRole('button', { name: '接受', exact: true }).click()
    await showDocument()
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
    if (width <= 760) {
      await page.getByRole('button', { name: '问题 1', exact: true }).click()
    }
    await page.locator('.issue-actions').getByRole('button', { name: '撤销', exact: true }).click()
    await showDocument()
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

for (const status of ['queued', 'checking_chinese', 'completed', 'network-error', 'failed'] as const) {
  test(`pending ${status} task survives reload without duplicate upload`, async ({ page }) => {
    let uploads = 0
    let lookups = 0
    const queued = {
      job_id: jobId, source_name: 'synthetic.txt', file_type: 'txt', size_bytes: 12,
      status: 'queued', stage: 'queued', progress: 0,
      error_code: null, error_message: null, error_stage: null, error_retryable: null,
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString()
    }
    await page.addInitScript(() => {
      class SyntheticEventSource extends EventTarget {
        readyState = 1
        onerror: ((event: Event) => void) | null = null
        close() { this.readyState = 2 }
      }
      Object.defineProperty(window, 'EventSource', { value: SyntheticEventSource, configurable: true })
    })
    await page.route('**/api/v1/jobs', async (route) => {
      uploads += 1
      await route.fulfill({ json: queued })
    })
    await page.route(`**/api/v1/jobs/${jobId}`, async (route) => {
      lookups += 1
      if (status === 'network-error' && lookups === 1) {
        await route.fulfill({ status: 503, json: { detail: 'synthetic offline' } })
        return
      }
      const next = status === 'network-error' ? 'queued' : status
      await route.fulfill({ json: {
        ...queued, status: next, stage: next, progress: next === 'completed' ? 100 : 0
      } })
    })
    const text = '帐号测试'
    await page.route(`**/api/v1/jobs/${jobId}/result`, async (route) => {
      await route.fulfill({ json: {
        success: true, filename: 'synthetic.txt', source_name: 'synthetic.txt',
        file_type: 'txt', text, blocks: [block(text)],
        parser_name: 'compatibility-flat-text', parser_version: '1',
        stats: stats(text), issues: [issue(text)], summary: summary(),
        file_id: null, file_ext: null, document_id: jobId, verification_run_id: runId,
        source_version: sourceVersion, execution_mode: 'asynchronous', analysis_mode: 'local_only',
        dictionary_versions: {}, degradation: { is_degraded: false, reasons: [] }, scenario: 'general'
      } })
    })
    await page.goto('/')
    for (const viewport of [{ width: 1280, height: 720 }, { width: 1366, height: 768 }]) {
      await page.setViewportSize(viewport)
      await page.locator('input[type="file"]').evaluate((input) => {
        const transfer = new DataTransfer()
        transfer.items.add(new File(['帐号测试'], 'synthetic.txt', { type: 'text/plain' }))
        ;(input as HTMLInputElement).files = transfer.files
        input.dispatchEvent(new Event('change', { bubbles: true }))
      })
      await expect(page.locator('[data-dropzone]')).toHaveCount(0)
      const bounds = await page.locator('[data-submit-source]').boundingBox()
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height)
      expect(await page.evaluate(() => window.scrollY)).toBe(0)
    }
    await page.locator('[data-submit-source]').click()
    await expect(page.getByRole('progressbar', { name: '检查进度' })).toHaveAttribute('value', '0')
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('text-verification-pending-job'))).not.toBeNull()
    await page.reload()
    if (status === 'completed') {
      await expect(page.getByText('发现问题')).toBeVisible()
    } else if (status === 'failed') {
      await expect(page.getByRole('alert')).toBeVisible()
    } else {
      await expect(page.locator('[data-selected-file]')).toContainText('synthetic.txt')
      await expect(page.locator('[data-dropzone]')).toHaveCount(0)
      if (status === 'network-error') {
        await expect(page.getByRole('alert')).toBeVisible()
        await page.getByRole('button', { name: '重试连接' }).click()
      }
      await expect(page.getByRole('progressbar', { name: '检查进度' })).toBeVisible()
      await expect(page.locator('[data-submit-source]')).toBeDisabled()
      const bounds = await page.locator('[data-submit-source]').boundingBox()
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(768)
    }
    expect(uploads).toBe(1)
    expect(lookups).toBe(status === 'network-error' ? 2 : 1)
    if (status === 'completed' || status === 'failed') {
      expect(await page.evaluate(() => sessionStorage.getItem('text-verification-pending-job'))).toBeNull()
    }
  })
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
  await page.locator('[data-issue-role="list"]').click()
  await page.locator('.issue-actions').getByRole('button', { name: '接受', exact: true }).click()
  await expect(page.locator('[data-count="accepted"]')).toHaveText('1')
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
  const previewTexts: string[] = []
  await page.route(`**/api/v1/jobs/${jobId}/preview/layout`, async (route) => {
    const payload = route.request().postDataJSON()
    expect(payload.source_version).toBe(sourceVersion)
    previewTexts.push(payload.text)
    await route.fulfill({ json: reviewLayout(payload.text) })
  })
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
    page.locator('.topbar').getByTitle(`sample.${sourceType}`, { exact: true })
  ).toBeVisible()
  await expect(page.locator('[data-original-layout], [data-text-review]')).toHaveCount(0)
  await expect(page.locator('.layout-page img')).toBeVisible()
  if (sourceType === 'docx' && !undoBeforeExport) {
    for (const [width, height] of [[2000, 925], [1440, 900]]) {
      await page.setViewportSize({ width, height })
      const documentPane = (await page.locator('.document-panel').boundingBox())!
      expect(documentPane.x).toBeLessThanOrEqual(16)
      expect(documentPane.width).toBeGreaterThanOrEqual(width * .75)
      const viewport = page.getByRole('region', { name: '文档版式审阅' }).locator('.layout-scroll')
      await expect(page.locator('.edit-actions').getByLabel('文档缩放')).toBeVisible()
      expect((await viewport.boundingBox())!.height).toBeGreaterThanOrEqual(height * .83)
      await page.locator('[data-action="toggle-search-replace"]').click()
      expect((await viewport.boundingBox())!.y).toBeLessThanOrEqual(190)
      expect((await viewport.boundingBox())!.height).toBeGreaterThanOrEqual(height * .78)
      expect((await viewport.boundingBox())!.y + (await viewport.boundingBox())!.height)
        .toBeLessThanOrEqual(height)
      await page.locator('[data-action="toggle-search-replace"]').click()
    }
  }
  await page.locator('[data-issue-role="list"]').first().click()
  await expect(page.locator('.layout-issue.selected')).toBeVisible()
  await page.locator('.issue-actions').getByRole('button', { name: '接受', exact: true }).click()
  await expect(page.locator('[data-count="accepted"]')).toHaveText('1')
  await expect(page.locator('.layout-page img')).toHaveAttribute('alt', /账号测试/)
  await expect(page.locator('.layout-issue.accepted')).toBeVisible()
  expect(previewTexts).toEqual(['帐号测试', '账号测试'])

  if (undoBeforeExport) {
    await page.locator('[data-action="toggle-search-replace"]').click()
    await page.getByLabel('查找内容').fill('账号')
    await page.getByLabel('替换内容').fill('临时😀')
    await page.getByRole('button', { name: '替换当前', exact: true }).click()
    await expect(page.locator('.layout-page img')).toHaveAttribute('alt', /临时😀测试/)
    await page.getByRole('button', { name: '撤销修改', exact: true }).click()
    await expect(page.locator('.layout-page img')).toHaveAttribute('alt', /账号测试/)
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
      track_changes: false
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
  await expect(page.locator('.topbar').getByTitle('多段.docx')).toBeVisible()
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
  await expect(page.locator('.topbar').getByTitle('多段.docx')).toBeVisible()
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
  const progress = page.getByRole('progressbar', { name: '检查进度' })
  await expect(progress).toBeVisible()
  await expect(progress).toHaveAttribute('value', '40')
  await expect(progress).toHaveAttribute('aria-valuetext', '40% · 正在执行扫描件 OCR')
  await expect(page.getByRole('heading', { name: 'Job progress' })).toHaveCount(0)
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    const bounds = await page.locator('.source-input-panel').evaluate((element) => {
      const settings = element.querySelector('.setup-options')!.getBoundingClientRect()
      const progress = element.querySelector('progress')!.getBoundingClientRect()
      const submit = element.querySelector('[data-submit-source]')!.getBoundingClientRect()
      return {
        settingsBottom: settings.bottom,
        settingsLeft: settings.left,
        settingsWidth: settings.width,
        progressTop: progress.top,
        progressBottom: progress.bottom,
        progressLeft: progress.left,
        progressWidth: progress.width,
        progressHeight: progress.height,
        submitTop: submit.top
      }
    })
    expect(bounds.progressTop).toBeGreaterThanOrEqual(bounds.settingsBottom)
    expect(bounds.progressBottom).toBeLessThanOrEqual(bounds.submitTop)
    expect(bounds.progressHeight).toBeGreaterThan(0)
    expect(bounds.progressHeight).toBeLessThanOrEqual(8)
    expect(bounds.progressLeft).toBeCloseTo(bounds.settingsLeft, 0)
    expect(bounds.progressWidth).toBeCloseTo(bounds.settingsWidth, 0)
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.evaluate(() => {
    ;(window as unknown as { __finishOcrJob: () => void }).__finishOcrJob()
  })
  await expect(page.locator('.header-document')).toHaveText(
    'scanned-page.pdf'
  )
  await expect(page.locator('.layout-page img').first()).toBeVisible()
  await expect(page.locator('[data-original-layout], [data-text-review]')).toHaveCount(0)

  const downloadPromise = page.waitForEvent('download')
  await page.locator('[data-toggle-export]').click()
  await page.getByRole('button', { name: '导出修改文件' }).click()
  const download = await downloadPromise

  expect(exportRequests).toEqual([
    {
      format: 'docx_reconstruction',
      revision_id: null,
      track_changes: false
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
