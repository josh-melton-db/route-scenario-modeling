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

test('refresh rates confirms and updates the lock without optimizing', async ({ page }) => {
  let refreshes = 0
  let solves = 0
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/refresh-rates')) {
      refreshes++
      return route.fulfill({ json: {} })
    }
    if (url.pathname.endsWith('/optimize') || url.pathname.endsWith('/solve')) solves++
    if (url.pathname === '/api/depot-plans/plan-1') return route.fulfill({ json: {
      ...planSet(1), rates_locked_at: '2026-10-06T12:00:00Z',
      rate_book_snapshot_hash: refreshes ? 'bbbbbbbb1234' : 'aaaaaaaa1234',
    } })
    if (url.pathname.includes('/days/')) return route.fulfill({ json: {
      default_status: 'completed', default_result: result('2026-09-01', 'default'),
      selected_result: result('2026-09-01', 'default'),
    } })
    return route.fulfill({ status: 404, json: {} })
  })
  await page.goto(`${appUrl}/scenario?networkRun=run-1&depot=DPT_NORTH&depotPlan=plan-1&date=2026-09-01`)
  await expect(page.getByText(/Rates locked:.*aaaaaaaa/)).toBeVisible()
  page.once('dialog', async dialog => { expect(dialog.message()).toContain('Existing results keep their rates'); await dialog.dismiss() })
  await page.getByRole('button', { name: 'Refresh rates', exact: true }).click()
  expect(refreshes).toBe(0)
  page.once('dialog', async dialog => { await dialog.accept() })
  await page.getByRole('button', { name: 'Refresh rates', exact: true }).click()
  await expect(page.getByText(/Rates locked:.*bbbbbbbb/)).toBeVisible()
  expect(refreshes).toBe(1)
  expect(solves).toBe(0)
})

test('contracted overflow defaults off, submits on, and displays rated and unrated deliveries', async ({ page }) => {
  let submitted: Record<string, unknown> | undefined
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/depot-plans/plan-1') return route.fulfill({ json: planSet(1, 'named-1') })
    if (url.pathname.endsWith('/optimize')) {
      submitted = route.request().postDataJSON()
      return route.fulfill({ json: {} })
    }
    if (url.pathname.includes('/days/')) return route.fulfill({ json: {
      default_status: 'completed', override_status: submitted ? 'infeasible' : null,
      default_result: result('2026-09-01', 'default'),
      selected_result: submitted ? {
        ...result('2026-09-01', 'overflow', 10), routed_cases: 80,
        contracted_deliveries: 1, contracted_cases: 10, fleet_cost: 35, contracted_cost: 100,
        contracted_revenue: 62.5,
        kpis: { ...kpis, total_revenue: 162.5, profit: 27.5, cost_breakdown: { ...costBreakdown, total_cost: 135 } },
        unserved_orders: [{ customer_id: 'no-rate', demand_cases: 10, reason: 'no_contract_rate' }],
      } : result('2026-09-01', 'default'),
    } })
    return route.fulfill({ status: 404, json: { detail: url.pathname } })
  })
  await page.goto(`${appUrl}/scenario?networkRun=run-1&depot=DPT_NORTH&depotPlan=plan-1&routePlanScenario=named-1&date=2026-09-01`)
  await expect(page.getByLabel('Allow contracted overflow', { exact: true })).not.toBeChecked()
  await page.getByLabel('Allow contracted overflow', { exact: true }).check()
  await page.getByRole('button', { name: 'Run scenario', exact: true }).click()
  await expect.poll(() => submitted).toMatchObject({ allow_contracted_overflow: true })
  await expect(page.getByText('Contracted: 1 deliveries · 10 cases')).toBeVisible()
  await expect(page.getByText('Fleet cost: $35.00 · Contracted cost: $100.00 · Contracted revenue: $62.50 · Total cost: $135.00')).toBeVisible()
  await expect(page.getByText('no-rate · 10 cases · No contract rate')).toBeVisible()
})

