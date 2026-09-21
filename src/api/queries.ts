import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  CreateScenarioResponse,
  EditorDeleteRequest,
  EditorEntityType,
  EditorInsertRequest,
  EditorPatchRequest,
  EditorPreviewRequest,
  NetworkOverviewParams,
  RateContractCreateRequest,
  RateDraftUpdateRequest,
  RatePublishRequest,
  RateQuoteRequest,
  RateVersionCreateRequest,
  RunStartResponse,
  RunStatusResponse,
  ScenarioCreateRequest,
  ScenarioDefinition,
  ValidationResponse,
} from './types'

const terminalStatuses = new Set(['succeeded', 'infeasible', 'failed'])

export const queryKeys = {
  networkOptions: ['network-options'] as const,
  networkOverview: (params: NetworkOverviewParams) =>
    ['network-overview', params] as const,
  depots: ['depots'] as const,
  days: ['days'] as const,
  carriers: ['carriers'] as const,
  carrierContracts: ['carrier-contracts'] as const,
  operatingParameters: ['operating-parameters'] as const,
  costParameters: ['cost-parameters'] as const,
  rateAuthoringOptions: ['rate-authoring-options'] as const,
  rateContracts: (serviceDate: string) => ['rate-contracts', serviceDate] as const,
  rateContractDetail: (contractId: string, versionId: string) =>
    ['rate-contract-detail', contractId, versionId] as const,
  scenarioTypes: ['scenario-types'] as const,
  recentScenarios: (limit: number) => ['recent-scenarios', limit] as const,
  baselineNetwork: (depotId: string, deliveryDay: string) =>
    ['baseline-network', depotId, deliveryDay] as const,
  baselineKpis: (depotId: string, deliveryDay: string) =>
    ['baseline-kpis', depotId, deliveryDay] as const,
  scenario: (scenarioId: string) => ['scenario', scenarioId] as const,
  run: (runId: string, scenarioId?: string | null) => ['run', runId, scenarioId] as const,
  results: (scenarioId: string) => ['scenario-results', scenarioId] as const,
  editorSession: (sessionId: string) => ['editor-session', sessionId] as const,
  editorRows: (
    sessionId: string,
    entityType: EditorEntityType,
    page: number,
    pageSize: number,
  ) => ['editor-rows', sessionId, entityType, page, pageSize] as const,
}

export function useNetworkOptions() {
  return useQuery({
    queryKey: queryKeys.networkOptions,
    queryFn: api.networkOptions,
    staleTime: 5 * 60 * 1000,
  })
}

export function useNetworkOverview(params: NetworkOverviewParams | null) {
  return useQuery({
    queryKey: params ? queryKeys.networkOverview(params) : ['network-overview', 'disabled'],
    queryFn: () => api.networkOverview(params as NetworkOverviewParams),
    enabled: Boolean(params),
  })
}

export function useDepots() {
  return useQuery({ queryKey: queryKeys.depots, queryFn: api.depots })
}

export function useDays() {
  return useQuery({ queryKey: queryKeys.days, queryFn: api.days })
}

export function useCarriers() {
  return useQuery({ queryKey: queryKeys.carriers, queryFn: api.carriers })
}

export function useCarrierContracts() {
  return useQuery({ queryKey: queryKeys.carrierContracts, queryFn: api.carrierContracts })
}

export function useOperatingParameters() {
  return useQuery({ queryKey: queryKeys.operatingParameters, queryFn: api.operatingParameters })
}

export function useCostParameters() {
  return useQuery({ queryKey: queryKeys.costParameters, queryFn: api.costParameters })
}

export function useRateContracts(serviceDate: string) {
  return useQuery({
    queryKey: queryKeys.rateContracts(serviceDate),
    queryFn: () => api.rateContracts(serviceDate),
    enabled: Boolean(serviceDate),
  })
}

export function useRateAuthoringOptions() {
  return useQuery({
    queryKey: queryKeys.rateAuthoringOptions,
    queryFn: api.rateAuthoringOptions,
  })
}

export function useRateContractDetail(contractId: string, versionId: string) {
  return useQuery({
    queryKey: queryKeys.rateContractDetail(contractId, versionId),
    queryFn: () => api.rateContractDetail(contractId, versionId),
    enabled: Boolean(contractId && versionId),
  })
}

export function usePreviewRateQuote() {
  return useMutation({
    mutationFn: (payload: RateQuoteRequest) => api.previewRateQuote(payload),
  })
}

function useInvalidateRates() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['rate-contracts'] })
}

export function useCreateRateContract() {
  const invalidate = useInvalidateRates()
  return useMutation({
    mutationFn: (payload: RateContractCreateRequest) => api.createRateContract(payload),
    onSuccess: invalidate,
  })
}

export function useCreateRateVersion() {
  const invalidate = useInvalidateRates()
  return useMutation({
    mutationFn: ({ contractId, payload }: { contractId: string; payload: RateVersionCreateRequest }) =>
      api.createRateVersion(contractId, payload),
    onSuccess: invalidate,
  })
}

export function useSaveRateDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ contractId, versionId, payload }: { contractId: string; versionId: string; payload: RateDraftUpdateRequest }) =>
      api.saveRateDraft(contractId, versionId, payload),
    onSuccess: (detail) => {
      queryClient.setQueryData(
        queryKeys.rateContractDetail(detail.contract_id, detail.version.version_id),
        detail,
      )
      void queryClient.invalidateQueries({ queryKey: ['rate-contracts'] })
    },
  })
}

