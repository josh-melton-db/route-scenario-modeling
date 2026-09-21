import type {
  BaselineNetwork,
  ComparisonResult,
  CreateScenarioResponse,
  DeliveryUploadResult,
  Depot,
  Carrier,
  CarrierContract,
  OperatingParameterSet,
  CostParameterSet,
  RateContractDetail,
  RateAuthoringOptions,
  RateContractCreateRequest,
  RateContractSummary,
  RateDraftUpdateRequest,
  RatePublishRequest,
  RateQuote,
  RateQuoteRequest,
  RateValidationResponse,
  RateVersionCreateRequest,
  EditorCommitResponse,
  EditorDeleteRequest,
  EditorEntityType,
  EditorInsertRequest,
  EditorPage,
  EditorPatchRequest,
  EditorPreviewRequest,
  EditorPreviewResponse,
  EditorRow,
  EditorSession,
  EditorValidationResponse,
  Kpis,
  NetworkOptions,
  NetworkOverview,
  NetworkOverviewParams,
  NetworkScenario,
  NetworkScenarioCreateRequest,
  NetworkScenarioResult,
  NetworkScenarioRunResponse,
  NetworkScenarioUpdateRequest,
  RunStartResponse,
  RunStatusResponse,
  ScenarioCreateRequest,
  ScenarioDefinition,
  ScenarioHistoryItem,
  ScenarioTypeSpec,
  ValidationResponse,
} from './types'

