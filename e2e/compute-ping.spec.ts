import { expect, test } from '@playwright/test'

test('settings pings each compute resource only on demand and allows retries', async ({ page }) => {
  const statuses = { sql_warehouse: 'not_started', route_solver: 'not_started' }
  const calls: string[] = []
  let failSolver = true
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/ready') return route.fulfill({ json: { status: 'ready', checks:
      Object.fromEntries(Object.entries(statuses).map(([name, state]) => [name, {
        ready: true, ping_available: true, warmup: { state, configured: true, endpoint: 'demo',
          started_at: null, completed_at: state === 'ready' ? '2026-10-06T09:00:00Z' : null,
          error: state === 'failed' ? 'Resource access denied.' : null },
      }])) } })
    if (path.startsWith('/api/compute/')) {
      calls.push(path)
      const name = path.includes('sql-warehouse') ? 'sql_warehouse' : 'route_solver'
      statuses[name] = name === 'route_solver' && failSolver ? 'failed' : 'ready'
      return route.fulfill({ status: 202, json: { state: 'warming', configured: true, endpoint: 'demo', started_at: null, completed_at: null, error: null } })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto('/setup')
  await expect(page.getByRole('button', { name: 'Ping SQL warehouse', exact: true })).toBeEnabled()
  expect(calls).toEqual([])
  await page.getByRole('button', { name: 'Ping SQL warehouse', exact: true }).click()
  await expect(page.getByText(/Last ping succeeded/)).toHaveCount(1)
  expect(calls).toEqual(['/api/compute/sql-warehouse/ping'])
  await page.getByRole('button', { name: 'Ping Route solver', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Resource access denied')
  failSolver = false
  await page.getByRole('button', { name: 'Ping Route solver', exact: true }).click()
  await expect(page.getByText(/Last ping succeeded/)).toHaveCount(2)
  expect(calls).toHaveLength(3)
})

test('settings disables compute pings in the local demo environment', async ({ page }) => {
  await page.route(/^https?:\/\/[^/]+\/api\//, (route) => {
    const path = new URL(route.request().url()).pathname
    return route.fulfill({ json: path === '/api/ready'
      ? { status: 'ready', checks: { sql_warehouse: { ready: true, ping_available: false }, route_solver: { ready: true, ping_available: false } } }
      : [] })
  })
  await page.goto('/setup')
  await expect(page.getByRole('button', { name: 'Ping SQL warehouse', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Ping Route solver', exact: true })).toBeDisabled()
})
