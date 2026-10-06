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
  DepotPlanDayDetail,
  DepotPlanOverrideRequest,
  DepotPlanRouteScenario,
  DepotPlanSet,
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
  NetworkBaselineState,
  NetworkBaselineProposal,
  NetworkDemandChange,
  NetworkReleaseRequest,
  NetworkReleaseTarget,
  NetworkOverview,
  NetworkOverviewParams,
  NetworkScenario,
  NetworkScenarioCreateRequest,
  NetworkScenarioResult,
  NetworkChargeAuditPage,
  NetworkScenarioRunResponse,
  NetworkRunRecord,
  NetworkScenarioUpdateRequest,
  RunStartResponse,
  RunStatusResponse,
  ScenarioCreateRequest,
  ScenarioDefinition,
  ScenarioHistoryItem,
  ScenarioTypeSpec,
  ValidationResponse,
  ReadinessSnapshot,
  SolverWarmupStatus,
  DemoResetResponse,
} from './types'

export interface ApiErrorPayload {
  code?: string
  message?: string
  request_id?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId?: string

  constructor(
    message: string,
    status: number,
    code: string,
    requestId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

interface RequestOptions extends RequestInit {
  timeoutMs?: number
}

function requestSignal(signal: AbortSignal | null | undefined, timeoutMs: number) {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(new DOMException('Request timed out', 'TimeoutError')), timeoutMs)
  const abort = () => controller.abort(signal?.reason)
  signal?.addEventListener('abort', abort, { once: true })
  return {
    signal: controller.signal,
    cleanup: () => {
      window.clearTimeout(timeout)
      signal?.removeEventListener('abort', abort)
    },
  }
}

async function apiError(res: Response): Promise<ApiError> {
  let payload: { error?: ApiErrorPayload; detail?: string } = {}
  try {
    payload = await res.json() as typeof payload
  } catch {
    // An intermediary can return HTML; do not expose it in the application.
  }
  const requestId = payload.error?.request_id ?? res.headers.get('x-request-id') ?? undefined
  const message = payload.error?.message ?? payload.detail ?? `Request failed (${res.status}).`
  const error = new ApiError(message, res.status, payload.error?.code ?? 'request_failed', requestId)
  if (res.status === 401 || res.status === 403) {
    window.dispatchEvent(new CustomEvent('app:session-expired', { detail: error }))
  }
  return error
}

export async function requestJSON<T>(path: string, init?: RequestOptions): Promise<T> {
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  }
  if (!(init?.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  const { signal, cleanup } = requestSignal(init?.signal, init?.timeoutMs ?? 30_000)
  try {
    const res = await fetch(path, { ...init, headers, signal })
    if (!res.ok) throw await apiError(res)
    return (await res.json()) as T
  } catch (error) {
    if (signal.aborted && !(error instanceof ApiError)) {
      throw new ApiError('The request timed out or was cancelled.', 0, 'request_cancelled')
    }
    throw error
  } finally {
    cleanup()
  }
}

async function requestVoid(path: string, init: RequestOptions): Promise<void> {
  const { signal, cleanup } = requestSignal(init.signal, init.timeoutMs ?? 30_000)
  try {
    const res = await fetch(path, { ...init, signal })
    if (!res.ok) throw await apiError(res)
  } catch (error) {
    if (signal.aborted && !(error instanceof ApiError)) {
      throw new ApiError('The request timed out or was cancelled.', 0, 'request_cancelled')
    }
    throw error
  } finally {
    cleanup()
  }
}

function qs(params: Record<string, string>): string {
  return new URLSearchParams(params).toString()
}

export const api = {
  pingCompute: (resource: 'sql-warehouse' | 'route-solver') => requestJSON<SolverWarmupStatus>(
    `/api/compute/${resource}/ping`, { method: 'POST' },
  ),
  readiness: async () => {
    const res = await fetch('/api/ready', { headers: { Accept: 'application/json' } })
    const payload = (await res.json()) as ReadinessSnapshot
    if (res.status !== 200 && res.status !== 503) {
      throw new ApiError('The readiness check failed.', res.status, 'readiness_failed')
    }
    return payload
  },
  networkBaseline: () => requestJSON<NetworkBaselineState>('/api/network/baseline'),
  networkBaselinePlanRun: (params: NetworkOverviewParams) => requestJSON<NetworkScenarioResult>(
    `/api/network/baseline/plan-run?${qs({ ...params })}`,
  ),
  proposeNetworkBaseline: (runId: string) => requestJSON<NetworkBaselineProposal>(
    '/api/network/baseline/proposals', { method: 'POST', body: JSON.stringify({ run_id: runId }) },
  ),
  acceptNetworkBaseline: (proposalId: string) => requestJSON<NetworkBaselineState>(
    `/api/network/baseline/proposals/${encodeURIComponent(proposalId)}/accept`, { method: 'POST' },
  ),
  resetNetworkBaselineStatus: () => requestJSON<DemoResetResponse>('/api/network/baseline/reset/status'),
  resetNetworkBaseline: async () => {
    let response = await requestJSON<DemoResetResponse>(
      '/api/network/baseline/reset', { method: 'POST' },
    )
    const deadline = Date.now() + 15 * 60_000
    while (response.reset.state === 'seeding_lakebase' || response.reset.state === 'bootstrapping' || response.reset.state === 'resetting') {
      if (Date.now() >= deadline) throw new Error('Demo reset is still bootstrapping. Check Setup for status.')
      await new Promise((resolve) => window.setTimeout(resolve, 2_000))
      response = await requestJSON<DemoResetResponse>('/api/network/baseline/reset/status')
    }
    if (response.reset.state === 'failed') {
      throw new Error(response.reset.error ?? 'Demo reset failed.')
    }
    return response
  },
  networkDemandChanges: (runId: string) => requestJSON<NetworkDemandChange[]>(
    `/api/network/runs/${encodeURIComponent(runId)}/demand-changes`,
  ),
  networkReleaseTargets: (runId: string, depotId: string, serviceDate: string) => requestJSON<NetworkReleaseTarget[]>(
    `/api/network/runs/${encodeURIComponent(runId)}/depots/${encodeURIComponent(depotId)}/release-targets?${qs({ service_date: serviceDate })}`,
  ),
  releaseNetworkDemand: (runId: string, payload: NetworkReleaseRequest) => requestJSON<NetworkDemandChange>(
    `/api/network/runs/${encodeURIComponent(runId)}/demand-changes`,
    { method: 'POST', body: JSON.stringify(payload) },
  ),
  reassignNetworkDemand: async (runId: string) => {
    let record = await requestJSON<NetworkRunRecord>(
      `/api/network/runs/${encodeURIComponent(runId)}/reassign`, { method: 'POST' },
    )
    const deadline = Date.now() + 120_000
    while (record.status === 'queued' || record.status === 'running' || record.status === 'completion_pending') {
      if (Date.now() >= deadline) throw new Error('Network reassignment is still processing. Refresh to check its status.')
      await new Promise((resolve) => window.setTimeout(resolve, 750))
      record = await requestJSON<NetworkRunRecord>(record.status_url)
    }
    if (record.status !== 'succeeded') {
      throw new Error(record.error_message ?? `Network reassignment ended with status ${record.status}.`)
    }
    const [scenario, result] = await Promise.all([
      requestJSON<NetworkScenario>(`/api/network/scenarios/${encodeURIComponent(record.scenario_id)}`),
      requestJSON<NetworkScenarioResult>(`/api/network/runs/${encodeURIComponent(record.run_id)}`),
    ])
    return { scenario, result } satisfies NetworkScenarioRunResponse
  },
  networkOptions: () => requestJSON<NetworkOptions>('/api/network/options'),
  networkOverview: (params: NetworkOverviewParams, signal?: AbortSignal) =>
    requestJSON<NetworkOverview>(`/api/network/overview?${qs({ ...params })}`, { signal }),
  networkScenarios: () =>
    requestJSON<NetworkScenario[]>('/api/network/scenarios'),
  createNetworkScenario: (payload: NetworkScenarioCreateRequest) =>
    requestJSON<NetworkScenario>('/api/network/scenarios', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  networkScenario: (scenarioId: string, signal?: AbortSignal) =>
    requestJSON<NetworkScenario>(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}`,
      { signal },
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
  runNetworkScenario: async (scenarioId: string, expectedRevision: number) => {
    const launched = await requestJSON<NetworkRunRecord>(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}/run`,
      { method: 'POST', body: JSON.stringify({ expected_revision: expectedRevision }) },
    )
    let record = launched
    const deadline = Date.now() + 120_000
    while (record.status === 'queued' || record.status === 'running' || record.status === 'completion_pending') {
      if (Date.now() >= deadline) throw new Error('Network run is still processing. Refresh to check its status.')
      await new Promise((resolve) => window.setTimeout(resolve, 750))
      record = await requestJSON<NetworkRunRecord>(record.status_url)
    }
    if (record.status !== 'succeeded') {
      throw new Error(record.error_message ?? `Network run ended with status ${record.status}.`)
    }
    const [scenario, result] = await Promise.all([
      requestJSON<NetworkScenario>(`/api/network/scenarios/${encodeURIComponent(scenarioId)}`),
      requestJSON<NetworkScenarioResult>(`/api/network/runs/${encodeURIComponent(record.run_id)}`),
    ])
    return { scenario, result } satisfies NetworkScenarioRunResponse
  },
  networkScenarioResult: (scenarioId: string, signal?: AbortSignal) =>
    requestJSON<NetworkScenarioResult>(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}/result`,
      { signal },
    ),
  networkRunResult: (runId: string, signal?: AbortSignal) =>
    requestJSON<NetworkScenarioResult>(
      `/api/network/runs/${encodeURIComponent(runId)}`,
      { signal },
    ),
  networkRunCharges: (
    runId: string,
    params: { side: 'scenario' | 'baseline'; offset: number; limit: number; query?: string },
    signal?: AbortSignal,
  ) => requestJSON<NetworkChargeAuditPage>(
    `/api/network/runs/${encodeURIComponent(runId)}/charges?${qs({
      side: params.side,
      offset: String(params.offset),
      limit: String(params.limit),
      query: params.query ?? '',
    })}`, { signal },
  ),
  createDepotPlan: (runId: string, depotId: string, priorityDate?: string) =>
    requestJSON<DepotPlanSet>(
      `/api/network/runs/${encodeURIComponent(runId)}/depots/${encodeURIComponent(depotId)}/plans${priorityDate ? `?${qs({ priority_date: priorityDate })}` : ''}`,
      { method: 'POST' },
    ),
  depotPlan: (planSetId: string, routeScenarioId = 'default', signal?: AbortSignal) =>
    requestJSON<DepotPlanSet>(
      `/api/depot-plans/${encodeURIComponent(planSetId)}?${qs({ route_scenario_id: routeScenarioId })}`,
      { signal },
    ),
  depotPlanDay: (planSetId: string, serviceDate: string, routeScenarioId = 'default', signal?: AbortSignal) =>
    requestJSON<DepotPlanDayDetail>(
      `/api/depot-plans/${encodeURIComponent(planSetId)}/days/${encodeURIComponent(serviceDate)}?${qs({ route_scenario_id: routeScenarioId })}`,
      { signal },
    ),
  solveDepotPlanDay: (planSetId: string, serviceDate: string) =>
    requestJSON<DepotPlanDayDetail>(
      `/api/depot-plans/${encodeURIComponent(planSetId)}/days/${encodeURIComponent(serviceDate)}/solve`,
      { method: 'POST' },
    ),
  createDepotPlanScenario: (planSetId: string, scenarioName: string) =>
    requestJSON<DepotPlanRouteScenario>(
      `/api/depot-plans/${encodeURIComponent(planSetId)}/scenarios`,
      { method: 'POST', body: JSON.stringify({ scenario_name: scenarioName }) },
    ),
  optimizeDepotPlanDay: (
    planSetId: string,
    serviceDate: string,
    payload: DepotPlanOverrideRequest,
  ) => requestJSON<DepotPlanDayDetail>(
    `/api/depot-plans/${encodeURIComponent(planSetId)}/days/${encodeURIComponent(serviceDate)}/optimize`,
    { method: 'POST', body: JSON.stringify(payload) },
  ),
  resetDepotPlanDay: (planSetId: string, routeScenarioId: string, serviceDate: string) =>
    requestJSON<DepotPlanDayDetail>(
      `/api/depot-plans/${encodeURIComponent(planSetId)}/scenarios/${encodeURIComponent(routeScenarioId)}/days/${encodeURIComponent(serviceDate)}`,
      { method: 'DELETE' },
    ),
  deleteNetworkScenario: (scenarioId: string) =>
    requestVoid(
      `/api/network/scenarios/${encodeURIComponent(scenarioId)}`,
      { method: 'DELETE' },
    ),
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
  discardRateDraft: (contractId: string, versionId: string) =>
    requestVoid(
      `/api/rates/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}`,
      { method: 'DELETE' },
    ),
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
  deleteScenario: (scenarioId: string) =>
    requestVoid(`/api/scenarios/${encodeURIComponent(scenarioId)}`, { method: 'DELETE' }),
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
