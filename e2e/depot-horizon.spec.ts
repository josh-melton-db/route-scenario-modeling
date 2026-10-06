import { expect, test } from '@playwright/test'

const appUrl = process.env.E2E_BASE_URL ?? ''
const depot = { depot_id: 'DPT_NORTH', name: 'North Depot', region: 'North', sales_territory: 'North', location: { lat: 40, lng: -86 } }
const costBreakdown = {
  mileage_cost: 10, labor_cost: 20, overtime_cost: 0, fixed_vehicle_cost: 5,
  sla_penalty_cost: 0, carrier_linehaul_cost: 0, carrier_lane_cost: 0,
  carrier_stop_cost: 0, carrier_minimum_adjustment: 0, fuel_surcharge_cost: 0,
  accessorial_cost: 0, volume_tier_adjustment: 0, commitment_adjustment: 0,
  total_cost: 35,
}
const kpis = {
  route_count: 1, driver_count: 1, vehicle_count: 1, total_miles: 10,
  drive_minutes: 20, service_minutes: 10, total_cases: 100, avg_stops_per_route: 1,
  avg_capacity_utilization_pct: 50, avg_driver_utilization_pct: 40,
  overtime_minutes: 0, missed_windows: 0, late_minutes: 0, total_revenue: 100,
  profit: 65, cost_breakdown: costBreakdown,
}

function dates(count: number) {
  return Array.from({ length: count }, (_, index) => {
    const date = new Date('2026-09-01T12:00:00')
    date.setDate(date.getDate() + index)
    return date.toISOString().slice(0, 10)
  })
}

function result(serviceDate: string, resultId: string, unservedCases = 0) {
  return {
    result_id: resultId, service_date: serviceDate,
    status: unservedCases ? 'infeasible' : 'completed', routes: [], kpis,
    assigned_cases: 100, routed_cases: 100 - unservedCases, unserved_cases: unservedCases,
    diagnostics: unservedCases ? ['Insufficient fixed fleet capacity'] : [],
    matrix_source: 'haversine_circuity', created_at: '2026-09-30T12:00:00Z',
  }
}

function planSet(count: number, routeScenarioId = 'default') {
  const horizonDates = dates(count)
  return {
    plan_set_id: `plan-${count}`, parent_run_id: `run-${count}`, depot,
    horizon_start: horizonDates[0], horizon_end: horizonDates.at(-1),
    route_scenario_id: routeScenarioId,
    scenarios: [
      { route_scenario_id: 'default', scenario_name: 'Stored default', is_default: true },
      ...(routeScenarioId === 'named-1' ? [{ route_scenario_id: 'named-1', scenario_name: 'Late shift', is_default: false }] : []),
    ],
    days: horizonDates.map((serviceDate, index) => ({
      service_date: serviceDate,
      status: index < 2 ? 'completed' : index === 2 ? 'running' : 'queued',
      default_status: index < 2 ? 'completed' : index === 2 ? 'running' : 'queued',
      assigned_cases: 100,
      routed_cases: index < 2 ? 100 : null,
      unserved_cases: index < 2 ? 0 : null,
      total_cost: index < 2 ? 35 : null,
      is_overridden: routeScenarioId === 'named-1' && serviceDate === '2026-09-03',
      selected_result_id: index < 2 ? `default-${serviceDate}` : null,
      error: null,
    })),
    coverage: { total_days: count, solved_days: 2, queued_days: Math.max(0, count - 3), running_days: count > 2 ? 1 : 0, failed_days: 0 },
    kpis, is_partial: count > 2, resource_source: 'synthetic fixed fleet snapshot',
  }
}

