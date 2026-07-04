import type {
  BaselineNetwork,
  ComparisonResult,
  CreateScenarioResponse,
  Depot,
  Kpis,
  RunStartResponse,
  RunStatusResponse,
  ScenarioCreateRequest,
  ScenarioDefinition,
  ScenarioTypeSpec,
  ValidationResponse,
} from './types'

async function requestJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  return (await res.json()) as T
}

function qs(params: Record<string, string>): string {
  return new URLSearchParams(params).toString()
}

export const api = {
  depots: () => requestJSON<Depot[]>('/api/meta/depots'),
  days: () => requestJSON<string[]>('/api/meta/days'),
  scenarioTypes: () => requestJSON<ScenarioTypeSpec[]>('/api/meta/scenario-types'),
  baselineNetwork: (depotId: string, deliveryDay: string) =>
    requestJSON<BaselineNetwork>(
      `/api/baseline/network?${qs({ depot_id: depotId, delivery_day: deliveryDay })}`,
    ),
  baselineKpis: (depotId: string, deliveryDay: string) =>
    requestJSON<Kpis>(
      `/api/baseline/kpis?${qs({ depot_id: depotId, delivery_day: deliveryDay })}`,
    ),
  createScenario: (payload: ScenarioCreateRequest) =>
    requestJSON<CreateScenarioResponse>('/api/scenarios', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  scenario: (scenarioId: string) =>
    requestJSON<ScenarioDefinition>(`/api/scenarios/${scenarioId}`),
  validateScenario: (scenarioId: string) =>
    requestJSON<ValidationResponse>(`/api/scenarios/${scenarioId}/validate`, {
      method: 'POST',
    }),
  runScenario: (scenarioId: string) =>
    requestJSON<RunStartResponse>(`/api/scenarios/${scenarioId}/run`, {
      method: 'POST',
    }),
  runStatus: (runId: string, scenarioId?: string | null) =>
    requestJSON<RunStatusResponse>(
      `/api/runs/${runId}${scenarioId ? `?${qs({ scenarioId })}` : ''}`,
    ),
  scenarioResults: (scenarioId: string) =>
    requestJSON<ComparisonResult>(`/api/scenarios/${scenarioId}/results`),
}
