import { expect, test, type Route } from '@playwright/test'

const appUrl = process.env.E2E_BASE_URL ?? ''
const horizonStart = '2026-10-06'
const horizonEnd = '2026-10-08'

const facilities = [
  { facility_id: 'DC_ALPHA', facility_name: 'Alpha DC', facility_type: 'distribution_center', region_id: 'MIDWEST', parent_facility_id: null },
  { facility_id: 'DPT_ALPHA', facility_name: 'Alpha Depot', facility_type: 'depot', region_id: 'MIDWEST', parent_facility_id: 'DC_ALPHA' },
]

function scenario(id: string, revision = 3) {
  return {
    scenario_id: id,
    scenario_name: `${id} plan`,
    baseline_scenario_id: 'baseline',
    demand_plan_version_id: 'demand-v1',
    capacity_plan_version_id: 'capacity-v1',
    horizon_start: horizonStart,
    horizon_end: horizonEnd,
    region_id: 'MIDWEST',
    status: 'solved',
    revision,
    assumptions: {
      disabled_facility_ids: [],
      disabled_lane_ids: [],
      lane_cost_adjustments_pct: {},
      unmet_penalty_per_case: 250,
      facility_supply_retained_pct: {},
      facility_capacity_retained_pct: {},
    },
    validation: null,
    created_at: `${horizonStart}T10:00:00Z`,
    updated_at: `${horizonStart}T11:00:00Z`,
    solved_at: `${horizonStart}T12:00:00Z`,
  }
}

function facilityAggregate(name: string, supplyPct: number, handlingPct: number) {
  return {
    facility_id: `DC_${name.toUpperCase()}`,
    facility_name: `${name} DC`,
    facility_type: 'distribution_center',
    region_id: 'MIDWEST',
    parent_facility_id: null as string | null,
    location: { lat: 40, lng: -86 },
    demand_units: 100,
    assigned_units: 80,
    capacity_units: 200,
    normal_supply_units: 160,
    supply_units: 120,
    supply_available_units: 120,
    supply_utilization_pct: 66.7,
    supply_retained_pct: supplyPct,
    supply_source: 'canonical_daily_supply',
    handling_capacity_units: 200,
    handling_available_units: 180,
    handling_utilization_pct: 44.4,
    handling_retained_pct: handlingPct,
    utilization_pct: 40,
    total_cost: 500,
    cost_per_unit: 6.25,
    on_time_pct: 100,
    connected_facility_count: 1,
    depot_count: 1,
    depot_analysis_available: false,
  }
}

function result(scenarioId: string, revision: number, runId: string, facility: ReturnType<typeof facilityAggregate>) {
  const overview = {
    context: { scenario_id: scenarioId, demand_plan_version_id: 'demand-v1', capacity_plan_version_id: 'capacity-v1', horizon_start: horizonStart, horizon_end: horizonEnd, region_id: 'MIDWEST', lane_type: 'LINEHAUL', metric: 'assigned_flow' },
    kpis: { demand_units: 100, assigned_units: 80, unmet_units: 20, total_cost: 500, cost_per_unit: 6.25, on_time_pct: 100, utilization_pct: 40 },
    facilities: [facility],
    lanes: [],
    insights: [],
    summary: `${scenarioId} result`,
    source: runId,
    freshness_at: `${horizonStart}T12:00:00Z`,
    is_partial: false,
  }
  return {
    run_id: runId,
    scenario_id: scenarioId,
    revision,
    generated_at: `${horizonStart}T12:00:00Z`,
    overview,
    baseline_overview: overview,
    kpi_deltas: { demand_units: 0, assigned_units: 0, unmet_units: 0, total_cost: 0, cost_per_unit: 0, on_time_pct: 0, utilization_pct: 0 },
    affected_depot_ids: [],
    charge_details: [],
    exceptions: [],
  }
}

const options = {
  regions: [{ region_id: 'MIDWEST', region_name: 'Midwest' }],
  facilities,
  demand_plans: [], capacity_plans: [], lane_types: ['LINEHAUL'], metrics: [],
  default_demand_plan_version_id: 'demand-v1', default_capacity_plan_version_id: 'capacity-v1',
  default_horizon_start: horizonStart, default_horizon_end: horizonEnd,
  default_region_id: 'MIDWEST', default_lane_type: 'LINEHAUL', default_metric: 'assigned_flow',
  source: 'e2e', freshness_at: `${horizonStart}T12:00:00Z`,
}

async function commonRoute(route: Route) {
  const path = new URL(route.request().url()).pathname
  if (path === '/api/network/options') { await route.fulfill({ json: options }); return true }
  if (path === '/api/network/overview') {
    const empty = result('overview', 1, 'overview', facilityAggregate('Overview', 100, 100)).overview
    await route.fulfill({ json: { ...empty, facilities: [], lanes: [] } })
    return true
  }
  if (path === '/api/network/baseline') { await route.fulfill({ json: { original_revision_id: 'original', active_revision_id: 'original', active_run_id: null, accepted_at: null } }); return true }
  return false
}

