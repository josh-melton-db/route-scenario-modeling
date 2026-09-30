export const ROUTE_CONTEXT_KEYS = [
  'networkScenario',
  'networkRun',
  'depot',
  'date',
  'depotPlan',
  'routePlanScenario',
  'networkReturn',
] as const

export interface ParentRouteContext {
  networkScenario?: string
  networkRun?: string
  depot?: string
  date?: string
  depotPlan?: string
  routePlanScenario?: string
  networkReturn?: string
}

export function readParentRouteContext(params: URLSearchParams): ParentRouteContext {
  return {
    networkScenario: params.get('networkScenario') || undefined,
    networkRun: params.get('networkRun') || undefined,
    depot: params.get('depot') || undefined,
    date: params.get('date') || undefined,
    depotPlan: params.get('depotPlan') || undefined,
    routePlanScenario: params.get('routePlanScenario') || undefined,
    networkReturn: params.get('networkReturn') || undefined,
  }
}

export function buildNetworkScenarioReturnHref(scenarioId: string, runId?: string) {
  const href = `/network/scenarios/${encodeURIComponent(scenarioId)}/flow`
  return runId ? `${href}?run=${encodeURIComponent(runId)}` : href
}

export function buildRouteWorkspaceHref(
  pathname: string,
  context: ParentRouteContext,
  extra?: Record<string, string | null | undefined>,
) {
  const [path, existingSearch = ''] = pathname.split('?', 2)
  const params = new URLSearchParams(existingSearch)
  for (const key of ROUTE_CONTEXT_KEYS) {
    const value = context[key]
    if (value) params.set(key, value)
  }
  for (const [key, value] of Object.entries(extra ?? {})) {
    if (value) params.set(key, value)
    else params.delete(key)
  }
  const search = params.toString()
  return search ? `${path}?${search}` : path
}

/** Deep link from the network plan into the existing depot route workspace. */
export function buildDepotAnalysisHref(
  depotId: string,
  horizonStart: string,
  horizonEnd: string,
  networkScenario = 'baseline',
  networkRun?: string,
  networkReturn?: string,
) {
  const serviceDate = firstWeekdayInRange(horizonStart, horizonEnd, 2)
  if (!serviceDate) return null
  return buildRouteWorkspaceHref('/analyze', {
    depot: depotId,
    date: serviceDate,
    networkScenario,
    networkRun,
    networkReturn:
      networkReturn ??
      (networkScenario !== 'baseline'
        ? buildNetworkScenarioReturnHref(networkScenario, networkRun)
        : '/network'),
  })
}

function firstWeekdayInRange(start: string, end: string, weekday: number) {
  const current = new Date(`${start}T12:00:00`)
  const final = new Date(`${end}T12:00:00`)
  while (current <= final) {
    if (current.getDay() === weekday) return current.toISOString().slice(0, 10)
    current.setDate(current.getDate() + 1)
  }
  return null
}
