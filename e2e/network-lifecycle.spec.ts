import { expect, test } from '@playwright/test'

const appUrl = process.env.E2E_BASE_URL ?? ''
const serviceDate = '2026-09-30'
const overview = {
  context: { scenario_id: 'network-1', demand_plan_version_id: 'demand-v1', capacity_plan_version_id: 'capacity-v1', horizon_start: serviceDate, horizon_end: serviceDate, region_id: 'ALL', lane_type: 'LINEHAUL', metric: 'assigned_flow' },
  kpis: { demand_units: 100, assigned_units: 100, unmet_units: 0, total_cost: 500, cost_per_unit: 5, on_time_pct: 100, utilization_pct: 50 },
  facilities: [], lanes: [], insights: [], summary: 'Test network', source: 'e2e', freshness_at: `${serviceDate}T12:00:00Z`, is_partial: false,
}
const scenario = {
  scenario_id: 'network-1', scenario_name: 'Lifecycle plan', baseline_scenario_id: 'baseline', demand_plan_version_id: 'demand-v1', capacity_plan_version_id: 'capacity-v1', horizon_start: serviceDate, horizon_end: serviceDate, region_id: 'ALL', status: 'solved', revision: 1,
  assumptions: { disabled_facility_ids: [], disabled_lane_ids: [], lane_cost_adjustments_pct: {}, unmet_penalty_per_case: 250 }, validation: null, created_at: `${serviceDate}T10:00:00Z`, updated_at: `${serviceDate}T10:00:00Z`, solved_at: `${serviceDate}T10:00:00Z`,
}
const networkResult = {
  run_id: 'run-1', scenario_id: 'network-1', revision: 1, generated_at: `${serviceDate}T12:00:00Z`, overview, baseline_overview: overview,
  kpi_deltas: { demand_units: 0, assigned_units: 0, unmet_units: 0, total_cost: 0, cost_per_unit: 0, on_time_pct: 0, utilization_pct: 0 }, affected_depot_ids: [], charge_details: [], exceptions: [],
}
const coverage = { ready: false, covered_dates: 0, expected_dates: 1, covered_depots: 0, expected_depots: 1, message: 'Local routes still need optimization.' }

test('shows comparable pricing and audits baseline separately from scenario', async ({ page }) => {
  const charge = { service_date: serviceDate, assigned_units: 100, loads: 1, rate_source: 'governed_contract', contract_id: 'contract-1', contract_version_id: 'version-1', rate_book_snapshot_id: 'snapshot-1', charge_lines: [] }
  const priced = {
    ...networkResult,
    baseline_freight_total_cost: 450, baseline_tariff_total_cost: 30, baseline_total_modeled_cost: 480,
    freight_total_cost: 450, tariff_total_cost: 50, scenario_total_modeled_cost: 500,
    original_published_baseline_cost: 999,
    baseline_rate_coverage: { governed_charge_count: 1, fallback_charge_count: 0 },
    scenario_rate_coverage: { governed_charge_count: 1, fallback_charge_count: 0 },
    pricing_context: { pricing_basis: 'comparable_pinned_dated_contracts_v1', load_size_cases: 900, contract_version_ids: ['version-1'], rate_book_snapshot_ids: ['snapshot-1'], objective_cost_basis: 'dated_linear' },
    baseline_charge_details: [{ ...charge, lane_id: 'BASELINE_LANE', freight_total: 450, tariff_total: 30, total_cost: 480 }],
    charge_details: [{ ...charge, lane_id: 'SCENARIO_LANE', freight_total: 450, tariff_total: 50, total_cost: 500 }],
  }
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/network/runs/run-1') return route.fulfill({ json: priced })
    if (path === '/api/network/options') return route.fulfill({ json: { regions: [{ region_id: 'ALL', region_name: 'All regions' }], facilities: [], demand_plans: [], capacity_plans: [], lane_types: ['LINEHAUL'], metrics: [], default_demand_plan_version_id: 'demand-v1', default_capacity_plan_version_id: 'capacity-v1', default_horizon_start: serviceDate, default_horizon_end: serviceDate, default_region_id: 'ALL', default_lane_type: 'LINEHAUL', default_metric: 'assigned_flow', source: 'e2e', freshness_at: `${serviceDate}T12:00:00Z` } })
    if (path === '/api/network/overview') return route.fulfill({ json: overview })
    if (path === '/api/network/scenarios/network-1') return route.fulfill({ json: scenario })
    if (path === '/api/network/scenarios') return route.fulfill({ json: [scenario] })
    if (path === '/api/network/baseline') return route.fulfill({ json: { original_revision_id: 'original', active_revision_id: 'original', active_run_id: null, route_coverage: coverage } })
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  await page.goto(`${appUrl}/network/scenarios/network-1/flow?run=run-1`)
  await expect(page.getByLabel('Comparison pricing basis')).toContainText('same pinned, dated rate books')
  await page.getByRole('link', { name: 'Rate audit', exact: true }).click()
  await expect(page.getByLabel('Comparison pricing basis')).toContainText('Baseline freight $450 + tariffs $30 = $480')
  await expect(page.getByLabel('Comparison pricing basis')).toContainText('not used to calculate the comparable delta')
  await expect(page.getByRole('table')).toContainText('SCENARIO_LANE')
  await page.getByLabel('Audit plan').selectOption('baseline')
  await expect(page.getByRole('table')).toContainText('BASELINE_LANE')
  await expect(page.getByRole('table')).not.toContainText('SCENARIO_LANE')
})

