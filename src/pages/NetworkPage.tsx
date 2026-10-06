import { useEffect, useMemo } from 'react'
import { Loader2 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useNavigate, useSearchParams } from 'react-router-dom'
import type {
  NetworkOverviewParams,
  NetworkOptions,
} from '@/api/types'
import { useNetworkOptions, useNetworkOverview } from '@/api/queries'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import NetworkContextBar from '@/components/NetworkContextBar'
import NetworkDetailDrawer from '@/components/NetworkDetailDrawer'
import NetworkFlowMap from '@/components/NetworkFlowMap'
import NetworkInsightRail from '@/components/NetworkInsightRail'
import NetworkKpiStrip from '@/components/NetworkKpiStrip'
import NetworkBaselineActions from '@/components/NetworkBaselineActions'
import { buildDepotAnalysisHref, buildRouteWorkspaceHref } from '@/lib/networkLinks'

const queryNames: Record<keyof NetworkOverviewParams, string> = {
  demand_plan_version_id: 'demandPlan',
  capacity_plan_version_id: 'capacityPlan',
  horizon_start: 'start',
  horizon_end: 'end',
  region_id: 'region',
  lane_type: 'laneType',
  metric: 'metric',
}

export default function NetworkPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const options = useNetworkOptions()
  const context = useMemo(
    () => (options.data ? contextFromUrl(searchParams, options.data) : null),
    [options.data, searchParams],
  )
  const overview = useNetworkOverview(context)
  const baselinePlan = useQuery({
    queryKey: ['network-baseline-plan-run', context],
    queryFn: () => api.networkBaselinePlanRun(context!),
    enabled: Boolean(context),
  })

  useEffect(() => {
    if (!context) return
    const next = new URLSearchParams(searchParams)
    let changed = false
    for (const [field, queryName] of Object.entries(queryNames)) {
      if (!next.has(queryName)) {
        next.set(queryName, String(context[field as keyof NetworkOverviewParams]))
        changed = true
      }
    }
    if (changed) setSearchParams(next, { replace: true })
  }, [context, searchParams, setSearchParams])

  if (options.error) {
    return <ErrorState title="Could not load network planning options" error={options.error} />
  }
  if (options.isLoading || !options.data || !context) return <NetworkLoading />

  function updateContext(patch: Partial<NetworkOverviewParams>) {
    const next = new URLSearchParams(searchParams)
    for (const [field, value] of Object.entries(patch)) {
      next.set(queryNames[field as keyof NetworkOverviewParams], String(value))
    }
    next.delete('facility')
    next.delete('lane')
    setSearchParams(next)
  }

  function selectEntity(entityType: 'facility' | 'lane', entityId: string | null) {
    const next = new URLSearchParams(searchParams)
    if (entityType === 'facility') {
      if (entityId) next.set('facility', entityId)
      else next.delete('facility')
      next.delete('lane')
    } else {
      if (entityId) next.set('lane', entityId)
      else next.delete('lane')
      next.delete('facility')
    }
    setSearchParams(next, { replace: true })
  }

  if (overview.error) {
    return (
      <div className="flex flex-col gap-4 px-4 py-5 sm:px-6 lg:px-8">
        <NetworkContextBar
          options={options.data}
          value={context}
          onChange={updateContext}
        />
        <ErrorState title="Could not load the network overview" error={overview.error} />
      </div>
    )
  }

  if (overview.isLoading || !overview.data) return <NetworkLoading contextBar />
  if (!overview.data.facilities.length) {
    return (
      <EmptyState
        title="No network facilities in this context"
        description="Choose another region or published input plan."
      />
    )
  }

  const selectedFacility =
    overview.data.facilities.find(
      (row) => row.facility_id === searchParams.get('facility'),
    ) ?? null
  const selectedLane =
    overview.data.lanes.find((row) => row.lane_id === searchParams.get('lane')) ?? null
  const networkReturn = `/network?${searchParams.toString()}`
  const depotAnalysisHref = selectedFacility?.depot_analysis_available && baselinePlan.data?.run_id
    ? buildDepotAnalysisHref(
        selectedFacility.facility_id,
        context.horizon_start,
        context.horizon_end,
        baselinePlan.data.scenario_id,
        baselinePlan.data.run_id,
        networkReturn,
      )
    : null
  const dcAnalysisHref =
    selectedFacility?.facility_type === 'distribution_center' && baselinePlan.data?.run_id
      ? buildRouteWorkspaceHref(`/dc/${encodeURIComponent(selectedFacility.facility_id)}`, {
          networkScenario: baselinePlan.data.scenario_id,
          networkRun: baselinePlan.data.run_id,
          networkReturn,
        })
      : null

  const facilities = overview.data.facilities

  const openFacility = (facilityId: string | null) => {
    if (!facilityId) {
      selectEntity('facility', null)
      return
    }
    const facility = facilities.find((row) => row.facility_id === facilityId)
    if (!facility) return

    if (facility.facility_type === 'distribution_center') {
      selectEntity('facility', facilityId)
      return
    }

    const href = facility.depot_analysis_available && baselinePlan.data?.run_id
      ? buildDepotAnalysisHref(
          facility.facility_id,
          context.horizon_start,
          context.horizon_end,
          baselinePlan.data.scenario_id,
          baselinePlan.data.run_id,
          networkReturn,
        )
      : null
    if (href) {
      navigate(href)
      return
    }

    selectEntity('facility', facilityId)
  }

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <NetworkContextBar
        options={options.data}
        value={context}
        onChange={updateContext}
      />
      <NetworkKpiStrip overview={overview.data} />
      <NetworkBaselineActions />
      {baselinePlan.isLoading && <p className="text-xs text-muted-foreground">Preparing the baseline's immutable depot-planning context…</p>}
      {baselinePlan.error && <p role="alert" className="text-xs text-destructive">Depot planning context could not be loaded: {String(baselinePlan.error)}</p>}
      {overview.data.is_partial && (
        <div className="rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-warning">
          This view is partial. Available facts are shown with their latest published freshness.
        </div>
      )}
      <div className="grid min-h-0 gap-4 xl:h-[calc(100svh-16rem)] xl:min-h-[560px] xl:grid-cols-[minmax(0,1fr)_340px]">
        <NetworkFlowMap
          facilities={overview.data.facilities}
          lanes={overview.data.lanes}
          selectedFacilityId={selectedFacility?.facility_id ?? null}
          selectedLaneId={selectedLane?.lane_id ?? null}
          onSelectFacility={openFacility}
          onSelectLane={(id) => selectEntity('lane', id)}
        />
        <NetworkInsightRail
          summary={overview.data.summary}
          insights={overview.data.insights}
          onSelect={(entityType, entityId) => selectEntity(entityType, entityId)}
        />
      </div>
      <NetworkDetailDrawer
        facility={selectedFacility}
        lane={selectedLane}
        facilities={facilities}
        depotAnalysisHref={depotAnalysisHref}
        dcAnalysisHref={dcAnalysisHref}
        onClose={() => {
          const next = new URLSearchParams(searchParams)
          next.delete('facility')
          next.delete('lane')
          setSearchParams(next, { replace: true })
        }}
        onSelectFacility={(facilityId) => selectEntity('facility', facilityId)}
        shortageScenarioId={baselinePlan.data?.scenario_id}
        shortageRunId={baselinePlan.data?.run_id}
      />
    </div>
  )
}