export function useValidateRateDraft() {
  return useMutation({
    mutationFn: ({ contractId, versionId }: { contractId: string; versionId: string }) =>
      api.validateRateDraft(contractId, versionId),
  })
}

export function usePublishRateDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ contractId, versionId, payload }: { contractId: string; versionId: string; payload: RatePublishRequest }) =>
      api.publishRateDraft(contractId, versionId, payload),
    onSuccess: (detail) => {
      queryClient.setQueryData(
        queryKeys.rateContractDetail(detail.contract_id, detail.version.version_id),
        detail,
      )
      void queryClient.invalidateQueries({ queryKey: ['rate-contracts'] })
    },
  })
}

export function useDiscardRateDraft() {
  const invalidate = useInvalidateRates()
  return useMutation({
    mutationFn: ({ contractId, versionId }: { contractId: string; versionId: string }) =>
      api.discardRateDraft(contractId, versionId),
    onSuccess: invalidate,
  })
}

export function useScenarioTypes() {
  return useQuery({ queryKey: queryKeys.scenarioTypes, queryFn: api.scenarioTypes })
}

export function useRecentScenarios(limit = 10) {
  return useQuery({
    queryKey: queryKeys.recentScenarios(limit),
    queryFn: () => api.recentScenarios(limit),
  })
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

export function useEditorSession(sessionId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.editorSession(sessionId ?? ''),
    queryFn: () => api.editorSession(sessionId ?? ''),
    enabled: Boolean(sessionId),
  })
}

export function useEditorRows(
  sessionId: string | undefined,
  entityType: EditorEntityType,
  page: number,
  pageSize: number,
) {
  return useQuery({
    queryKey: queryKeys.editorRows(sessionId ?? '', entityType, page, pageSize),
    queryFn: () => api.editorRows(sessionId ?? '', entityType, page, pageSize),
    enabled: Boolean(sessionId),
  })
}

export function useCreateScenario() {
  return useMutation({
    mutationFn: (payload: ScenarioCreateRequest) => api.createScenario(payload),
  })
}

export interface ScenarioRunStart {
  scenario: ScenarioDefinition
  run?: RunStartResponse
  validation?: ValidationResponse
}

function runReturnedWithScenario(
  created: CreateScenarioResponse,
): RunStartResponse | undefined {
  if (created.run) return created.run
  if (!created.run_id) return undefined

  return {
    run_id: created.run_id,
    scenario_id: created.scenario.scenario_id,
    status: created.status ?? 'queued',
    message: created.message ?? 'Scenario run queued for precheck.',
    databricks_run_url: created.databricks_run_url,
  }
}

/**
 * New durable-run deployments return a run with scenario creation, so the UI
 * can navigate straight to server-owned precheck progress. Legacy deployments
 * still expose validation and run as separate calls; preserve that behavior
 * until the API cutover is complete.
 */
export function useCreateScenarioRun() {
  return useMutation({
    mutationFn: async (
      payload: ScenarioCreateRequest,
    ): Promise<ScenarioRunStart> => {
      const created = await api.createScenario(payload)
      const immediateRun = runReturnedWithScenario(created)
      if (immediateRun) {
        return { scenario: created.scenario, run: immediateRun }
      }

      const validation = await api.validateScenario(created.scenario.scenario_id)
      if (!validation.valid) {
        return { scenario: created.scenario, validation }
      }

      const run = await api.runScenario(created.scenario.scenario_id)
      return { scenario: created.scenario, run }
    },
  })
}

export function useDeleteScenario() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (scenarioId: string) => api.deleteScenario(scenarioId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['recent-scenarios'] }),
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

export function useUploadDeliveries() {
  return useMutation({
    mutationFn: (file: File) => api.uploadDeliveries(file),
  })
}

export function useOpenEditorSession() {
  return useMutation({
    mutationFn: api.openEditorSession,
  })
}

export function useInsertEditorRow() {
  return useMutation({
    mutationFn: ({
      sessionId,
      entityType,
      payload,
    }: {
      sessionId: string
      entityType: EditorEntityType
      payload: EditorInsertRequest
    }) => api.insertEditorRow(sessionId, entityType, payload),
  })
}

export function usePatchEditorRow() {
  return useMutation({
    mutationFn: ({
      sessionId,
      entityType,
      rowId,
      payload,
    }: {
      sessionId: string
      entityType: EditorEntityType
      rowId: string
      payload: EditorPatchRequest
    }) => api.patchEditorRow(sessionId, entityType, rowId, payload),
  })
}

export function useDeleteEditorRow() {
  return useMutation({
    mutationFn: ({
      sessionId,
      entityType,
      rowId,
      payload,
    }: {
      sessionId: string
      entityType: EditorEntityType
      rowId: string
      payload: EditorDeleteRequest
    }) => api.deleteEditorRow(sessionId, entityType, rowId, payload),
  })
}

export function useValidateEditorSession() {
  return useMutation({
    mutationFn: (sessionId: string) => api.validateEditorSession(sessionId),
  })
}

export function usePreviewEditorBaseline() {
  return useMutation({
    mutationFn: ({
      sessionId,
      payload,
    }: {
      sessionId: string
      payload: EditorPreviewRequest
    }) => api.previewEditorBaseline(sessionId, payload),
  })
}

export function useCommitEditorSession() {
  return useMutation({
    mutationFn: (sessionId: string) => api.commitEditorSession(sessionId),
  })
}

export function useDiscardEditorSession() {
  return useMutation({
    mutationFn: (sessionId: string) => api.discardEditorSession(sessionId),
  })
}
