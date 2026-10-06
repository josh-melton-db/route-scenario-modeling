import { expect, test } from '@playwright/test'

test('depot rate book uses the selected date, local scope, and actual commitment units', async ({ page }) => {
  const version = { version_id: 'v1', version_number: 1, status: 'published', effective_start: '2026-01-01', effective_end: '2026-12-31' }
  const common = { carrier_id: 'carrier', carrier_name: 'Carrier', version, status: 'published', lane_count: 1, accessorial_count: 0, volume_tier_count: 0, committed_quantity: 20, current_utilization: 5, commitment_unit: 'routes', commitment_period: 'week', applicable_depot_ids: [], coverage_status: 'covered', freshness_at: '2026-10-05T12:00:00Z' }
  const contracts = [
    { ...common, contract_id: 'tola', contract_name: 'Texas local service', lane_types: ['LAST_MILE'], applicable_region_ids: ['REGION_TOLA'] },
    { ...common, contract_id: 'west', contract_name: 'West local service', lane_types: ['LAST_MILE'], applicable_region_ids: ['REGION_WEST'] },
    { ...common, contract_id: 'linehaul', contract_name: 'Texas linehaul', lane_types: ['LINEHAUL'], applicable_region_ids: ['REGION_TOLA'] },
    { ...common, contract_id: 'dallas', contract_name: 'Dallas-only local service', lane_types: ['DELIVERY'], applicable_region_ids: ['REGION_TOLA'], applicable_depot_ids: ['DPT_TOLA_DALLAS'] },
  ]
  let requestedDate: string | null = null
  await page.route(/^https?:\/\/[^/]+\/api\//, (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/rates/contracts') {
      requestedDate = url.searchParams.get('service_date')
      return route.fulfill({ json: contracts })
    }
    if (url.pathname === '/api/network/options') return route.fulfill({ json: { facilities: [{ facility_id: 'DPT_TOLA_SAN_ANTONIO', facility_name: 'San Antonio Depot', facility_type: 'depot', region_id: 'REGION_TOLA' }], regions: [] } })
    if (url.pathname === '/api/meta/carriers') return route.fulfill({ json: [] })
    return route.fulfill({ json: [] })
  })
  await page.goto('/rates?depot=DPT_TOLA_SAN_ANTONIO&date=2026-10-05')
  await expect(page.getByRole('heading', { name: 'San Antonio Depot · local rate book' })).toBeVisible()
  await expect(page.getByText('Texas local service', { exact: true })).toBeVisible()
  await expect(page.getByText('West local service', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Texas linehaul', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Dallas-only local service', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('cell', { name: /5 \/ 20 routes/ })).toContainText('week')
  expect(requestedDate).toBe('2026-10-05')
})
