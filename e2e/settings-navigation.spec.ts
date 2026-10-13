import { expect, test } from '@playwright/test'

const appUrl = process.env.E2E_BASE_URL ?? ''

test.beforeEach(async ({ page }) => {
  await page.route(/^https?:\/\/[^/]+\/api\//, route => route.fulfill({ status: 503, json: { detail: 'Navigation-only test' } }))
})

test('settings retain network navigation from the baseline and after reload', async ({ page }) => {
  await page.goto(`${appUrl}/network?region=ALL`)
  await page.getByRole('link', { name: 'Setup and readiness' }).click()
  await expect(page).toHaveURL(/\/setup\?networkReturn=/)
  await expect(page.getByRole('navigation').getByLabel('Network scenario')).toBeVisible()
  await expect(page.getByRole('navigation').getByLabel('Depot', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('navigation').getByRole('link', { name: 'Inputs', exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('navigation').getByLabel('Network scenario')).toBeVisible()
  await expect(page.getByRole('navigation').getByLabel('Depot', { exact: true })).toHaveCount(0)
})

test('settings preserve scenario tabs and their original run context', async ({ page }) => {
  await page.goto(`${appUrl}/network/scenarios/NSC_TEST/flow?run=run-test`)
  await page.getByRole('link', { name: 'Setup and readiness' }).click()
  await expect(page.getByRole('navigation').getByRole('link', { name: 'Plan flow', exact: true })).toHaveAttribute('href', '/network/scenarios/NSC_TEST/flow?run=run-test')
  await expect(page.getByRole('navigation').getByRole('link', { name: 'Lane changes', exact: true })).toBeVisible()
  await expect(page.getByRole('navigation').getByLabel('Depot', { exact: true })).toHaveCount(0)
  await page.getByRole('navigation').getByRole('link', { name: 'Plan flow', exact: true }).click()
  await expect(page).toHaveURL(/\/network\/scenarios\/NSC_TEST\/flow\?run=run-test$/)
})

test('settings button is absent from depot and DC navigation', async ({ page }) => {
  for (const path of ['/analyze?depot=DPT_NORTH', '/scenario?depot=DPT_NORTH', '/data-editor?depot=DPT_NORTH', '/rates', '/dc/DC_TEST']) {
    await page.goto(`${appUrl}${path}`)
    await expect(page.getByRole('navigation').getByRole('link', { name: 'Setup and readiness' })).toHaveCount(0)
  }
})
