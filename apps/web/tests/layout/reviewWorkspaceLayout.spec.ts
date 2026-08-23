import { expect, test, type Page } from '@playwright/test'

const desktopViewports = [
  { width: 1280, height: 800 },
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 }
] as const

const compactViewports = [
  { width: 768, height: 1024 },
  { width: 390, height: 844 }
] as const

const acceptanceViewports = [
  { width: 1280, height: 800 },
  { width: 1366, height: 768 },
  ...compactViewports
] as const

async function loadFixture(page: Page) {
  await page.goto('/tests/fixtures/review-workspace.html')
  await expect(page.locator('.review-workspace')).toBeVisible()
  await expect(page.locator('.document-block')).toHaveCount(30)
}

async function readControlMetrics(locator: ReturnType<Page['locator']>) {
  return locator.evaluate((node) => {
    if (!(node instanceof HTMLElement)) {
      throw new Error('Expected HTMLElement for geometry assertions')
    }

    const style = window.getComputedStyle(node)
    const textRange = document.createRange()
    textRange.selectNodeContents(node)
    const textLineCount = Array.from(textRange.getClientRects()).filter(
      (rect) => rect.width > 0 && rect.height > 0
    ).length

    return {
      writingMode: style.writingMode,
      whiteSpace: style.whiteSpace,
      scrollWidth: node.scrollWidth,
      clientWidth: node.clientWidth,
      scrollHeight: node.scrollHeight,
      clientHeight: node.clientHeight,
      textLineCount
    }
  })
}

function expectDefinedBox(
  box: Awaited<ReturnType<ReturnType<Page['locator']>['boundingBox']>>
): asserts box is NonNullable<typeof box> {
  expect(box).not.toBeNull()
}

async function clickWorkspaceTool(page: Page, tool: string) {
  await page.locator(`[data-tool="${tool}"]`).click()
}

async function openDocumentPanel(page: Page, viewportWidth: number) {
  if (viewportWidth < 1280) {
    await clickWorkspaceTool(page, 'document')
  }
}

async function assertNoPageScroll(page: Page) {
  const metrics = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    innerHeight: window.innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth
  }))

  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.innerHeight)
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.innerWidth)
}

async function assertButtonsAreTouchSized(page: Page, selectors: string[]) {
  const buttons = page.locator(
    selectors.join(', ')
  )
  const count = await buttons.count()
  expect(count).toBeGreaterThan(0)

  for (let index = 0; index < count; index += 1) {
    const button = buttons.nth(index)
    await expect(button).toBeVisible()
    const box = await button.boundingBox()
    expectDefinedBox(box)
    expect(Math.round(box.width)).toBeGreaterThanOrEqual(44)
    expect(Math.round(box.height)).toBeGreaterThanOrEqual(44)
  }
}

async function assertDocumentEditorIsContained(page: Page) {
  const documentViewer = page.locator('.document-viewer')
  const editor = page.locator('.document-editor')
  const saveButton = page.getByRole('button', { name: '保存草稿并重新检查' })
  const discardButton = page.getByRole('button', { name: '放弃草稿' })
  const [viewerBox, editorBox, saveBox, discardBox] = await Promise.all([
    documentViewer.boundingBox(),
    editor.boundingBox(),
    saveButton.boundingBox(),
    discardButton.boundingBox()
  ])

  expectDefinedBox(viewerBox)
  expectDefinedBox(editorBox)
  expectDefinedBox(saveBox)
  expectDefinedBox(discardBox)
  for (const box of [editorBox, saveBox, discardBox]) {
    expect(box.x).toBeGreaterThanOrEqual(viewerBox.x)
    expect(box.x + box.width).toBeLessThanOrEqual(viewerBox.x + viewerBox.width)
    expect(box.y).toBeGreaterThanOrEqual(viewerBox.y)
    expect(box.y + box.height).toBeLessThanOrEqual(viewerBox.y + viewerBox.height)
  }

  await expect(saveButton).toBeInViewport()
  await expect(discardButton).toBeInViewport()
  await assertButtonsAreTouchSized(page, ['.document-editor__actions button'])
}

async function assertDesktopVersionToolbarDoesNotWrap(page: Page) {
  const metrics = await page.locator('.version-toolbar').evaluate((toolbar) => {
    const style = window.getComputedStyle(toolbar)
    const bottoms = Array.from(toolbar.children).map(
      (child) => child.getBoundingClientRect().bottom
    )

    return {
      flexDirection: style.flexDirection,
      bottomSpread: Math.max(...bottoms) - Math.min(...bottoms),
      scrollHeight: (toolbar as HTMLElement).scrollHeight,
      clientHeight: (toolbar as HTMLElement).clientHeight
    }
  })

  expect(metrics.flexDirection).toBe('row')
  expect(metrics.bottomSpread).toBeLessThanOrEqual(4)
  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.clientHeight)
}