function contextFromUrl(
  searchParams: URLSearchParams,
  options: NetworkOptions,
): NetworkOverviewParams {
  const laneType = searchParams.get('laneType')
  const metric = searchParams.get('metric')
  return {
    demand_plan_version_id:
      searchParams.get('demandPlan') ?? options.default_demand_plan_version_id,
    capacity_plan_version_id:
      searchParams.get('capacityPlan') ?? options.default_capacity_plan_version_id,
    horizon_start: searchParams.get('start') ?? options.default_horizon_start,
    horizon_end: searchParams.get('end') ?? options.default_horizon_end,
    region_id: searchParams.get('region') ?? options.default_region_id,
    lane_type: options.lane_types.includes(laneType as NetworkOverviewParams['lane_type'])
      ? (laneType as NetworkOverviewParams['lane_type'])
      : options.lane_types.includes('ALL') ? 'ALL' : options.default_lane_type,
    metric: options.metrics.some((row) => row.metric_id === metric)
      ? (metric as NetworkOverviewParams['metric'])
      : options.default_metric,
  }
}

function NetworkLoading({ contextBar = false }: { contextBar?: boolean }) {
  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      {contextBar && <div className="h-36 animate-pulse rounded-lg border border-border bg-card" />}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="h-24 animate-pulse rounded-lg border border-border bg-card" />
        ))}
      </div>
      <div className="flex h-[520px] items-center justify-center rounded-lg border border-border bg-card text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading network plan...
      </div>
    </div>
  )
}
