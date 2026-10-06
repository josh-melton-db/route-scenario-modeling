import { expect, test, type Page } from '@playwright/test'

const appUrl = process.env.E2E_BASE_URL ?? ''
const serviceDate = '2026-10-06'
const baselineScenarioId = `baseline-plan-scenario.original.demand-v1.capacity-v1.${serviceDate}.${serviceDate}`
const baselineRunId = `baseline-plan-run.original.demand-v1.capacity-v1.${serviceDate}.${serviceDate}`

const scenario = {
  scenario_id: baselineScenarioId,
  scenario_name: 'Published baseline',
  baseline_scenario_id: 'baseline',
  source_baseline_revision_id: 'original',
  demand_plan_version_id: 'demand-v1',
  capacity_plan_version_id: 'capacity-v1',
  horizon_start: serviceDate,
  horizon_end: serviceDate,
  region_id: 'ALL',
  status: 'solved',
  revision: 1,
  assumptions: {
    disabled_facility_ids: [], disabled_lane_ids: [], lane_cost_adjustments_pct: {},
    unmet_penalty_per_case: 250, facility_supply_retained_pct: {},
    facility_capacity_retained_pct: {}, tariffs: [], dc_transfer_requests: [],
    source_baseline_revision_id: 'original', parent_run_id: null, release_overlays: [],
  },
  validation: null,
  created_at: `${serviceDate}T12:00:00Z`,
  updated_at: `${serviceDate}T12:00:00Z`,
  solved_at: `${serviceDate}T12:00:00Z`,
}

const overview = {
  context: { scenario_id: baselineScenarioId, demand_plan_version_id: 'demand-v1', capacity_plan_version_id: 'capacity-v1', horizon_start: serviceDate, horizon_end: serviceDate, region_id: 'ALL', lane_type: 'LINEHAUL', metric: 'assigned_flow' },
  kpis: { demand_units: 100, assigned_units: 80, unmet_units: 20, total_cost: 500, cost_per_unit: 6.25, on_time_pct: 100, utilization_pct: 40 },
  facilities: [], lanes: [], insights: [], summary: 'Baseline shortage', source: 'e2e', freshness_at: `${serviceDate}T12:00:00Z`, is_partial: false,
}

const options = {
  regions: [{ region_id: 'ALL', region_name: 'All regions' }], facilities: [], demand_plans: [], capacity_plans: [], lane_types: ['LINEHAUL'], metrics: [],
  default_demand_plan_version_id: 'demand-v1', default_capacity_plan_version_id: 'capacity-v1', default_horizon_start: serviceDate, default_horizon_end: serviceDate,
  default_region_id: 'ALL', default_lane_type: 'LINEHAUL', default_metric: 'assigned_flow', source: 'e2e', freshness_at: `${serviceDate}T12:00:00Z`,
}

function result(evidence: 'available' | 'unavailable') {
  return {
    run_id: baselineRunId, scenario_id: baselineScenarioId, revision: 1,
    generated_at: `${serviceDate}T12:00:00Z`, overview, baseline_overview: overview,
    kpi_deltas: { demand_units: 0, assigned_units: 0, unmet_units: 0, total_cost: 0, cost_per_unit: 0, on_time_pct: 0, utilization_pct: 0 },
    affected_depot_ids: [], charge_details: [], exception_evidence_status: evidence,
    exception_evidence_message: evidence === 'unavailable' ? 'Dated baseline inputs were not published.' : null,
    exceptions: evidence === 'available' ? [{
      exception_id: 'BASELINE_UNMET', exception_type: 'unmet_demand', severity: 'critical', service_date: serviceDate,
      entity_type: 'facility', entity_id: 'DPT_ALPHA', message: '20 cases are unassigned.', demand_units: 100, assigned_units: 80, unmet_units: 20, shortage_cause: 'unknown',
    }] : [],
  }
}