test('shows strict road provenance and an actionable failure without an approximate result', async ({ page }) => {
  let fail = false
  const stored = {
    ...result('2026-09-01', 'strict-result'), matrix_source: 'valhalla',
    execution: { mode: 'strict_serving_road', solver: 'model_serving', solver_invoked: true, matrix_source: 'valhalla', coverage_id: 'texas', artifact_version: 'tx-v1', costing: 'truck', resource_source: 'snapshot:dim_fleet_assets', approximate: false, solver_endpoint: 'route-solver-test' },
  }
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/network/runs/run-1/depots/DPT_NORTH/plans' || path === '/api/depot-plans/plan-1') return route.fulfill({ json: planSet(1) })
    if (path === '/api/depot-plans/plan-1/days/2026-09-01') return route.fulfill({ json: {
      plan_set_id: 'plan-1', service_date: '2026-09-01', route_scenario_id: 'default',
      default_status: fail ? 'failed' : 'completed', override_status: null,
      default_result: fail ? null : stored, selected_result: fail ? null : stored,
      error: fail ? 'Road coverage validation failed: point outside coverage texas; configure a broader extract.' : null,
    } })
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  const href = `${appUrl}/analyze?networkRun=run-1&depot=DPT_NORTH&date=2026-09-01`
  await page.goto(href)
  await expect(page.getByLabel('Route execution provenance')).toHaveCount(0)
  await expect(page.getByText('2026-09-01 routes')).toBeVisible()
  fail = true
  await page.reload()
  await expect(page.getByRole('alert')).toContainText('configure a broader extract')
  await expect(page.getByLabel('Route execution provenance')).toHaveCount(0)
})

