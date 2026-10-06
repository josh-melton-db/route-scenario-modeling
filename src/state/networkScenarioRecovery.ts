import type { NetworkScenario, NetworkScenarioAssumptions, NetworkScenarioCreateRequest } from '@/api/types'

const storageKey = (scenarioId: string) => `network-scenario-recovery:${scenarioId}`

export function networkScenarioParameters(
  scenario: NetworkScenario,
  assumptions: NetworkScenarioAssumptions = scenario.assumptions,
  name = scenario.scenario_name,
): NetworkScenarioCreateRequest {
  return {
    scenario_name: name,
    baseline_scenario_id: scenario.baseline_scenario_id,
    source_baseline_revision_id: scenario.source_baseline_revision_id,
    demand_plan_version_id: scenario.demand_plan_version_id,
    capacity_plan_version_id: scenario.capacity_plan_version_id,
    horizon_start: scenario.horizon_start,
    horizon_end: scenario.horizon_end,
    region_id: scenario.region_id,
    assumptions,
  }
}

export function rememberNetworkScenario(
  scenario: NetworkScenario,
  assumptions: NetworkScenarioAssumptions = scenario.assumptions,
  name = scenario.scenario_name,
) {
  try {
    sessionStorage.setItem(storageKey(scenario.scenario_id), JSON.stringify(networkScenarioParameters(scenario, assumptions, name)))
  } catch {
    // Browser storage may be disabled; normal server-backed editing still works.
  }
}

export function networkScenarioRecovery(scenarioId: string): NetworkScenarioCreateRequest | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey(scenarioId)) ?? 'null')
    if (!value || ['scenario_name', 'demand_plan_version_id', 'capacity_plan_version_id',
      'horizon_start', 'horizon_end', 'region_id'].some((key) => typeof value[key] !== 'string')
      || !value.assumptions || typeof value.assumptions !== 'object' || Array.isArray(value.assumptions)) return null
    return value
  } catch {
    return null
  }
}
