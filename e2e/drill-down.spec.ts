import { expect, test } from '@playwright/test'

test('drilling from a distribution center into depot-level analysis', async ({ page }) => {
  await page.goto('/dc/DC_SOUTHEAST_ATLANTA')

  await expect(
    page.getByRole('heading', { name: 'Atlanta Distribution Center' }),
  ).toBeVisible()
  await expect(page.getByText('Depots served by this distribution center')).toBeVisible()

  // The constrained Southeast plan leaves unmet demand at this DC.
  await expect(page.getByText('Unmet demand')).toBeVisible()

  // The depot rows link into the lower-level analysis surface.
  const depotLink = page.getByRole('link', { name: /Depot routes/ }).first()
  await depotLink.click()

  await expect(page).toHaveURL(/\/analyze\?depot=DPT_SE_/)
  await expect(page.getByText('BASELINE ROUTES')).toBeVisible({ timeout: 60_000 })

  // The lower-level view exposes the depot navigation.
  await expect(page.getByRole('link', { name: 'Scenarios', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Inputs', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Network', exact: true })).toBeHidden()

  // The depot selector lists every network depot.
  const depotOptions = page.getByLabel('Depot').locator('option')
  await expect(depotOptions).toHaveCount(24, { timeout: 30_000 })

  // The return context brings the user back to the distribution center.
  await page.getByRole('link', { name: 'Back to network baseline' }).click()
  await expect(page).toHaveURL(/\/dc\/DC_SOUTHEAST_ATLANTA/)
  await expect(
    page.getByRole('heading', { name: 'Atlanta Distribution Center' }),
  ).toBeVisible()
})
