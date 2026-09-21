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
    await expect(page.getByRole('heading', { name: 'Network baseline' })).toBeVisible()

    // The network level starts minimal: no depot-level navigation.
    await expect(page.getByRole('link', { name: 'Depot', exact: true })).toBeHidden()
    await expect(page.getByRole('link', { name: 'Rates', exact: true })).toBeHidden()

    // Create a scenario from the nav picker.
    await page.getByLabel('Network scenario').selectOption('__new__')
    await expect(page.getByRole('heading', { name: 'New network plan' })).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.locator('header').getByText('draft', { exact: true })).toBeVisible()
    await expect(page.getByText('Unsaved changes')).toBeHidden()

    const saveButton = page.getByRole('button', { name: 'Save changes' })
    const validateButton = page.getByRole('button', { name: 'Validate', exact: true })
    await expect(saveButton).toBeDisabled()
    await expect(validateButton).toBeEnabled()

    // Rename and edit an assumption: the tab becomes dirty and blocks validation.
    await page.getByLabel('Scenario name').fill('E2E save flow')
    const penalty = page.getByLabel('Unmet-demand penalty ($ / case)')
    await penalty.fill('300')
    await expect(page.getByText('Unsaved changes')).toBeVisible()
    await expect(validateButton).toBeDisabled()
    await expect(saveButton).toBeEnabled()

    // Saving persists the edit and clears the unsaved state.
    await saveButton.click()
    await expect(page.getByText('Unsaved changes')).toBeHidden({ timeout: 30_000 })
    await expect(saveButton).toBeDisabled()
    await expect(validateButton).toBeEnabled()
    await expect(page.getByRole('heading', { name: 'E2E save flow' })).toBeVisible()
    await expect(penalty).toHaveValue('300')

    const scenarioId = new URL(page.url()).pathname.split('/')[3]
    const scenarios = await page.request.get('/api/network/scenarios')
    const persisted = (
      (await scenarios.json()) as { scenario_id: string; revision: number }[]
    ).find((row) => row.scenario_id === scenarioId)
    expect(persisted?.revision).toBe(2)

    // Validate, then run the fixed-capacity plan end to end.
    await validateButton.click()
    await expect(page.getByText(/Ready to solve with 1 advisory issue/)).toBeVisible({
      timeout: 30_000,
    })

    // The scenario workspace tabs are in the top nav.
    await expect(page.getByRole('link', { name: 'Plan flow' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Rate audit' })).toBeVisible()

    await page.getByRole('button', { name: 'Run fixed-capacity plan' }).click()
    await expect(page.getByText('Baseline vs. scenario')).toBeVisible({ timeout: 120_000 })
    await expect(page.locator('header').getByText('solved', { exact: true })).toBeVisible()
    await expect(page.getByText('Depots with changed flow')).toBeVisible()
    await expect(page.getByText('Unmet cases').first()).toBeVisible()

    // Depot-level navigation stays hidden while working a network scenario.
    await expect(page.getByRole('link', { name: 'Inputs', exact: true })).toBeHidden()

    // Deleting from the scenario tab returns to the network overview.
    await page.getByRole('link', { name: 'Scenario', exact: true }).click()
    await page.getByRole('button', { name: 'Delete scenario' }).click()
    await expect(page).toHaveURL(/\/network(\?|$)/)
    await expect(page.getByRole('heading', { name: 'Network baseline' })).toBeVisible()
  })

  test.afterEach(async ({ page }) => {
    const scenarios = await page.request.get('/api/network/scenarios')
    const rows = (await scenarios.json()) as { scenario_id: string; scenario_name: string }[]
    for (const row of rows.filter((item) => item.scenario_name === 'E2E save flow')) {
      await page.request.delete(`/api/network/scenarios/${row.scenario_id}`)
    }
  })
})