test('main network depot links use the accepted baseline planning run and preserve filters', async ({ page }) => {
  const facility = { facility_id: 'DPT_TEST', facility_name: 'Test Depot', facility_type: 'depot', region_id: 'ALL', parent_facility_id: null, location: { lat: 40, lng: -86 }, demand_units: 100, assigned_units: 100, capacity_units: 200, utilization_pct: 50, total_cost: 500, cost_per_unit: 5, on_time_pct: 100, connected_facility_count: 1, depot_count: 1, depot_analysis_available: true }
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/network/options') return route.fulfill({ json: { regions: [{ region_id: 'ALL', region_name: 'All regions' }], facilities: [], demand_plans: [], capacity_plans: [], lane_types: ['LINEHAUL'], metrics: [], default_demand_plan_version_id: 'demand-v1', default_capacity_plan_version_id: 'capacity-v1', default_horizon_start: serviceDate, default_horizon_end: serviceDate, default_region_id: 'ALL', default_lane_type: 'LINEHAUL', default_metric: 'assigned_flow', source: 'e2e', freshness_at: `${serviceDate}T12:00:00Z` } })
    if (url.pathname === '/api/network/overview') return route.fulfill({ json: { ...overview, facilities: [facility] } })
    if (url.pathname === '/api/network/baseline') return route.fulfill({ json: { original_revision_id: 'original', active_revision_id: 'accepted', active_run_id: 'run-1', accepted_at: `${serviceDate}T12:00:00Z`, route_coverage: coverage } })
    if (url.pathname === '/api/network/baseline/plan-run') {
      expect(url.searchParams.get('capacity_plan_version_id')).toBe('capacity-v1')
      expect(url.searchParams.get('horizon_start')).toBe(serviceDate)
      return route.fulfill({ json: { ...networkResult, run_id: 'accepted-planning-run', scenario_id: 'accepted-planning-scenario' } })
    }
    if (url.pathname === '/api/network/scenarios') return route.fulfill({ json: [] })
    return route.fulfill({ status: 404, json: { detail: url.pathname } })
  })
  await page.goto(`${appUrl}/network?facility=DPT_TEST`)
  const link = page.getByRole('link', { name: 'Open depot analysis' })
  await expect(link).toBeVisible()
  const href = await link.getAttribute('href')
  const params = new URL(href!, appUrl || 'http://localhost').searchParams
  expect(params.get('networkRun')).toBe('accepted-planning-run')
  expect(params.get('networkScenario')).toBe('accepted-planning-scenario')
  expect(params.get('depot')).toBe('DPT_TEST')
  expect(params.get('date')).toBe(serviceDate)
  expect(params.get('networkReturn')).toContain('/network?facility=DPT_TEST')
})

