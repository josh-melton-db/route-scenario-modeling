import { expect, test } from '@playwright/test'

test('DC drill-down preserves the pinned network and immediate service date', async ({ page }) => {
  const serviceDate = '2026-10-05'
  const dcId = 'DC_SOUTHEAST_ATLANTA'
  const depotId = 'DPT_SE_BIRMINGHAM'
  const common = { region_id: 'REGION_SOUTHEAST', location: { lat: 33.5, lng: -86.8 }, demand_units: 100, assigned_units: 80, capacity_units: 150, utilization_pct: 53, total_cost: 500, cost_per_unit: 6.25, on_time_pct: 100, connected_facility_count: 1, depot_count: 1, depot_analysis_available: true }
  const overview = {
    context: { scenario_id: 'network-1', horizon_start: serviceDate, horizon_end: '2026-10-11', region_id: 'ALL' },
    facilities: [
      { ...common, facility_id: dcId, facility_name: 'Atlanta Distribution Center', facility_type: 'distribution_center', parent_facility_id: null },
      { ...common, facility_id: depotId, facility_name: 'Birmingham Depot', facility_type: 'depot', parent_facility_id: dcId },
    ],
    lanes: [], kpis: { demand_units: 100, assigned_units: 80, unmet_units: 20 },
  }
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/network/options') return route.fulfill({ json: { default_demand_plan_version_id: 'demand-v1', default_capacity_plan_version_id: 'capacity-v1', default_horizon_start: serviceDate, default_horizon_end: '2026-10-11', facilities: [], regions: [], demand_plans: [], capacity_plans: [] } })
    if (path === '/api/network/runs/run-pinned') return route.fulfill({ json: { run_id: 'run-pinned', scenario_id: 'network-1', overview } })
    if (path === '/api/network/runs/run-pinned/depots/DPT_SE_BIRMINGHAM/plans') return route.fulfill({ json: {
      plan_set_id: 'plan-pinned', parent_run_id: 'run-pinned',
      depot: { depot_id: depotId, name: 'Birmingham Depot', region: 'Southeast', sales_territory: 'Southeast', location: common.location },
      horizon_start: serviceDate, horizon_end: serviceDate, route_scenario_id: 'default',
      scenarios: [{ route_scenario_id: 'default', scenario_name: 'Baseline', is_default: true }],
      days: [{ service_date: serviceDate, status: 'queued', default_status: 'queued', assigned_cases: 80, is_overridden: false }],
      coverage: { total_days: 1, solved_days: 0, queued_days: 1, running_days: 0, failed_days: 0 },
      kpis: null, is_partial: true,
    } })
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  await page.goto('/dc/DC_SOUTHEAST_ATLANTA?networkScenario=network-1&networkRun=run-pinned')
  await expect(page.getByRole('heading', { name: 'Atlanta Distribution Center' })).toBeVisible()
  await page.getByRole('link', { name: 'Birmingham Depot', exact: true }).click()
  await expect(page).toHaveURL(/\/analyze\?/)
  const context = new URL(page.url()).searchParams
  expect(context.get('networkRun')).toBe('run-pinned')
  expect(context.get('networkScenario')).toBe('network-1')
  expect(context.get('depot')).toBe(depotId)
  expect(context.get('date')).toBe(serviceDate)
  await expect(page.getByRole('link', { name: 'Scenarios', exact: true })).toBeVisible()
})
