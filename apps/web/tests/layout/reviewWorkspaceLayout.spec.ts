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

async function loadFixture(page: Page) {
  await page.goto('/tests/fixtures/review-workspace.html')
  await expect(page.locator('.review-workspace')).toBeVisible()
  await expect(page.locator('.document-block')).toHaveCount(30)
}

function expectDefinedBox(
  box: Awaited<ReturnType<ReturnType<Page['locator']>['boundingBox']>>
): asserts box is NonNullable<typeof box> {
  expect(box).not.toBeNull()
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

    await page.getByRole('button', { name: /^查找$/ }).click()

    const searchInput = page.getByLabel('查找内容')
    const nextMatchButton = page.getByRole('button', { name: '下一处' })
    await expect(searchInput).toBeInViewport()
    await expect(nextMatchButton).toBeVisible()
    expect(
      await nextMatchButton.evaluate((node) => window.getComputedStyle(node).writingMode)
    ).toBe('horizontal-tb')

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
