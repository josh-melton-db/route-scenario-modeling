import type { NetworkLaneAggregate } from '@/api/types'
import { formatCurrency, formatNumber } from '@/lib/format'

export function uniqueLaneEndpoints(
  lanes: NetworkLaneAggregate[],
  idKey: 'origin_endpoint_id' | 'destination_endpoint_id',
  nameKey: 'origin_endpoint_name' | 'destination_endpoint_name',
) {
  const endpoints = new Map<string, { id: string; name: string }>()
  for (const lane of lanes) {
    endpoints.set(lane[idKey], { id: lane[idKey], name: lane[nameKey] })
  }
  return [...endpoints.values()].sort((left, right) => left.name.localeCompare(right.name))
}

export function laneNameFor(lanes: NetworkLaneAggregate[], laneId: string) {
  return lanes.find((lane) => lane.lane_id === laneId)?.lane_name ?? laneId
}

export function signedNumber(value: number) {
  return `${value >= 0 ? '+' : ''}${formatNumber(value)}`
}

export function signedCurrency(value: number, maximumFractionDigits = 0) {
  return `${value >= 0 ? '+' : ''}${formatCurrency(value, maximumFractionDigits)}`
}
