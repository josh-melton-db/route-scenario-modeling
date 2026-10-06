import type { RateContractSummary } from '@/api/types'

export function localRateContractsForDepot(
  contracts: RateContractSummary[],
  depotId: string,
  regionId?: string | null,
) {
  return contracts.filter((contract) => {
    if (contract.lane_types?.length && contract.lane_types.every((type) => type === 'LINEHAUL')) return false
    const depots = contract.applicable_depot_ids ?? []
    const regions = contract.applicable_region_ids ?? []
    if (depots.length && !depots.includes(depotId)) return false
    if (regions.length && (!regionId || !regions.includes(regionId))) return false
    return true
  })
}