test('edits available supply and handling capacity independently', async ({ page }) => {
  let savedAssumptions: Record<string, unknown> | undefined
  let current = scenario('network-controls')
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    if (await commonRoute(route)) return
    const path = new URL(route.request().url()).pathname
    if (path === '/api/network/scenarios/network-controls' && route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      savedAssumptions = body.assumptions
      current = { ...current, revision: current.revision + 1, assumptions: body.assumptions }
      return route.fulfill({ json: current })
    }
    if (path === '/api/network/scenarios/network-controls') return route.fulfill({ json: current })
    if (path === '/api/network/scenarios') return route.fulfill({ json: [current] })
    return route.fulfill({ status: 404, json: { detail: path } })
  })

  await page.goto(`${appUrl}/network/scenarios/network-controls/scenario`)
  await page.getByRole('button', { name: 'Facility supply & handling' }).click()
  await page.getByLabel('Alpha DC available supply percent exact value').fill('35')
  await page.getByLabel('Alpha DC handling capacity percent exact value').fill('140')

  await expect.poll(() => savedAssumptions).toMatchObject({
    facility_supply_retained_pct: { DC_ALPHA: 35 },
    facility_capacity_retained_pct: { DC_ALPHA: 140 },
  })
  await expect(page.getByLabel('Alpha Depot available supply percent exact value')).toBeDisabled()
  await expect(page.getByLabel('Alpha Depot handling capacity percent exact value')).toHaveValue('100')
})

test('uses the selected scenario result, blocks stale latest data, and labels pinned history', async ({ page }) => {
  const alphaCurrent = scenario('network-alpha', 3)
  const betaCurrent = scenario('network-beta', 2)
  const staleAlpha = result('network-alpha', 2, 'alpha-stale', facilityAggregate('Alpha', 42, 88))
  const pinnedAlpha = result('network-alpha', 1, 'alpha-history', facilityAggregate('Alpha', 25, 75))
  const betaLatest = result('network-beta', 2, 'beta-latest', facilityAggregate('Beta', 125, 60))

  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    if (await commonRoute(route)) return
    const path = new URL(route.request().url()).pathname
    if (path === '/api/network/scenarios/network-alpha') return route.fulfill({ json: alphaCurrent })
    if (path === '/api/network/scenarios/network-beta') return route.fulfill({ json: betaCurrent })
    if (path === '/api/network/scenarios/network-alpha/result') return route.fulfill({ json: staleAlpha })
    if (path === '/api/network/scenarios/network-beta/result') return route.fulfill({ json: betaLatest })
    if (path === '/api/network/runs/alpha-history') return route.fulfill({ json: pinnedAlpha })
    if (path === '/api/network/scenarios') return route.fulfill({ json: [alphaCurrent, betaCurrent] })
    return route.fulfill({ status: 404, json: { detail: path } })
  })

  await page.goto(`${appUrl}/network/scenarios/network-alpha/flow`)
  await expect(page.getByText('This result is stale for the selected scenario')).toBeVisible()
  await expect(page.getByLabel('Facility unmet demand details')).toHaveCount(0)

  await page.goto(`${appUrl}/network/scenarios/network-alpha/flow?run=alpha-history`)
  await expect(page.getByText(/Viewing pinned historical run/)).toContainText('alpha-history')
  await expect(page.getByLabel('Facility unmet demand details')).toContainText(
    'Alpha DC, distribution center: no target demand in this view.',
  )

  await page.goto(`${appUrl}/network/scenarios/network-beta/flow`)
  const details = page.getByLabel('Facility unmet demand details')
  await expect(details).toContainText(
    'Beta DC, distribution center: no target demand in this view.',
  )
  await expect(details).not.toContainText('Alpha DC')
  await expect(page.getByText('This result is stale for the selected scenario')).toHaveCount(0)
})

test('location shortage rolls up child demand rather than DC outbound volume', async ({ page }) => {
  const current = scenario('network-rings', 1)
  const data = result('network-rings', 1, 'rings-run', facilityAggregate('Alpha', 100, 100))
  // The parent ships only 20 cases; alternate supply fulfills the child's full 100.
  data.overview.facilities[0].assigned_units = 20
  data.overview.facilities.push({
    ...facilityAggregate('Depot', 100, 100),
    facility_id: 'DPT_ALPHA',
    facility_name: 'Alpha Depot',
    facility_type: 'depot',
    parent_facility_id: 'DC_ALPHA',
    assigned_units: 100,
  })
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    if (await commonRoute(route)) return
    const path = new URL(route.request().url()).pathname
    if (path === '/api/network/scenarios/network-rings') return route.fulfill({ json: current })
    if (path === '/api/network/scenarios/network-rings/result') return route.fulfill({ json: data })
    if (path === '/api/network/scenarios') return route.fulfill({ json: [current] })
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  await page.goto(`${appUrl}/network/scenarios/network-rings/flow`)
  const details = page.getByLabel('Facility unmet demand details')
  await expect(details).toContainText('Alpha DC, distribution center: 0 unmet cases at this target.')
  await expect(details).toContainText('Alpha Depot, depot: 0 unmet cases at this target.')
  await expect(page.getByText('Location fill · unmet demand at target')).toBeVisible()
  await expect(page.getByText('Lane color · utilization of capacity')).toBeVisible()
})