for (const viewport of acceptanceViewports) {
  test(`keeps review loop controls continuously usable at ${viewport.width}x${viewport.height}`, async ({
    page
  }) => {
    await page.setViewportSize(viewport)
    await loadFixture(page)

    await assertNoPageScroll(page)
    if (viewport.width >= 1280) {
      await assertDesktopVersionToolbarDoesNotWrap(page)
    }

    await clickWorkspaceTool(page, 'history')
    await expect(page.getByTestId('operation-history')).toBeInViewport()
    await expect(page.locator('[data-tool="export"]')).toBeInViewport()
    await assertButtonsAreTouchSized(page, [
      '[data-tool="history"]',
      '[data-tool="export"]',
      '[data-testid="history-undo-latest"]'
    ])

    await openDocumentPanel(page, viewport.width)
    await page.getByRole('button', { name: /编辑当前版本|从此版本创建新版本/ }).click()
    await expect(page.locator('.document-editor')).toBeVisible()
    await assertButtonsAreTouchSized(page, [
      'button[name="edit-version"]',
      '.version-toolbar__tabs button'
    ])
    await assertDocumentEditorIsContained(page)

    await clickWorkspaceTool(page, 'search')
    const searchInput = page.getByLabel('查找内容')
    await searchInput.fill('合同')
    await page.getByRole('button', { name: '下一处' }).click()
    await expect(searchInput).toBeInViewport()
    await expect(page.getByRole('button', { name: '下一处' })).toBeInViewport()
    await expect(page.getByRole('button', { name: '替换当前' })).toBeInViewport()
    await assertButtonsAreTouchSized(page, [
      '[data-tool="search"]',
      'button[name="previous-match"]',
      'button[name="next-match"]',
      'button[name="clear-find"]',
      'button[name="replace-current"]',
      'button[name="replace-all"]'
    ])

    await clickWorkspaceTool(page, 'issues')
    await page.locator('.issue-card').first().click()
    if (viewport.width >= 1280) {
      await expect(page.locator('.context-inspector')).toBeInViewport()
    } else {
      await expect(page.locator('.issue-panel')).toBeInViewport()
    }

    await assertNoPageScroll(page)
  })
}

for (const viewport of desktopViewports) {
  test(`keeps desktop geometry stable at ${viewport.width}x${viewport.height}`, async ({
    page
  }) => {
    await page.setViewportSize(viewport)
    await loadFixture(page)

    const rail = page.getByRole('navigation', { name: '审阅工具' })
    const sidePanel = page.locator('.workspace-side-panel')
    const documentViewer = page.locator('.document-viewer')
    const inspector = page.locator('.context-inspector')

    const [railBox, sidePanelBox, documentBox, inspectorBox, hasOuterScroll] =
      await Promise.all([
        rail.boundingBox(),
        sidePanel.boundingBox(),
        documentViewer.boundingBox(),
        inspector.boundingBox(),
        page.evaluate(
          () =>
            document.documentElement.scrollHeight > window.innerHeight ||
            document.documentElement.scrollWidth > window.innerWidth
        )
      ])

    expectDefinedBox(railBox)
    expectDefinedBox(sidePanelBox)
    expectDefinedBox(documentBox)
    expectDefinedBox(inspectorBox)

    expect(hasOuterScroll).toBe(false)
    expect(Math.round(railBox.width)).toBe(64)
    expect(documentBox.width).toBeGreaterThan(inspectorBox.width)
    expect(sidePanelBox.x).toBeGreaterThanOrEqual(railBox.x + railBox.width)
    expect(documentBox.x).toBeGreaterThanOrEqual(sidePanelBox.x + sidePanelBox.width)
    expect(inspectorBox.x).toBeGreaterThanOrEqual(documentBox.x + documentBox.width)
  })
}

test('switches exactly at the 1279/1280 breakpoint boundary', async ({ page }) => {
  await page.setViewportSize({ width: 1279, height: 800 })
  await loadFixture(page)

  await expect(page.getByRole('navigation', { name: '工作台视图' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '审阅工具' })).toHaveCount(0)

  await page.setViewportSize({ width: 1280, height: 800 })

  await expect(page.getByRole('navigation', { name: '审阅工具' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '工作台视图' })).toHaveCount(0)
})

for (const viewport of compactViewports) {
  test(`keeps compact search controls horizontal and export dialog in bounds at ${viewport.width}x${viewport.height}`, async ({
    page
  }) => {
    await page.setViewportSize(viewport)
    await loadFixture(page)

    await page.getByRole('button', { name: /编辑当前版本|从此版本创建新版本/ }).click()
    await expect(page.locator('.document-editor')).toBeVisible()
    await page.getByRole('button', { name: /^查找$/ }).click()

    const searchInput = page.getByLabel('查找内容')
    const replaceInput = page.getByLabel('替换为')
    const actionButtons = [
      page.getByRole('button', { name: '上一处' }),
      page.getByRole('button', { name: '下一处' }),
      page.getByRole('button', { name: '替换当前' }),
      page.getByRole('button', { name: '全部替换' })
    ]

    await expect(searchInput).toBeInViewport()
    await expect(replaceInput).toBeInViewport()

    for (const button of actionButtons) {
      await expect(button).toBeInViewport()

      const metrics = await readControlMetrics(button)
      expect(metrics.writingMode).toBe('horizontal-tb')
      expect(metrics.textLineCount).toBeLessThanOrEqual(1)
      expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth)
      expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.clientHeight)
    }

    await page.getByRole('button', { name: /^导出$/ }).click()

    const dialog = page.getByRole('dialog', { name: '导出文件' })
    await expect(dialog).toBeVisible()

    const [dialogBox, hasHorizontalOverflow] = await Promise.all([
      dialog.boundingBox(),
      page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    ])

    expectDefinedBox(dialogBox)

    expect(hasHorizontalOverflow).toBe(false)
    expect(dialogBox.x).toBeGreaterThanOrEqual(0)
    expect(dialogBox.y).toBeGreaterThanOrEqual(0)
    expect(dialogBox.x + dialogBox.width).toBeLessThanOrEqual(viewport.width)
    expect(dialogBox.y + dialogBox.height).toBeLessThanOrEqual(viewport.height)
  })
}