async function mockBaseline(page: Page, evidence: 'available' | 'unavailable') {
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/network/baseline') return route.fulfill({ json: { original_revision_id: 'original', active_revision_id: 'original', active_run_id: null, active_plan_scenario_id: baselineScenarioId, active_plan_run_id: baselineRunId, accepted_at: null } })
    if (url.pathname === '/api/network/options') return route.fulfill({ json: options })
    if (url.pathname === '/api/network/scenarios' && route.request().method() === 'GET') return route.fulfill({ json: [] })
    if (url.pathname === `/api/network/scenarios/${baselineScenarioId}`) return route.fulfill({ json: scenario })
    if (url.pathname === `/api/network/scenarios/${baselineScenarioId}/result`) return route.fulfill({ json: result(evidence) })
    if (url.pathname === '/api/network/overview') return route.fulfill({ json: overview })
    if (url.pathname === '/api/network/scenarios' && route.request().method() === 'POST') return route.fulfill({ status: 201, json: { ...scenario, scenario_id: 'NSC_COPY', scenario_name: 'Published baseline — editable copy', status: 'draft', solved_at: null } })
    return route.fulfill({ status: 404, json: { detail: `Unhandled ${url.pathname}` } })
  })
}

test('baseline shortage review shows dated evidence and clones to an editable scenario', async ({ page }) => {
  await mockBaseline(page, 'available')
  await page.goto(`${appUrl}/network/scenarios/${baselineScenarioId}/exceptions`)
  await expect(page.getByLabel('Network scenario')).toHaveValue(baselineScenarioId)
  await expect(page.getByText('Dated unmet demand by depot')).toBeVisible()
  await expect(page.getByText('DPT_ALPHA')).toBeVisible()
  await page.getByRole('link', { name: 'Scenario' }).click()
  await expect(page.getByText('Published baseline is an immutable reference')).toBeVisible()
  await page.getByRole('button', { name: 'Create editable copy' }).click()
  await expect(page).toHaveURL(/\/network\/scenarios\/NSC_COPY\/scenario\?rename=1$/)
})

test('missing dated evidence does not claim the baseline has no exceptions', async ({ page }) => {
  await mockBaseline(page, 'unavailable')
  await page.goto(`${appUrl}/network/scenarios/${baselineScenarioId}/exceptions`)
  await expect(page.getByText('Dated exceptions are unavailable')).toBeVisible()
  await expect(page.getByText('Dated baseline inputs were not published.')).toBeVisible()
  await expect(page.getByText('No exceptions')).toHaveCount(0)
})

test('starts an editable tariff what-if from the visible baseline action', async ({ page }) => {
  await mockBaseline(page, 'available')
  await page.route('**/api/network/overview**', (route) => route.fulfill({ json: { ...overview, facilities: [{
    facility_id: 'DPT_ALPHA', facility_name: 'Alpha Depot', facility_type: 'depot', region_id: 'ALL', parent_facility_id: null,
    location: { lat: 40, lng: -86 }, demand_units: 100, assigned_units: 80, capacity_units: 200, utilization_pct: 40,
    total_cost: 500, cost_per_unit: 6.25, on_time_pct: 100, connected_facility_count: 1, depot_count: 1, depot_analysis_available: true,
  }] } }))
  let payload: Record<string, unknown> | null = null
  await page.route('**/api/network/baseline/plan-run**', (route) => route.fulfill({ json: { scenario_id: baselineScenarioId, run_id: baselineRunId } }))
  await page.route('**/api/network/scenarios', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    payload = route.request().postDataJSON()
    return route.fulfill({ status: 201, json: { ...scenario, scenario_id: 'NSC_TARIFF', status: 'draft' } })
  })
  await page.goto(`${appUrl}/network`)
  await expect(page.getByText('Mexico → US · $5 / case')).toBeVisible()
  await page.getByRole('button', { name: 'Simulate tariffs', exact: true }).click()
  await expect.poll(() => payload).toMatchObject({
    source_baseline_revision_id: 'original',
    assumptions: { tariffs: [{ origin_country: 'MX', destination_country: 'US', amount_per_case: 5, effective_start: serviceDate, effective_end: serviceDate }] },
  })
  await expect(page).toHaveURL(/network\/scenarios\/NSC_TARIFF\/scenario$/)
})
