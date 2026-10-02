import { expect, test } from '@playwright/test'

test.describe('network scenario save, validate, and run', () => {
  test.beforeEach(async ({ page }) => {
    page.on('dialog', (dialog) => dialog.accept())
  })

  test('creating from the nav picker, saving, validating, and running the plan', async ({
    page,
  }) => {
    test.setTimeout(180_000)

    await page.goto('/network')
    await expect(page.getByLabel('Network baseline filters')).toBeVisible({ timeout: 30_000 })

    // The network level starts minimal: no depot-level navigation.
    await expect(page.getByRole('link', { name: 'Depot', exact: true })).toBeHidden()
    await expect(page.getByRole('link', { name: 'Rates', exact: true })).toBeHidden()

    // Create a scenario from the nav picker.
    await page.getByLabel('Network scenario').selectOption('__new__')
    const nameInput = page.getByRole('textbox', { name: 'Network plan name', exact: true })
    await expect(nameInput).toBeVisible({
      timeout: 30_000,
    })
    await expect(nameInput).toHaveValue('New network plan')
    await expect(page.locator('header').getByText('draft', { exact: true })).toBeVisible()
    await expect(page.getByText('Unsaved changes')).toBeHidden()

    // Rename and edit an assumption: both persist without explicit save/validate.
    await nameInput.fill('E2E save flow')
    await nameInput.press('Enter')
    await expect(page.getByRole('heading', { name: 'E2E save flow' })).toBeVisible()
    const penalty = page.getByLabel('Unmet-demand penalty ($ / case)')
    await penalty.fill('300')
    await expect(page.getByText('Saved', { exact: true })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('heading', { name: 'E2E save flow' })).toBeVisible()
    await expect(penalty).toHaveValue('300')

    const scenarioId = new URL(page.url()).pathname.split('/')[3]
    const scenarios = await page.request.get('/api/network/scenarios')
    const persisted = (
      (await scenarios.json()) as { scenario_id: string; revision: number }[]
    ).find((row) => row.scenario_id === scenarioId)
    expect(persisted?.revision).toBe(3)

    // The scenario workspace tabs are in the top nav.
    await expect(page.getByRole('link', { name: 'Plan flow' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Rate audit' })).toBeVisible()

    await page.getByRole('button', { name: 'Run fixed-capacity plan' }).click()
    await expect(page.getByText('Baseline vs. scenario')).toBeVisible({ timeout: 120_000 })
    const solvedScenario = await page.request.get(`/api/network/scenarios/${scenarioId}`)
    expect((await solvedScenario.json()).status).toBe('solved')
    await expect(page.getByText('Depots with changed flow')).toBeVisible()
    await expect(page.getByText('Unmet cases').first()).toBeVisible()

    // Editing a tariff and pressing the header Run action must solve that
    // unsaved draft, not silently rerun the previous revision.
    await page.getByRole('link', { name: 'Scenario', exact: true }).click()
    await page.getByRole('button', { name: 'Add tariff rule' }).click()
    await page.getByLabel('USD / case').fill('0.10')
    await page.getByRole('button', { name: 'Run fixed-capacity plan' }).click()
    await expect(page.getByText('Baseline vs. scenario')).toBeVisible({ timeout: 120_000 })
    const rerunScenario = await (await page.request.get(`/api/network/scenarios/${scenarioId}`)).json()
    const rerunResult = await (await page.request.get(`/api/network/scenarios/${scenarioId}/result`)).json()
    expect(rerunScenario.revision).toBe(4)
    expect(rerunScenario.assumptions.tariffs[0].amount_per_case).toBe(0.1)
    expect(rerunResult.tariff_total_cost).toBeGreaterThan(0)

    // Depot-level navigation stays hidden while working a network scenario.
    await expect(page.getByRole('link', { name: 'Inputs', exact: true })).toBeHidden()

    // Deleting from the scenario tab returns to the network overview.
    await page.getByRole('link', { name: 'Scenario', exact: true }).click()
    await page.getByRole('button', { name: 'Delete network plan' }).click()
    await expect(page).toHaveURL(/\/network(\?|$)/)
    await expect(page.getByLabel('Network baseline filters')).toBeVisible({ timeout: 30_000 })
  })

  test.afterEach(async ({ page }) => {
    const scenarios = await page.request.get('/api/network/scenarios')
    const rows = (await scenarios.json()) as { scenario_id: string; scenario_name: string }[]
    for (const row of rows.filter((item) => item.scenario_name === 'E2E save flow')) {
      await page.request.delete(`/api/network/scenarios/${row.scenario_id}`)
    }
  })
})
