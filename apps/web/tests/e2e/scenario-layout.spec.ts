import { expect, test } from '@playwright/test'
import { scenarioCatalogFixture } from '../fixtures/scenarioCatalog'

test.beforeEach(async ({ page }) => {
  const scenarios = scenarioCatalogFixture()
  scenarios[0]!.description = '检查基础文字质量，不要求论文、合同、新闻或技术文档的专用结构。'
  await page.route('**/api/v1/scenarios', (route) => route.fulfill({ json: { scenarios } }))
})

test('groups scenario controls above a compact full-width rule summary', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  const rules = page.getByRole('region', { name: '场景规则' })
  await expect(rules).toContainText('通用文档规则包')
  const select = page.getByLabel('文档场景', { exact: true })
  const settings = page.locator('.input-card [data-open-settings]')
  const selectBox = (await select.boundingBox())!
  const settingsBox = (await settings.boundingBox())!
  await expect(page.locator('.scenario-header .scenario-field > span')).toHaveCount(0)
  expect(Math.abs(selectBox.y + selectBox.height / 2 - settingsBox.y - settingsBox.height / 2)).toBeLessThan(3)
  expect(settingsBox.x - selectBox.x - selectBox.width).toBeGreaterThanOrEqual(0)
  expect(settingsBox.x - selectBox.x - selectBox.width).toBeLessThanOrEqual(20)
  const summaryBox = (await rules.boundingBox())!
  const optionsBox = (await page.locator('.setup-options').boundingBox())!
  expect(Math.abs(selectBox.x - optionsBox.x)).toBeLessThan(2)
  expect(Math.abs(summaryBox.width - optionsBox.width)).toBeLessThan(2)
  expect(summaryBox.height).toBeLessThan(130)
  await expect(rules.locator('.rule-details')).not.toHaveAttribute('open', '')
  await rules.locator('.rule-details > summary').click()
  await expect(rules.locator('.rule-details')).toHaveAttribute('open', '')
  await rules.locator('.rule-details > summary').click()
  await page.screenshot({ path: testInfo.outputPath('compact-scenario-desktop.png') })
  await settings.click()
  await expect(page.getByRole('dialog', { name: '检查设置', exact: true })).toBeVisible()
})

test('keeps compact scenario controls and rule details usable on narrow screens', async ({ page }, testInfo) => {
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    const rules = page.getByRole('region', { name: '场景规则' })
    await expect(rules).toContainText('通用文档规则包')
    await page.getByLabel('文档场景', { exact: true }).selectOption('academic')
    await expect(rules).toContainText('学术论文专用检查')
    await rules.locator('.rule-details > summary').click()
    await expect(rules.getByText(/需完整文本/)).toBeVisible()
    expect(await page.locator('.input-card').evaluate((element) =>
      element.scrollWidth <= element.clientWidth
    )).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`compact-scenario-${width}.png`) })
    await page.locator('.input-card [data-open-settings]').click()
    await expect(page.getByRole('dialog', { name: '检查设置', exact: true })).toBeVisible()
  }
})
