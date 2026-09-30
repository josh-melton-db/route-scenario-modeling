import { expect, test } from '@playwright/test'

const scenarioId = 'network-scenario-1'
const runId = 'network-run-old'
const depotId = 'DPT_NORTH'
const serviceDate = '2026-09-01'
const networkReturn = `/network/scenarios/${scenarioId}/flow?run=${runId}`
const appUrl = process.env.E2E_BASE_URL ?? ''

const overview = {
  context: {
    scenario_id: scenarioId,
    demand_plan_version_id: 'demand-v1',
    capacity_plan_version_id: 'capacity-v1',
    horizon_start: '2026-09-01',
    horizon_end: '2026-09-30',
    region_id: 'ALL',
    lane_type: 'LINEHAUL',
    metric: 'assigned_flow',
  },
  kpis: {
    demand_units: 100,
    assigned_units: 100,
    unmet_units: 0,
    total_cost: 500,
    cost_per_unit: 5,
    on_time_pct: 100,
    utilization_pct: 50,
  },
  facilities: [],
  lanes: [],
  insights: [],
  summary: 'Pinned historical result',
  source: 'e2e',
  freshness_at: '2026-09-01T12:00:00Z',
  is_partial: false,
}

const scenario = {
  scenario_id: scenarioId,
  scenario_name: 'Pinned parent plan',
  baseline_scenario_id: 'baseline',
  demand_plan_version_id: 'demand-v1',
  capacity_plan_version_id: 'capacity-v1',
  horizon_start: '2026-09-01',
  horizon_end: '2026-09-30',
  region_id: 'ALL',
  status: 'solved',
  revision: 3,
  assumptions: {
    disabled_facility_ids: [],
    disabled_lane_ids: [],
    lane_cost_adjustments_pct: {},
    unmet_penalty_per_case: 250,
  },
  validation: null,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-20T10:00:00Z',
  solved_at: '2026-09-20T10:00:00Z',
}

test('preserves parent scenario, run, depot, and date across route navigation', async ({ page }) => {
  let historicalReads = 0
  await page.route('**/api/network/runs/*', async (route) => {
    historicalReads += 1
    await route.fulfill({
      json: {
        run_id: runId,
        scenario_id: scenarioId,
        revision: 1,
        generated_at: '2026-09-01T12:00:00Z',
        overview,
        baseline_overview: overview,
        kpi_deltas: {
          demand_units: 0,
          assigned_units: 0,
          unmet_units: 0,
          total_cost: 0,
          cost_per_unit: 0,
          on_time_pct: 0,
          utilization_pct: 0,
        },
        affected_depot_ids: [],
        charge_details: [],
        exceptions: [],
      },
    })
  })
  await page.route('**/api/network/scenarios/*/result', (route) =>
    route.fulfill({ status: 500, json: { detail: 'latest result must not be read' } }),
  )
  await page.route(`**/api/network/scenarios/${scenarioId}`, (route) => route.fulfill({ json: scenario }))
  await page.route('**/api/network/scenarios', (route) => route.fulfill({ json: [scenario] }))
  await page.route('**/api/network/options', (route) => route.fulfill({
    json: {
      regions: [{ region_id: 'ALL', region_name: 'All regions' }],
      facilities: [], demand_plans: [], capacity_plans: [],
      lane_types: ['LINEHAUL'], metrics: [],
      default_demand_plan_version_id: 'demand-v1',
      default_capacity_plan_version_id: 'capacity-v1',
      default_horizon_start: '2026-09-01', default_horizon_end: '2026-09-30',
      default_region_id: 'ALL', default_lane_type: 'LINEHAUL',
      default_metric: 'assigned_flow', source: 'e2e', freshness_at: '2026-09-01T12:00:00Z',
    },
  }))
  await page.route('**/api/network/overview**', (route) => route.fulfill({ json: overview }))
  await page.route('**/api/depots', (route) => route.fulfill({
    json: [{ depot_id: depotId, name: 'North Depot', region: 'North', sales_territory: 'North', location: { lat: 40, lng: -86 } }],
  }))
  await page.route('**/api/delivery-days', (route) => route.fulfill({ json: ['Tuesday'] }))

  await page.goto(`${appUrl}/network/scenarios/${scenarioId}/flow?run=${runId}`)
  await expect(page.getByText(/plan generated 9\/1\/2026/)).toBeVisible()
  expect(historicalReads).toBeGreaterThan(0)

  const routeContext = new URLSearchParams({
    networkScenario: scenarioId,
    networkRun: runId,
    depot: depotId,
    date: serviceDate,
    networkReturn,
  })
  await page.goto(`${appUrl}/analyze?${routeContext}`)

  await expect(page.getByRole('link', { name: 'Network' })).toHaveAttribute(
    'href',
    networkReturn,
  )
  await page.getByRole('link', { name: 'Scenarios' }).click()
  await expect(page).toHaveURL(new RegExp(`/scenario\\?.*networkScenario=${scenarioId}`))
  await expect(page).toHaveURL(new RegExp(`networkRun=${runId}`))
  await expect(page).toHaveURL(new RegExp(`depot=${depotId}`))
  await expect(page).toHaveURL(new RegExp(`date=${serviceDate}`))

  await page.getByRole('link', { name: 'Depot' }).click()
  await expect(page).toHaveURL(new RegExp(`/analyze\\?.*networkRun=${runId}`))
  await page.getByRole('link', { name: 'Network' }).click()
  await expect(page).toHaveURL(`${appUrl}/network/scenarios/${scenarioId}/flow?run=${runId}`)
  expect(historicalReads).toBeGreaterThan(1)
})
