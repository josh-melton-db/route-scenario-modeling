import { expect, test } from '@playwright/test'

test('delivery pricing defaults off, persists, and appears in the rate audit', async ({ page }) => {
  const options = await (await page.request.get('/api/network/options')).json()
  const response = await page.request.post('/api/network/scenarios', { data: {
    scenario_name: 'Delivery rate audit E2E',
    demand_plan_version_id: options.default_demand_plan_version_id,
    capacity_plan_version_id: options.default_capacity_plan_version_id,
    horizon_start: options.default_horizon_start,
    horizon_end: options.default_horizon_start,
    region_id: 'REGION_TOLA',
  } })
  expect(response.ok()).toBeTruthy()
  const scenario = await response.json()
  try {
    await page.goto(`/network/scenarios/${scenario.scenario_id}/scenario`)
    const toggle = page.getByRole('checkbox', { name: 'Use DELIVERY contract rates' })
    await expect(toggle).not.toBeChecked()
    await toggle.check()
    await expect(page.getByText('Saved', { exact: true })).toBeVisible()
    await page.reload()
    await expect(toggle).toBeChecked()
    await page.getByRole('button', { name: 'Run fixed-capacity plan' }).click()
    await expect(page.getByText('Baseline vs. scenario')).toBeVisible({ timeout: 120_000 })
    const result = await (await page.request.get(`/api/network/scenarios/${scenario.scenario_id}/result`)).json()
    expect(result.pricing_context.pricing_basis).toBe('comparable_pinned_dated_contracts_v2_delivery_contracts')
    const audit = await (await page.request.get(`/api/network/runs/${result.run_id}/charges?side=scenario&limit=250`)).json()
    expect(audit.items.some((row: { rate_source: string }) => row.rate_source === 'delivery_contract')).toBeTruthy()
    await page.getByRole('link', { name: 'Rate audit' }).click()
    await expect(page.getByText('Delivery contract', { exact: true }).first()).toBeVisible()
  } finally {
    await page.request.delete(`/api/network/scenarios/${scenario.scenario_id}`)
  }
})
