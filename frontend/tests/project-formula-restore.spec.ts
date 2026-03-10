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

async function applyFormulaAndCheckRestore(
  page: import('@playwright/test').Page,
  selector: string,
  formula: string,
) {
  const input = page.locator(selector).first()
  await expect(input).toBeVisible()
  await input.scrollIntoViewIfNeeded()

  await input.click()
  const originalValue = await input.inputValue()

  const selectAll = process.platform === 'darwin' ? 'Meta+A' : 'Control+A'
  await input.press(selectAll)
  await input.fill(formula)
  await input.press('Enter')
  await page.waitForTimeout(250)

  await input.press('Tab')
  await page.waitForTimeout(120)

  await input.click()
  await expect.poll(async () => (await input.inputValue()).trim(), { timeout: 1200 }).toBe(formula)

  await input.press(selectAll)
  await input.fill(originalValue)
  await input.press('Enter')
  await page.waitForTimeout(200)
}

test('expense inputs keep original formula on refocus after Enter', async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 })
  await page.goto('http://localhost:13011/projects/5', { waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  await closeOnboarding(page)

  const expensesTab = page.getByRole('button', { name: 'Расходы' })
  await expect(expensesTab).toBeVisible()
  await expensesTab.click()
  await page.waitForTimeout(250)

  await applyFormulaAndCheckRestore(page, '.expense-table td.col-unit input.input:not([readonly])', '1000+250')
  await applyFormulaAndCheckRestore(page, '.expense-table td.col-sum input.input:not([readonly])', '2000+333')
})
