import { test, expect } from '@playwright/test'

async function closeOnboarding(page: import('@playwright/test').Page) {
  const clickIfVisible = async (name: string) => {
    const btn = page.getByRole('button', { name })
    if (await btn.isVisible().catch(() => false)) {
      await btn.click()
      await page.waitForTimeout(200)
    }
  }
  await clickIfVisible('Далее')
  await clickIfVisible('Далее')
  await clickIfVisible('Далее')
  await clickIfVisible('Завершить')
}

async function getTopZone(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const topEl = document.querySelector('.sticky-stack .top-panel') as HTMLElement | null
    const kpiEl = document.querySelector('.sticky-stack .dashboard-strip') as HTMLElement | null
    const tabsEl = document.querySelector('.tab-row') as HTMLElement | null
    if (!topEl || !kpiEl || !tabsEl) return null
    const top = topEl.getBoundingClientRect()
    const kpi = kpiEl.getBoundingClientRect()
    const tabs = tabsEl.getBoundingClientRect()
    const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight - 20)
    return {
      topTop: top.top,
      kpiTop: kpi.top,
      tabsTop: tabs.top,
      maxScroll,
      scrollY: window.scrollY,
    }
  })
}

test('project page: fixed zone is only top summary area across all tabs', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 620 })
  await page.goto('http://localhost:13011/projects/5', { waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  await closeOnboarding(page)
  await page.waitForTimeout(200)

  const nav = page.locator('.nav')
  const sticky = page.locator('.sticky-stack')
  await expect(nav).toBeVisible()
  await expect(sticky).toBeVisible()

  for (const tabName of ['Расходы', 'Оплаты', 'Сметы'] as const) {
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.waitForTimeout(150)
    await page.getByRole('button', { name: tabName }).click()
    await page.waitForTimeout(250)

    const before = await getTopZone(page)
    expect(before).not.toBeNull()
    if (!before) return

    const target = Math.min(900, before.maxScroll)
    await page.evaluate((value) => window.scrollTo(0, value), target)
    await page.waitForTimeout(250)

    const after = await getTopZone(page)
    expect(after).not.toBeNull()
    if (!after) return

    expect(Math.abs(after.topTop - before.topTop)).toBeLessThanOrEqual(2)
    expect(Math.abs(after.kpiTop - before.kpiTop)).toBeLessThanOrEqual(2)
    if (target > 120) {
      expect(after.tabsTop).toBeLessThan(before.tabsTop - 80)
    }
  }

  await page.getByRole('button', { name: 'Расходы' }).click()
  await page.waitForTimeout(250)
  const groupControls = page.locator('.expense-sheet .expense-group-controls').first()
  await expect(groupControls).toBeVisible()
  const groupBefore = await groupControls.boundingBox()
  expect(groupBefore).not.toBeNull()
  if (!groupBefore) return

  await page.evaluate(() => window.scrollTo(0, 1200))
  await page.waitForTimeout(250)
  const groupAfter = await groupControls.boundingBox()
  expect(groupAfter).not.toBeNull()
  if (!groupAfter) return

  // "+ группа" is below red-line zone and must move with content.
  expect(groupAfter.y).toBeLessThan(groupBefore.y - 200)
})