test('renders the 28-day pinned horizon and completes then resets a non-Tuesday override', async ({ page }) => {
  let named = false
  let optimized = false
  let reset = false
  let completedReads = 0
  const legacyRequests: string[] = []

  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (path.includes('/baseline') || path === '/api/meta/days' || path === '/api/scenarios') {
      legacyRequests.push(path)
      await route.fulfill({ status: 500, json: { detail: 'legacy API must not be called' } })
      return
    }
    if (path === '/api/network/runs/run-28/depots/DPT_NORTH/plans' && request.method() === 'POST') {
      await route.fulfill({ json: planSet(28) })
      return
    }
    if (path === '/api/depot-plans/plan-28' && request.method() === 'GET') {
      await route.fulfill({ json: planSet(28, named ? 'named-1' : 'default') })
      return
    }
    if (path === '/api/depot-plans/plan-28/scenarios' && request.method() === 'POST') {
      named = true
      await route.fulfill({ json: { route_scenario_id: 'named-1', scenario_name: 'Late shift', is_default: false } })
      return
    }
    if (path === '/api/depot-plans/plan-28/days/2026-09-03/optimize' && request.method() === 'POST') {
      optimized = true
      completedReads = 0
      await route.fulfill({ json: dayDetail('queued') })
      return
    }
    if (path === '/api/depot-plans/plan-28/scenarios/named-1/days/2026-09-03' && request.method() === 'DELETE') {
      reset = true
      await route.fulfill({ json: dayDetail(null) })
      return
    }
    if (path.startsWith('/api/depot-plans/plan-28/days/')) {
      const serviceDate = decodeURIComponent(path.split('/').at(-1) ?? '')
      if (serviceDate === '2026-09-03' && optimized && !reset) {
        completedReads += 1
        await route.fulfill({ json: dayDetail(completedReads > 1 ? 'completed' : 'queued') })
      } else {
        await route.fulfill({ json: {
          plan_set_id: 'plan-28', service_date: serviceDate,
          route_scenario_id: named ? 'named-1' : 'default', default_status: 'completed',
          override_status: null, default_result: result(serviceDate, `default-${serviceDate}`),
          selected_result: result(serviceDate, `default-${serviceDate}`), error: null,
        } })
      }
      return
    }
    await route.fulfill({ status: 404, json: { detail: `Unhandled ${request.method()} ${path}` } })
  })

  function dayDetail(overrideStatus: 'queued' | 'completed' | null) {
    const defaultResult = result('2026-09-03', 'default-2026-09-03')
    return {
      plan_set_id: 'plan-28', service_date: '2026-09-03', route_scenario_id: 'named-1',
      default_status: 'completed', override_status: overrideStatus,
      default_result: defaultResult,
      selected_result: overrideStatus === 'completed' ? result('2026-09-03', 'override-1', 5) : defaultResult,
      error: null,
    }
  }

  const parent = encodeURIComponent('/network/scenarios/network-1/flow?run=run-28')
  await page.goto(`${appUrl}/analyze?networkScenario=network-1&networkRun=run-28&depot=DPT_NORTH&date=2026-09-03&networkReturn=${parent}`)
  await page.getByLabel('Depot plan date', { exact: true }).getByRole('button').click()
  await expect(page.getByRole('listbox', { name: 'Depot plan dates' }).getByRole('option')).toHaveCount(28)
  await page.getByLabel('Depot plan date', { exact: true }).getByRole('button').first().click()
  await expect(page.getByText(/Horizon totals include/)).toHaveCount(0)
  await expect(page).toHaveURL(/depotPlan=plan-28/)

  await page.getByRole('link', { name: 'Scenarios' }).click()
  await expect(page).toHaveURL(/networkRun=run-28/)
  await expect(page).toHaveURL(/depotPlan=plan-28/)
  await page.getByLabel('New route scenario name').fill('Late shift')
  await page.getByRole('button', { name: 'Create' }).click()
  await expect(page).toHaveURL(/routePlanScenario=named-1/)

  await expect(page.getByText('2026-09-03 routes')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add deliveries', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Move facility', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Drivers & route limits', exact: true }).click()
  await page.getByLabel('Driver delta').fill('-1')
  await page.getByLabel('Allow overtime').check()
  await page.getByRole('button', { name: 'Run scenario', exact: true }).click()
  await expect(page).toHaveURL(/analyze\?/ )
  await expect(page.getByText('Selected override (infeasible)', { exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText(/Unserved: 5 cases/)).toBeVisible()
  await page.getByRole('link', { name: 'Scenarios' }).click()
  await expect(page.getByLabel('Driver delta')).toHaveValue('-1')

  await page.getByRole('button', { name: 'Reset selected day to default' }).click()
  await expect(page.getByRole('button', { name: 'Reset selected day to default' })).toBeDisabled()
  await page.getByRole('link', { name: 'Network' }).click()
  await expect(page).toHaveURL(`${appUrl}/network/scenarios/network-1/flow?run=run-28`)
  expect(legacyRequests).toEqual([])
})

test('uses the parent horizon length instead of assuming 28 dates', async ({ page }) => {
  await page.route('**/api/network/runs/run-10/depots/DPT_NORTH/plans**', (route) => route.fulfill({ json: planSet(10) }))
  await page.route('**/api/depot-plans/plan-10**', (route) => route.fulfill({ json: planSet(10) }))
  await page.goto(`${appUrl}/analyze?networkRun=run-10&depot=DPT_NORTH&date=2026-09-04`)
  await page.getByLabel('Depot plan date', { exact: true }).getByRole('button').click()
  await expect(page.getByRole('listbox', { name: 'Depot plan dates' }).getByRole('option')).toHaveCount(10)
})

test('restores a stale depot link into an editable scenario without silently running it', async ({ page }) => {
  let scenarioCreated = false
  let optimizeCalls = 0
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/depot-plans/stale-plan')) return route.fulfill({ status: 404, json: { detail: 'Depot plan not found.' } })
    if (path === '/api/network/runs/run-1/depots/DPT_NORTH/plans') return route.fulfill({ json: planSet(1) })
    if (path === '/api/depot-plans/plan-1/scenarios') {
      scenarioCreated = true
      return route.fulfill({ json: { route_scenario_id: 'named-1', scenario_name: 'Operational plan', is_default: false } })
    }
    if (path === '/api/depot-plans/plan-1') return route.fulfill({ json: planSet(1, 'named-1') })
    if (path.endsWith('/optimize')) {
      optimizeCalls++
      return route.fulfill({ json: {} })
    }
    if (path === '/api/depot-plans/plan-1/days/2026-09-01') return route.fulfill({ json: {
      plan_set_id: 'plan-1', service_date: '2026-09-01', route_scenario_id: 'named-1',
      default_status: 'completed', override_status: null,
      default_result: result('2026-09-01', 'saved-default'), selected_result: result('2026-09-01', 'saved-default'),
    } })
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  await page.goto(`${appUrl}/analyze?networkRun=run-1&depot=DPT_NORTH&date=2026-09-01&depotPlan=stale-plan&routePlanScenario=stale-scenario`)
  await expect(page.getByRole('heading', { name: 'This depot plan is no longer available' })).toBeVisible()
  await page.getByRole('button', { name: 'Restore depot workspace' }).click()
  await expect(page).toHaveURL(/scenario\?.*depotPlan=plan-1.*routePlanScenario=named-1/)
  await expect(page.getByRole('heading', { name: 'Scenario changes' })).toBeVisible()
  expect(scenarioCreated).toBe(true)
  expect(optimizeCalls).toBe(0)
})

test('dated scenario selects a delivery before editing its window', async ({ page }) => {
  let submitted: Record<string, unknown> | null = null
  const baseline = {
    ...result('2026-09-01', 'default-day'),
    routes: [{ route_id: 'route-1', route_name: 'Route 1', path: [depot.location, { lat: 40.01, lng: -86.01 }],
      driver_name: 'Driver 1', total_cases: 100, total_miles: 10, drive_minutes: 20, service_minutes: 10, overtime_minutes: 0,
      stops: [{
        stop_id: 'stop-1', customer_id: 'customer-1', customer_name: 'Corner Store',
        location: { lat: 40.01, lng: -86.01 }, sequence: 1, demand_cases: 100, arrival_time: '09:00',
        time_window_start: '08:00', time_window_end: '16:00',
      }] }],
  }
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/depot-plans/plan-28') return route.fulfill({ json: planSet(28, 'named-1') })
    if (path.endsWith('/optimize')) {
      submitted = route.request().postDataJSON()
      return route.fulfill({ json: {} })
    }
    if (path.startsWith('/api/depot-plans/plan-28/days/')) return route.fulfill({ json: {
      plan_set_id: 'plan-28', service_date: '2026-09-01', route_scenario_id: 'named-1',
      default_status: 'completed', override_status: null,
      default_result: baseline, selected_result: baseline, error: null,
    } })
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  await page.goto(`${appUrl}/scenario?networkRun=run-28&depot=DPT_NORTH&depotPlan=plan-28&routePlanScenario=named-1&date=2026-09-01`)
  await expect(page.getByRole('heading', { name: 'Scenario changes' })).toBeVisible()
  await expect(page.getByText('2026-09-01 routes')).toHaveCount(0)
  await expect(page.getByText('Revenue', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Delivery time window', exact: true }).click()
  await expect(page.getByLabel('Delivery time window map')).toBeVisible()
  await expect(page.getByLabel('Delivery 1 opens')).toHaveCount(0)
  await page.getByLabel('Customer name', { exact: true }).selectOption({ label: 'Corner Store' })
  await page.getByLabel('Delivery 1 opens').fill('09:00')
  await page.getByLabel('Delivery 1 closes').fill('13:00')
  await page.getByRole('button', { name: 'Run scenario', exact: true }).click()
  await expect.poll(() => submitted).toMatchObject({
    route_scenario_id: 'named-1',
    changes: [{ kind: 'time_window_change', customer_id: 'customer-1', receiving_window_start: '09:00', receiving_window_end: '13:00' }],
  })
  await expect(page).toHaveURL(/analyze\?/)
  await expect(page.getByText('2026-09-01 routes')).toBeVisible()
})
