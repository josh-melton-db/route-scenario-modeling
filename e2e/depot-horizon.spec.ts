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
  await expect(page.getByLabel('Depot plan dates').getByRole('button')).toHaveCount(28)
  await expect(page.getByText('2/28 solved')).toBeVisible()
  await expect(page.getByText(/Horizon totals include only 2 solved dates/)).toBeVisible()
  await expect(page.getByText(/Thu, Sep 3/)).toBeVisible()
  await expect(page).toHaveURL(/depotPlan=plan-28/)

  await page.getByRole('link', { name: 'Scenarios' }).click()
  await expect(page).toHaveURL(/networkRun=run-28/)
  await expect(page).toHaveURL(/depotPlan=plan-28/)
  await page.getByLabel('New route scenario name').fill('Late shift')
  await page.getByRole('button', { name: 'Create' }).click()
  await expect(page).toHaveURL(/routePlanScenario=named-1/)

  await page.getByLabel('Driver delta').fill('-1')
  await page.getByLabel('Allow overtime').check()
  await page.getByRole('button', { name: 'Optimize selected day' }).click()
  await expect(page.getByText(/Override: queued/)).toBeVisible()
  await expect(page.getByText(/Override: completed/)).toBeVisible({ timeout: 8_000 })
  await expect(page.getByText(/unserved 5/)).toBeVisible()

  await page.getByRole('button', { name: 'Reset selected day to default' }).click()
  await expect(page.getByText(/Override: completed/)).toBeHidden()
  await page.getByRole('link', { name: 'Network' }).click()
  await expect(page).toHaveURL(`${appUrl}/network/scenarios/network-1/flow?run=run-28`)
  expect(legacyRequests).toEqual([])
})

test('uses the parent horizon length instead of assuming 28 dates', async ({ page }) => {
  await page.route('**/api/network/runs/run-10/depots/DPT_NORTH/plans**', (route) => route.fulfill({ json: planSet(10) }))
  await page.route('**/api/depot-plans/plan-10**', (route) => route.fulfill({ json: planSet(10) }))
  await page.goto(`${appUrl}/analyze?networkRun=run-10&depot=DPT_NORTH&date=2026-09-04`)
  await expect(page.getByLabel('Depot plan dates').getByRole('button')).toHaveCount(10)
  await expect(page.getByText('2/10 solved')).toBeVisible()
})
