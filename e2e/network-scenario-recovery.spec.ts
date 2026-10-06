import { expect, test } from '@playwright/test'

test('restores network parameters after a backend reset without restoring a stale run', async ({ page }) => {
  let missing = false
  let created: Record<string, unknown> | null = null
  let runCalls = 0
  const original = {
    scenario_id: 'old-scenario', scenario_name: 'Tariff demo', baseline_scenario_id: 'baseline',
    source_baseline_revision_id: 'baseline-original', demand_plan_version_id: 'demand-v1',
    capacity_plan_version_id: 'capacity-v1', horizon_start: '2026-10-06', horizon_end: '2026-10-06',
    region_id: 'ALL', revision: 1, status: 'draft', validation: null,
    created_at: '2026-10-06T12:00:00Z', updated_at: '2026-10-06T12:00:00Z', solved_at: null,
    assumptions: { facility_capacity_retained_pct: {}, facility_supply_retained_pct: {},
      disabled_facility_ids: [], disabled_lane_ids: [], lane_cost_adjustments_pct: {}, demand_adjustments: [],
      dc_transfer_requests: [], unmet_penalty_per_case: 250,
      tariffs: [{ rule_id: 'tariff-1', origin_country: 'MX', destination_country: 'US',
        effective_start: '2026-10-06', effective_end: '2026-10-06', amount_per_case: 5 }] },
  }
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/network/scenarios/old-scenario') return missing
      ? route.fulfill({ status: 404, json: { detail: 'Network scenario not found.' } })
      : route.fulfill({ json: original })
    if (path === '/api/network/scenarios' && route.request().method() === 'POST') {
      created = route.request().postDataJSON()
      return route.fulfill({ json: { ...original, scenario_id: 'restored-scenario' } })
    }
    if (path === '/api/network/scenarios/restored-scenario') return route.fulfill({ json: { ...original, scenario_id: 'restored-scenario' } })
    if (path.endsWith('/run')) {
      runCalls++
      return route.fulfill({ status: 500, json: {} })
    }
    if (path === '/api/network/options') return route.fulfill({ json: {
      regions: [{ region_id: 'ALL', region_name: 'All regions' }], facilities: [], demand_plans: [], capacity_plans: [],
      lane_types: ['LINEHAUL'], metrics: [], default_demand_plan_version_id: 'demand-v1', default_capacity_plan_version_id: 'capacity-v1',
      default_horizon_start: '2026-10-06', default_horizon_end: '2026-10-06', default_region_id: 'ALL',
      default_lane_type: 'LINEHAUL', default_metric: 'assigned_flow', source: 'e2e', freshness_at: '2026-10-06T12:00:00Z',
    } })
    if (path === '/api/network/overview') return route.fulfill({ json: { facilities: [], lanes: [] } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/network/scenarios/old-scenario/scenario')
  await expect(page.getByRole('heading', { name: 'Tariff demo', exact: true })).toBeVisible()
  missing = true
  await page.reload()
  await expect(page.getByRole('heading', { name: 'This network scenario is no longer available' })).toBeVisible()
  await page.getByRole('button', { name: 'Restore scenario parameters', exact: true }).click()
  await expect(page).toHaveURL(/\/network\/scenarios\/restored-scenario\/scenario$/)
  await expect(page.getByRole('heading', { name: 'Tariff demo', exact: true })).toBeVisible()
  expect(created).toMatchObject({ scenario_name: 'Tariff demo', source_baseline_revision_id: 'baseline-original',
    assumptions: { unmet_penalty_per_case: 250, tariffs: original.assumptions.tariffs } })
  expect(runCalls).toBe(0)
})