for (const mode of ['off', 'enabled-unpriced', 'contracted'] as const) {
  test(`overflow cost and revenue lines respect saved result mode: ${mode}`, async ({ page }) => {
    const contracted = mode === 'contracted'
    const stored = {
      ...result('2026-09-01', 'stored', contracted ? 10 : 0),
      routed_cases: contracted ? 70 : 100,
      contracted_cases: contracted ? 20 : 0,
      contracted_deliveries: contracted ? 2 : 0,
      contracted_revenue: contracted ? 125 : 0,
      contracted_cost: contracted ? 20 : 0,
      kpis: contracted ? { ...kpis, total_revenue: 225, profit: 170, cost_breakdown: { ...costBreakdown, total_cost: 55 } } : kpis,
      execution: mode === 'enabled-unpriced' ? { allow_contracted_overflow: true } : {},
    }
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname
      if (path === '/api/depot-plans/plan-1') {
        const plan = planSet(1)
        return route.fulfill({ json: { ...plan, days: [{ ...plan.days[0], ...stored }] } })
      }
      if (path.includes('/days/')) return route.fulfill({ json: {
        default_status: 'completed', default_result: stored, selected_result: stored,
      } })
      return route.fulfill({ status: 404, json: { detail: path } })
    })
    await page.goto(`${appUrl}/analyze?networkRun=run-1&depot=DPT_NORTH&depotPlan=plan-1&date=2026-09-01`)
    await expect(page.getByText('2026-09-01 routes')).toBeVisible()
    await expect(page.getByText(/^Fleet cost:/)).toHaveCount(mode === 'off' ? 0 : 1)
    await expect(page.getByText(/^Contracted:/)).toHaveCount(mode === 'off' ? 0 : 1)
    await expect(page.getByText(/Contracted revenue:/)).toHaveCount(mode === 'off' ? 0 : 1)
    if (mode === 'enabled-unpriced') await expect(page.getByText(/Contracted revenue: \$0.00/)).toBeVisible()
    if (contracted) {
      await expect(page.getByText(/Contracted revenue: \$125.00/)).toBeVisible()
      await expect(page.getByText('Revenue', { exact: true }).locator('..')).toContainText('$225')
      await expect(page.getByText('Profit', { exact: true }).locator('..')).toContainText('$170')
      await page.getByLabel('Depot plan date', { exact: true }).getByRole('button').click()
      await expect(page.getByText('90/100 cases · 20 contracted')).toBeVisible()
    }
  })
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
  await page.getByRole('button', { name: '+ New scenario', exact: true }).click()
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
  await expect(page.getByLabel('right comparison scenario')).toHaveValue('named-1')
  await expect(page.getByText(/Unserved: 5 cases/)).toBeVisible()
  await expect(page.getByRole('link', { name: 'Reallocate supply' })).toHaveCount(0)
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

test('opens today in Indianapolis and reuses its saved default without a solve request', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-09-04T14:00:00Z') })
  const writes: string[] = []
  const reads: string[] = []
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push(path)
    if (path === '/api/depot-plans/plan-28') return route.fulfill({ json: planSet(28) })
    if (path.startsWith('/api/depot-plans/plan-28/days/')) {
      const serviceDate = path.split('/').at(-1)!
      reads.push(serviceDate)
      return route.fulfill({ json: {
        plan_set_id: 'plan-28', service_date: serviceDate, route_scenario_id: 'default',
        default_status: 'completed', override_status: null,
        default_result: result(serviceDate, 'saved-today'), selected_result: result(serviceDate, 'saved-today'),
        error: null,
      } })
    }
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  await page.goto(`${appUrl}/analyze?networkRun=run-28&depot=DPT_NORTH&depotPlan=plan-28`)
  await expect(page).toHaveURL(/date=2026-09-04/)
  await expect(page.getByText('2026-09-04 routes')).toBeVisible()
  expect(reads).toContain('2026-09-04')
  expect(writes).toEqual([])
})