test('proposes then accepts a pinned run and confirms baseline reset without changing history', async ({ page }) => {
  let accepted = false
  let reset = false
  const actions: string[] = []
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path === '/api/network/baseline') return route.fulfill({ json: { original_revision_id: 'original', active_revision_id: accepted && !reset ? 'accepted' : 'original', active_run_id: accepted && !reset ? 'run-1' : null, accepted_at: accepted && !reset ? `${serviceDate}T12:00:00Z` : null, route_coverage: coverage } })
    if (path === '/api/network/baseline/proposals' && method === 'POST') {
      expect(route.request().postDataJSON()).toEqual({ run_id: 'run-1' })
      actions.push('propose')
      return route.fulfill({ json: { proposal_id: 'proposal-1', run_id: 'run-1', source_revision_id: 'original', status: 'proposed', route_coverage: coverage } })
    }
    if (path === '/api/network/baseline/proposals/proposal-1/accept') { accepted = true; actions.push('accept'); return route.fulfill({ json: {} }) }
    if (path === '/api/network/baseline/reset') { reset = true; actions.push('reset'); return route.fulfill({ json: {} }) }
    if (path === '/api/network/runs/run-1') return route.fulfill({ json: networkResult })
    if (path === '/api/network/scenarios/network-1') return route.fulfill({ json: scenario })
    if (path === '/api/network/scenarios') return route.fulfill({ json: [scenario] })
    if (path === '/api/network/options') return route.fulfill({ json: { regions: [{ region_id: 'ALL', region_name: 'All regions' }], facilities: [], demand_plans: [], capacity_plans: [], lane_types: ['LINEHAUL'], metrics: [], default_demand_plan_version_id: 'demand-v1', default_capacity_plan_version_id: 'capacity-v1', default_horizon_start: serviceDate, default_horizon_end: serviceDate, default_region_id: 'ALL', default_lane_type: 'LINEHAUL', default_metric: 'assigned_flow', source: 'e2e', freshness_at: `${serviceDate}T12:00:00Z` } })
    if (path === '/api/network/overview') return route.fulfill({ json: overview })
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  await page.goto(`${appUrl}/network/scenarios/network-1/flow?run=run-1`)
  await page.getByRole('button', { name: 'Propose as baseline' }).click()
  await expect(page.getByText(/Proposal ready/)).toBeVisible()
  await page.getByRole('button', { name: 'Accept as baseline' }).click()
  await expect(page.getByText('This run is the active baseline')).toBeVisible()
  await expect(page.getByText(/Local routes still need optimization/)).toBeVisible()
  await page.getByRole('button', { name: 'Reset to original story' }).click()
  expect(reset).toBe(false)
  await page.getByRole('button', { name: 'Confirm reset' }).click()
  await expect(page.getByText('Original story baseline')).toBeVisible()
  await expect(page).toHaveURL(/flow\?run=run-1$/)
  expect(actions).toEqual(['propose', 'accept', 'reset'])
})

