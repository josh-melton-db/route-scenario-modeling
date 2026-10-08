import { expect, test } from '@playwright/test'

test('tariff decimals stay editable without autosaving each character', async ({ page }) => {
  await page.goto('/network')
  await expect(page.getByLabel('Network baseline filters')).toBeVisible({ timeout: 30_000 })
  await page.getByLabel('Network scenario').selectOption('__new__')
  const name = page.getByRole('textbox', { name: 'Network plan name', exact: true })
  await name.fill('Tariff entry regression')
  await name.press('Enter')
  await page.getByRole('button', { name: 'Add tariff rule' }).click()
  await expect(page.getByText('Saved', { exact: true })).toBeVisible({ timeout: 30_000 })
  const scenarioId = new URL(page.url()).pathname.split('/')[3]
  const endpoint = `/api/network/scenarios/${scenarioId}`
  const before = await (await page.request.get(endpoint)).json()
  const amount = page.getByLabel('USD / case')

  await amount.fill('')
  await amount.pressSequentially('.')
  await expect(amount).toHaveValue('.')
  // Pause beyond the scenario autosave delay to catch partial-value saves.
  await page.waitForTimeout(900)
  await expect(amount).toBeFocused()
  await expect(amount).toHaveValue('.')
  await amount.pressSequentially('1')
  await page.waitForTimeout(900)
  await expect(amount).toHaveValue('.1')
  const during = await (await page.request.get(endpoint)).json()
  expect(during.revision).toBe(before.revision)
  expect(during.assumptions.tariffs[0].amount_per_case).toBe(0)

  await amount.press('Tab')
  await expect.poll(async () => (await (await page.request.get(endpoint)).json()).assumptions.tariffs[0].amount_per_case).toBe(0.1)
  await expect(amount).toHaveValue('0.1')
  await amount.fill('0.25')
  await amount.press('Enter')
  await expect.poll(async () => (await (await page.request.get(endpoint)).json()).assumptions.tariffs[0].amount_per_case).toBe(0.25)
  await page.request.delete(endpoint)
})