test('selects independent comparisons and hides stale results while rerunning', async ({ page }) => {
  let pending = true
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/depot-plans/plan-1') return route.fulfill({ json: planSet(1, 'named-1') })
    if (url.pathname.includes('/days/')) {
      const named = url.searchParams.get('route_scenario_id') === 'named-1'
      return route.fulfill({ json: {
        default_status: 'completed', override_status: named ? pending ? 'running' : 'infeasible' : null,
        default_result: result('2026-09-01', 'default'),
        selected_result: named ? { ...result('2026-09-01', 'old', 82), unserved_orders: [{ customer_id: 'c1', customer_name: 'River Market', demand_cases: 82, reason: 'time_window_infeasible' }] } : result('2026-09-01', 'default'),
      } })
    }
    return route.fulfill({ status: 404, json: { detail: url.pathname } })
  })
  await page.goto(`${appUrl}/analyze?networkRun=run-1&depot=DPT_NORTH&depotPlan=plan-1&date=2026-09-01&routePlanScenario=named-1`)
  await expect(page.getByLabel('left comparison scenario')).toHaveValue('default')
  await expect(page.getByText('Optimizing…', { exact: true })).toBeVisible()
  await expect(page.getByText('Unserved: 82 cases')).toHaveCount(0)
  pending = false
  await expect(page.getByText('River Market · 82 cases · Delivery time window cannot be met')).toBeVisible()
  await page.getByLabel('right comparison scenario').selectOption('none')
  await expect(page.getByText('Unserved: 82 cases')).toHaveCount(0)
  await expect(page.getByText('2026-09-01 routes')).toHaveCount(1)
  await page.getByLabel('left comparison scenario').selectOption('named-1')
  await expect(page.getByText('Unserved: 82 cases')).toBeVisible()
})

test('uploads quantities and uses checked road coordinates in the submitted scenario', async ({ page }) => {
  let submitted: Record<string, unknown> | null = null
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/depot-plans/plan-1') return route.fulfill({ json: planSet(1, 'named-1') })
    if (path.endsWith('/delivery-access')) return route.fulfill({ json: { reachable: true, road_access_lat: 40.002, road_access_lng: -86.002, road_snap_distance_miles: .05 } })
    if (path.endsWith('/optimize')) { submitted = route.request().postDataJSON(); return route.fulfill({ json: { default_status: 'completed', override_status: 'queued', default_result: result('2026-09-01', 'default'), selected_result: result('2026-09-01', 'default') } }) }
    if (path.includes('/days/')) return route.fulfill({ json: { default_status: 'completed', override_status: null, default_result: result('2026-09-01', 'default'), selected_result: result('2026-09-01', 'default') } })
    return route.fulfill({ status: 404, json: { detail: path } })
  })
  await page.goto(`${appUrl}/scenario?networkRun=run-1&depot=DPT_NORTH&depotPlan=plan-1&date=2026-09-01&routePlanScenario=named-1`)
  await page.getByRole('button', { name: 'Add deliveries', exact: true }).click()
  await page.getByLabel('Upload delivery CSV').setInputFiles({ name: 'deliveries.csv', mimeType: 'text/csv', buffer: Buffer.from('lat,lng,demand_cases,customer_name\n40.001,-86.001,125,"River, Market"') })
  await expect(page.getByText('1 deliveries checked for truck-road access; 1 snapped to the road.')).toBeVisible()
  await page.getByRole('button', { name: 'Run scenario', exact: true }).click()
  await expect.poll(() => submitted).toMatchObject({ changes: [{ kind: 'add_deliveries', deliveries: [{ lat: 40.002, lng: -86.002, demand_cases: 125, customer_name: 'River, Market' }] }] })
})

test('inputs display the selected depot scenario rather than global editor data', async ({ page }) => {
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/depot-plans/plan-1') return route.fulfill({ json: planSet(1, 'named-1') })
    if (url.pathname.endsWith('/inputs')) return route.fulfill({ json: {
      depot, parent_run_id: 'run-1', service_date: '2026-09-01',
      deliveries: [{ customer_id: 'c1', customer_name: 'River Market', receiving_window_start: '09:30', receiving_window_end: '11:00' }],
      orders: [{ customer_id: 'c1', demand_cases: 125 }], fleet: [{ vehicle_id: 'EXTRA-DRIVER', capacity_cases: 900 }],
      cost_parameters: { cost_per_mile: 2.5 }, cost_source: 'frozen depot costs', override_status: 'completed',
    } })
    return route.fulfill({ status: 404, json: { detail: 'No global editor requests allowed' } })
  })
  await page.goto(`${appUrl}/data-editor?networkRun=run-1&depot=DPT_NORTH&depotPlan=plan-1&date=2026-09-01&routePlanScenario=named-1`)
  await expect(page.getByText('River Market', { exact: true })).toBeVisible()
  await expect(page.getByText('125', { exact: true })).toBeVisible()
  await expect(page.getByText('EXTRA-DRIVER', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Inputs scenario')).toHaveValue('named-1')
})