test('releases assigned but route-unserved cases and explicitly reruns the parent', async ({ page }) => {
  let pending = false
  let rerun = false
  const depot = { depot_id: 'DPT_TEST', name: 'Test Depot', region: 'North', sales_territory: 'North', location: { lat: 40, lng: -86 } }
  const kpis = { route_count: 0, driver_count: 0, vehicle_count: 0, total_miles: 0, drive_minutes: 0, service_minutes: 0, total_cases: 0, avg_stops_per_route: 0, avg_capacity_utilization_pct: 0, avg_driver_utilization_pct: 0, overtime_minutes: 0, missed_windows: 0, late_minutes: 0, total_revenue: 0, profit: 0,
    cost_breakdown: Object.fromEntries(['mileage_cost', 'labor_cost', 'overtime_cost', 'fixed_vehicle_cost', 'sla_penalty_cost', 'carrier_linehaul_cost', 'carrier_lane_cost', 'carrier_stop_cost', 'carrier_minimum_adjustment', 'fuel_surcharge_cost', 'accessorial_cost', 'volume_tier_adjustment', 'commitment_adjustment', 'total_cost'].map((key) => [key, 0])) }
  const result = { result_id: 'day-1', service_date: serviceDate, status: 'infeasible', routes: [], kpis, assigned_cases: 100, routed_cases: 0, unserved_cases: 100, diagnostics: ['Fixed fleet cannot serve demand'], matrix_source: 'haversine_circuity', created_at: `${serviceDate}T12:00:00Z` }
  const change = { change_id: 'change-1', status: 'pending', service_date: serviceDate, customer_id: 'CUST_1', cases: 40, depot_id: 'DPT_TEST', depot_plan_id: 'plan-1', route_scenario_id: 'named-1' }
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path === '/api/depot-plans/plan-1') return route.fulfill({ json: { plan_set_id: 'plan-1', parent_run_id: 'run-1', depot, horizon_start: serviceDate, horizon_end: serviceDate, route_scenario_id: 'named-1', scenarios: [{ route_scenario_id: 'default', scenario_name: 'Default', is_default: true }, { route_scenario_id: 'named-1', scenario_name: 'Release scenario', is_default: false }], days: [{ service_date: serviceDate, status: 'infeasible', default_status: 'infeasible', assigned_cases: 100, routed_cases: 0, unserved_cases: 100, total_cost: 0, is_overridden: false, selected_result_id: 'day-1', error: null }], coverage: { total_days: 1, solved_days: 1, queued_days: 0, running_days: 0, failed_days: 0 }, kpis, is_partial: false, resource_source: 'fixed test fleet' } })
    if (path === `/api/depot-plans/plan-1/days/${serviceDate}`) return route.fulfill({ json: { plan_set_id: 'plan-1', service_date: serviceDate, route_scenario_id: 'named-1', default_status: 'infeasible', override_status: null, default_result: result, selected_result: result, error: null } })
    if (path.endsWith('/release-targets')) return route.fulfill({ json: [{ customer_id: 'CUST_1', customer_name: 'Unserved customer', assigned_cases: 100 }] })
    if (path === '/api/network/runs/run-1/demand-changes') {
      if (method === 'POST') {
        expect(route.request().postDataJSON()).toEqual({ kind: 'release', depot_plan_id: 'plan-1', route_scenario_id: 'named-1', service_date: serviceDate, customer_id: 'CUST_1', cases: 40 })
        pending = true
        return route.fulfill({ json: change })
      }
      return route.fulfill({ json: pending ? [change] : [] })
    }
    if (path === '/api/network/runs/run-1/reassign') {
      rerun = true
      return route.fulfill({
        status: 202,
        json: { run_id: 'run-2', scenario_id: 'network-2', revision: 1, status: 'queued', status_url: '/api/network/run-requests/run-2', attempt_count: 0, error_code: null, error_message: null },
      })
    }
    if (path === '/api/network/run-requests/run-2') return route.fulfill({ json: { run_id: 'run-2', scenario_id: 'network-2', revision: 1, status: 'succeeded', status_url: '/api/network/run-requests/run-2', attempt_count: 1, error_code: null, error_message: null } })
    if (path === '/api/network/scenarios/network-2') return route.fulfill({ json: { ...scenario, scenario_id: 'network-2' } })
    if (path === '/api/network/runs/run-2') return route.fulfill({ json: { ...networkResult, run_id: 'run-2', scenario_id: 'network-2' } })
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  await page.goto(`${appUrl}/scenario?networkScenario=network-1&networkRun=run-1&depot=DPT_TEST&depotPlan=plan-1&routePlanScenario=named-1&date=${serviceDate}`)
  await page.getByLabel('Release customer').selectOption('CUST_1')
  await page.getByLabel('Release cases').fill('40')
  await page.getByRole('button', { name: 'Propose release' }).click()
  await expect(page.getByText(/1 pending release/)).toBeVisible()
  expect(rerun).toBe(false)
  await expect(page.getByText(/Assigned 100 · routed 0 · unserved 100/)).toBeVisible()
  await page.getByRole('button', { name: 'Rerun network with releases' }).click()
  await expect(page).toHaveURL(/network\/scenarios\/network-2\/flow\?run=run-2$/)
  expect(rerun).toBe(true)
})