async function requestJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  }
  if (!(init?.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  const res = await fetch(path, {
    ...init,
    headers,
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
  networkOptions: () => requestJSON<NetworkOptions>('/api/network/options'),
  networkOverview: (params: NetworkOverviewParams) =>
    requestJSON<NetworkOverview>(`/api/network/overview?${qs({ ...params })}`),
  networkScenarios: () =>
    requestJSON<NetworkScenario[]>('/api/network/scenarios'),
  createNetworkScenario: (payload: NetworkScenarioCreateRequest) =>
    requestJSON<NetworkScenario>('/api/network/scenarios', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  networkScenario: (scenarioId: string) =>
    requestJSON<NetworkScenario>(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}`,
    ),
  updateNetworkScenario: (scenarioId: string, payload: NetworkScenarioUpdateRequest) =>
    requestJSON<NetworkScenario>(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    ),
  validateNetworkScenario: (scenarioId: string) =>
    requestJSON<NetworkScenario>(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}/validate`,
      { method: 'POST' },
    ),
  runNetworkScenario: (scenarioId: string) =>
    requestJSON<NetworkScenarioRunResponse>(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}/run`,
      { method: 'POST' },
    ),
  networkScenarioResult: (scenarioId: string) =>
    requestJSON<NetworkScenarioResult>(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}/result`,
    ),
  deleteNetworkScenario: async (scenarioId: string) => {
    const res = await fetch(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}`,
      { method: 'DELETE' },
    )
    if (!res.ok) {
      const body = await res.text()
      throw new Error(`${res.status} ${res.statusText}: ${body}`)
    }
  },
  depots: () => requestJSON<Depot[]>('/api/meta/depots'),
  days: () => requestJSON<string[]>('/api/meta/days'),
  carriers: () => requestJSON<Carrier[]>('/api/meta/carriers'),
  carrierContracts: () => requestJSON<CarrierContract[]>('/api/meta/carrier-contracts'),
  operatingParameters: () => requestJSON<OperatingParameterSet[]>('/api/meta/operating-parameters'),
  costParameters: () => requestJSON<CostParameterSet[]>('/api/meta/cost-parameters'),
  rateContracts: (serviceDate: string) =>
    requestJSON<RateContractSummary[]>(
      `/api/rates/contracts?${qs({ service_date: serviceDate })}`,
    ),
  rateAuthoringOptions: () =>
    requestJSON<RateAuthoringOptions>('/api/rates/authoring-options'),
  rateContractDetail: (contractId: string, versionId: string) =>
    requestJSON<RateContractDetail>(
      `/api/rates/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}`,
    ),
  createRateContract: (payload: RateContractCreateRequest) =>
    requestJSON<RateContractDetail>('/api/rates/contracts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createRateVersion: (
    contractId: string,
    payload: RateVersionCreateRequest,
  ) =>
    requestJSON<RateContractDetail>(
      `/api/rates/contracts/${encodeURIComponent(contractId)}/versions`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  saveRateDraft: (
    contractId: string,
    versionId: string,
    payload: RateDraftUpdateRequest,
  ) =>
    requestJSON<RateContractDetail>(
      `/api/rates/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}`,
      { method: 'PUT', body: JSON.stringify(payload) },
    ),
  validateRateDraft: (contractId: string, versionId: string) =>
    requestJSON<RateValidationResponse>(
      `/api/rates/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}/validate`,
      { method: 'POST' },
    ),
  publishRateDraft: (
    contractId: string,
    versionId: string,
    payload: RatePublishRequest,
  ) =>
    requestJSON<RateContractDetail>(
      `/api/rates/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}/publish`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  discardRateDraft: async (contractId: string, versionId: string) => {
    const res = await fetch(
      `/api/rates/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}`,
      { method: 'DELETE' },
    )
    if (!res.ok) {
      const body = await res.text()
      throw new Error(`${res.status} ${res.statusText}: ${body}`)
    }
  },
  previewRateQuote: (payload: RateQuoteRequest) =>
    requestJSON<RateQuote>('/api/rates/quote', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  scenarioTypes: () => requestJSON<ScenarioTypeSpec[]>('/api/meta/scenario-types'),
  recentScenarios: (limit = 10) =>
    requestJSON<ScenarioHistoryItem[]>(
      `/api/scenarios?${qs({ limit: String(limit) })}`,
    ),
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
  deleteScenario: async (scenarioId: string) => {
    const res = await fetch(`/api/scenarios/${encodeURIComponent(scenarioId)}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`${res.status} ${res.statusText}: ${text}`)
    }
  },
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
  openEditorSession: () =>
    requestJSON<EditorSession>('/api/data-editor/sessions', {
      method: 'POST',
    }),
  editorSession: (sessionId: string) =>
    requestJSON<EditorSession>(
      `/api/data-editor/sessions/${encodeURIComponent(sessionId)}`,
    ),
  editorRows: (
    sessionId: string,
    entityType: EditorEntityType,
    page: number,
    pageSize: number,
  ) =>
    requestJSON<EditorPage>(
      `/api/data-editor/sessions/${encodeURIComponent(sessionId)}/rows/${entityType}?${qs({
        page: String(page),
        page_size: String(pageSize),
      })}`,
    ),
  insertEditorRow: (
    sessionId: string,
    entityType: EditorEntityType,
    payload: EditorInsertRequest,
  ) =>
    requestJSON<EditorRow>(
      `/api/data-editor/sessions/${encodeURIComponent(sessionId)}/rows/${entityType}`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  patchEditorRow: (
    sessionId: string,
    entityType: EditorEntityType,
    rowId: string,
    payload: EditorPatchRequest,
  ) =>
    requestJSON<EditorRow>(
      `/api/data-editor/sessions/${encodeURIComponent(sessionId)}/rows/${entityType}/${encodeURIComponent(rowId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(payload),
      },
    ),
  deleteEditorRow: (
    sessionId: string,
    entityType: EditorEntityType,
    rowId: string,
    payload: EditorDeleteRequest,
  ) =>
    requestJSON<EditorSession>(
      `/api/data-editor/sessions/${encodeURIComponent(sessionId)}/rows/${entityType}/${encodeURIComponent(rowId)}`,
      {
        method: 'DELETE',
        body: JSON.stringify(payload),
      },
    ),
  validateEditorSession: (sessionId: string) =>
    requestJSON<EditorValidationResponse>(
      `/api/data-editor/sessions/${encodeURIComponent(sessionId)}/validate`,
      { method: 'POST' },
    ),
  previewEditorBaseline: (sessionId: string, payload: EditorPreviewRequest) =>
    requestJSON<EditorPreviewResponse>(
      `/api/data-editor/sessions/${encodeURIComponent(sessionId)}/preview`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  commitEditorSession: (sessionId: string) =>
    requestJSON<EditorCommitResponse>(
      `/api/data-editor/sessions/${encodeURIComponent(sessionId)}/commit`,
      { method: 'POST' },
    ),
  discardEditorSession: (sessionId: string) =>
    requestJSON<EditorSession>(
      `/api/data-editor/sessions/${encodeURIComponent(sessionId)}/discard`,
      { method: 'POST' },
    ),
  uploadDeliveries: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return requestJSON<DeliveryUploadResult>('/api/scenarios/uploads/deliveries', {
      method: 'POST',
      body,
    })
  },
  downloadTemplateUrl: '/api/scenarios/uploads/template',
}
