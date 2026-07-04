import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { RunStatusResponse, ScenarioCreateRequest } from './types'

const terminalStatuses = new Set(['succeeded', 'infeasible', 'failed'])

export const queryKeys = {
  depots: ['depots'] as const,
  days: ['days'] as const,
  scenarioTypes: ['scenario-types'] as const,
  baselineNetwork: (depotId: string, deliveryDay: string) =>
    ['baseline-network', depotId, deliveryDay] as const,
  baselineKpis: (depotId: string, deliveryDay: string) =>
    ['baseline-kpis', depotId, deliveryDay] as const,
  scenario: (scenarioId: string) => ['scenario', scenarioId] as const,
  run: (runId: string, scenarioId?: string | null) => ['run', runId, scenarioId] as const,
  results: (scenarioId: string) => ['scenario-results', scenarioId] as const,
}

export function useDepots() {
  return useQuery({ queryKey: queryKeys.depots, queryFn: api.depots })
}

export function useDays() {
  return useQuery({ queryKey: queryKeys.days, queryFn: api.days })
}

export function useScenarioTypes() {
  return useQuery({ queryKey: queryKeys.scenarioTypes, queryFn: api.scenarioTypes })
}

export function useBaselineNetwork(depotId: string, deliveryDay: string) {
  return useQuery({
    queryKey: queryKeys.baselineNetwork(depotId, deliveryDay),
    queryFn: () => api.baselineNetwork(depotId, deliveryDay),
    enabled: Boolean(depotId && deliveryDay),
  })
}

export function useBaselineKpis(depotId: string, deliveryDay: string) {
  return useQuery({
    queryKey: queryKeys.baselineKpis(depotId, deliveryDay),
    queryFn: () => api.baselineKpis(depotId, deliveryDay),
    enabled: Boolean(depotId && deliveryDay),
  })
}

export function useScenario(scenarioId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.scenario(scenarioId ?? ''),
    queryFn: () => api.scenario(scenarioId ?? ''),
    enabled: Boolean(scenarioId),
  })
}

export function useRunStatus(runId: string | undefined, scenarioId?: string | null) {
  return useQuery({
    queryKey: queryKeys.run(runId ?? '', scenarioId),
    queryFn: () => api.runStatus(runId ?? '', scenarioId),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const data = query.state.data as RunStatusResponse | undefined
      return data && terminalStatuses.has(data.status) ? false : 1500
    },
  })
}

export function useScenarioResults(scenarioId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.results(scenarioId ?? ''),
    queryFn: () => api.scenarioResults(scenarioId ?? ''),
    enabled: Boolean(scenarioId),
  })
}

export function useCreateScenario() {
  return useMutation({
    mutationFn: (payload: ScenarioCreateRequest) => api.createScenario(payload),
  })
}

export function useValidateScenario() {
  return useMutation({
    mutationFn: (scenarioId: string) => api.validateScenario(scenarioId),
  })
}

export function useStartRun() {
  return useMutation({
    mutationFn: (scenarioId: string) => api.runScenario(scenarioId),
  })
}
