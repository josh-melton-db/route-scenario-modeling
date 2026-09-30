import type { NetworkLaneAggregate } from '@/api/types'

export type SoWhatTone = 'critical' | 'warning' | 'info' | 'good'

export interface LaneSoWhat {
  tone: SoWhatTone
  headline: string
  detail: string
}

const SATURATED_PCT = 95
const TIGHT_PCT = 85
const ON_TIME_TARGET_PCT = 95

/**
 * Turns a lane's own numbers into the consequence a planner cares about, rather
 * than restating the metrics shown beside it.
 *
 * Unmet demand is held at facilities, never on a lane, so endpoint shortfalls are
 * passed in and reported as corridor context. The lane's own service and capacity
 * signals lead, because a shortfall at a connected facility can come from
 * anywhere in the corridor.
 */
export function laneSoWhat({
  lane,
  originUnmetUnits = 0,
  destinationUnmetUnits = 0,
}: {
  lane: NetworkLaneAggregate
  originUnmetUnits?: number
  destinationUnmetUnits?: number
}): LaneSoWhat {
  const destinationUnmet =
    lane.destination_endpoint_type === 'facility' ? destinationUnmetUnits : 0
  const originUnmet = lane.origin_endpoint_type === 'facility' ? originUnmetUnits : 0
  const stranded =
    destinationUnmet > 0
      ? { name: lane.destination_endpoint_name, units: destinationUnmet }
      : { name: lane.origin_endpoint_name, units: originUnmet }

  const headroom = Math.max(0, lane.capacity_units - lane.assigned_units)
  const utilization = formatPercent(lane.utilization_pct)
  const onTime = formatPercent(lane.on_time_pct)
  const committed = lane.assigned_units > 0 || lane.capacity_units > 0
  const saturated = lane.utilization_pct >= SATURATED_PCT
  const late = lane.on_time_pct < ON_TIME_TARGET_PCT
  const exposedCases = Math.round(lane.assigned_units * (1 - lane.on_time_pct / 100))

  if (late && saturated) {
    return {
      tone: 'critical',
      headline: 'Committed past its service target',
      detail:
        `Every case of supplied capacity is committed at an ${onTime} on-time outlook, below the ` +
        `${ON_TIME_TARGET_PCT}% target, so roughly ${formatNumber(exposedCases)} cases a period are ` +
        `exposed to a late delivery with no spare capacity to recover against.`,
    }
  }

  if (late) {
    return {
      tone: 'warning',
      headline: 'Service is below the delivery target',
      detail:
        `${onTime} on-time against a ${ON_TIME_TARGET_PCT}% target at ${utilization} committed, ` +
        `which exposes about ${formatNumber(exposedCases)} cases a period to a late delivery.`,
    }
  }

  if (saturated && stranded.units > 0) {
    return {
      tone: 'warning',
      headline: 'No slack left in this corridor',
      detail:
        `This lane is fully committed at ${utilization}, and ${stranded.name} still shows ` +
        `${formatNumber(stranded.units)} unassigned cases. Relieving capacity anywhere in this ` +
        `corridor is the highest-leverage change available.`,
    }
  }

  if (saturated) {
    return {
      tone: 'warning',
      headline: 'No headroom left on this lane',
      detail:
        `${utilization} of supplied capacity is committed. The next demand increment in this ` +
        `corridor needs added capacity or a reroute rather than more flow.`,
    }
  }

  if (lane.contract_coverage === 'partial') {
    return {
      tone: 'warning',
      headline: 'The cost here is a planning fallback',
      detail:
        `${formatCurrency(lane.total_cost)} is modeled without a published lane rate, so treat it ` +
        `as directional. Committing to this cost needs a governed rate-book entry first.`,
    }
  }

  if (stranded.units > 0) {
    return {
      tone: 'info',
      headline: 'Demand is stranded, but not for lack of lane capacity',
      detail:
        `${stranded.name} still shows ${formatNumber(stranded.units)} unassigned cases while this ` +
        `lane carries ${formatNumber(headroom)} cases of spare supplied capacity, so the gap sits ` +
        `upstream or downstream of this lane.`,
    }
  }

  if (committed && lane.utilization_pct >= TIGHT_PCT) {
    return {
      tone: 'info',
      headline: 'Tight but serviceable',
      detail:
        `${formatNumber(headroom)} cases of supplied capacity remain at ${utilization}. ` +
        `Absorbing a small increment here is realistic; a large one is not.`,
    }
  }

  if (committed) {
    return {
      tone: 'good',
      headline: 'This lane has room to absorb demand',
      detail:
        `${formatNumber(headroom)} cases of supplied capacity are unused at ${utilization}, so ` +
        `shifting flow onto this lane is the low-risk lever in this corridor.`,
    }
  }

  return {
    tone: 'good',
    headline: 'Nothing needs attention on this lane',
    detail: `No flow is assigned here, and nothing on this lane is short of plan targets.`,
  }
}

function formatCurrency(value: number) {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  })
}

function formatNumber(value: number) {
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

function formatPercent(value: number) {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`
}
