import { useEffect, useState } from 'react'
import { Loader2, Plus } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '@/api/client'
import type { DepotPlanDayResult, KpiDeltas, Kpis } from '@/api/types'
import {
  useCreateDepotPlanScenario,
  useDepotPlan,
  useDepotPlanBootstrap,
  useDepotPlanDay,
  useOptimizeDepotPlanDay,
  useResetDepotPlanDay,
  useSolveDepotPlanDay,
  queryKeys,
} from '@/api/queries'
import { defaultDepotServiceDate } from '@/lib/networkLinks'
import ErrorState from './ErrorState'
import KpiDeltaGrid from './KpiDeltaGrid'
import MapView from './MapView'
import DualMap from './DualMap'
import RouteSidebar from './RouteSidebar'
import DepotPlanCalendar from './DepotPlanCalendar'
import DepotDemandReleasePanel from './DepotDemandReleasePanel'
import DepotOperationalOverrideForm, {
  emptyOperationalDraft,
} from './DepotOperationalOverrideForm'
import { useRoutePlanDrafts } from '@/state/useRoutePlanDrafts'
import { useRouteContext } from '@/state/useRouteContext'

export default function DepotPlanWorkspace({ mode }: { mode: 'analyze' | 'scenario' }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const runId = searchParams.get('networkRun') ?? ''
  const depotId = searchParams.get('depot') ?? ''
  const requestedPlanId = searchParams.get('depotPlan') ?? ''
  const requestedDate = searchParams.get('date') ?? ''
  const routeScenarioId = searchParams.get('routePlanScenario') ?? 'default'
  const bootstrap = useDepotPlanBootstrap(requestedPlanId ? '' : runId, depotId, requestedDate || undefined)
  const planSetId = requestedPlanId || bootstrap.data?.plan_set_id || ''
  const plan = useDepotPlan(planSetId, routeScenarioId)
  const planData = plan.data ?? bootstrap.data
  const selectedDate = requestedDate || (planData ? defaultDepotServiceDate(planData.horizon_start, planData.horizon_end) : '')
  const day = useDepotPlanDay(planSetId, selectedDate, routeScenarioId)
  const createScenario = useCreateDepotPlanScenario(planSetId)
  const optimize = useOptimizeDepotPlanDay(planSetId, selectedDate)
  const reset = useResetDepotPlanDay(planSetId, routeScenarioId, selectedDate)
  const solve = useSolveDepotPlanDay(planSetId)
  const setFacility = useRouteContext((state) => state.setFacility)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [newScenarioName, setNewScenarioName] = useState('Operational plan')
  const drafts = useRoutePlanDrafts((state) => state.drafts)
  const setDraft = useRoutePlanDrafts((state) => state.setDraft)
  const clearDraft = useRoutePlanDrafts((state) => state.clearDraft)
  const [showRelease, setShowRelease] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(false)

  useEffect(() => {
    if (!planData) return
    setFacility({
      facilityId: planData.depot.depot_id,
      facilityName: planData.depot.name,
      facilityType: 'depot',
    })
    const next = new URLSearchParams(searchParams)
    let changed = false
    if (!requestedPlanId) {
      next.set('depotPlan', planData.plan_set_id)
      changed = true
    }
    if (!requestedDate) {
      next.set('date', defaultDepotServiceDate(planData.horizon_start, planData.horizon_end))
      changed = true
    }
    if (!searchParams.get('routePlanScenario')) {
      next.set('routePlanScenario', routeScenarioId)
      changed = true
    }
    if (changed) setSearchParams(next, { replace: true })
  }, [planData, requestedDate, requestedPlanId, routeScenarioId, searchParams, setFacility, setSearchParams])

  const draftKey = `${planSetId}:${routeScenarioId}:${selectedDate}`
  const activeDraft = drafts[draftKey] ?? day.data?.override_request ?? emptyOperationalDraft
  const currentResult = day.data?.selected_result ?? day.data?.default_result ?? null
  const pending = day.data?.default_status === 'queued' || day.data?.default_status === 'running' || day.data?.override_status === 'queued' || day.data?.override_status === 'running'
  const error = bootstrap.error ?? plan.error ?? day.error

  async function restoreWorkspace() {
    setRestoring(true)
    setActionError(null)
    try {
      const restored = await api.createDepotPlan(runId, depotId, requestedDate || undefined)
      let restoredScenarioId = 'default'
      if (routeScenarioId !== 'default') {
        const name = planData?.scenarios.find((row) => row.route_scenario_id === routeScenarioId)?.scenario_name
          ?? newScenarioName
        const restoredScenario = await api.createDepotPlanScenario(restored.plan_set_id, name)
        restoredScenarioId = restoredScenario.route_scenario_id
        setDraft(`${restored.plan_set_id}:${restoredScenarioId}:${selectedDate || restored.horizon_start}`, activeDraft)
      }
      queryClient.setQueryData(queryKeys.depotPlanBootstrap(runId, depotId), restored)
      const next = new URLSearchParams(searchParams)
      next.set('depotPlan', restored.plan_set_id)
      next.set('routePlanScenario', restoredScenarioId)
      next.set('date', selectedDate || restored.horizon_start)
      setSearchParams(next, { replace: true })
      navigate(`/scenario?${next.toString()}`, { replace: true })
    } catch (err) {
      setActionError(String(err))
    } finally {
      setRestoring(false)
    }
  }

  async function addScenario() {
    if (!newScenarioName.trim()) return
    setActionError(null)
    try {
      const created = await createScenario.mutateAsync(newScenarioName.trim())
      updateContext({ routePlanScenario: created.route_scenario_id })
    } catch (err) {
      setActionError(String(err))
    }
  }

  async function optimizeDay() {
    if (routeScenarioId === 'default' || !day.data?.default_result) return
    setActionError(null)
    try {
      await optimize.mutateAsync({ route_scenario_id: routeScenarioId, ...activeDraft })
      navigate(`/analyze?${searchParams.toString()}`)
    } catch (err) {
      setActionError(String(err))
    }
  }

  async function resetDay() {
    setActionError(null)
    try {
      await reset.mutateAsync()
      clearDraft(draftKey)
    } catch (err) {
      setActionError(String(err))
    }
  }

  async function solveDay(serviceDate: string) {
    setActionError(null)
    try {
      await solve.mutateAsync(serviceDate)
      updateContext({ date: serviceDate })
    } catch (err) {
      setActionError(String(err))
    }
  }

  function updateContext(values: Record<string, string>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(values)) next.set(key, value)
    setSelectedRouteId(null)
    setSearchParams(next)
  }

  if (error instanceof ApiError && error.status === 404 && requestedPlanId) {
    return <div className="mx-auto flex max-w-xl flex-col gap-3 p-8" role="alert">
      <h2 className="font-semibold">This depot plan is no longer available</h2>
      <p className="text-sm text-muted-foreground">The local demo may have restarted or the plan may have been removed. Restore the workspace to prepare routes again. Any scenario changes still in this browser will be carried over for review.</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={restoring} onClick={() => void restoreWorkspace()} className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">{restoring ? 'Restoring…' : 'Restore depot workspace'}</button>
        <button type="button" onClick={() => navigate(searchParams.get('networkReturn') || '/network')} className="rounded-md border border-border px-3 py-2 text-sm">Back to network</button>
      </div>
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}
    </div>
  }
  if (error) return <ErrorState title="Could not load depot horizon" error={error} />
  if (!planData || !planSetId) {
    return <Loading label="Creating the stored depot horizon…" />
  }

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-muted-foreground">
            Route scenario
            <select aria-label="Route plan scenario" value={routeScenarioId}
              onChange={(event) => updateContext({ routePlanScenario: event.target.value })}
              className="mt-1 block h-9 rounded-md border border-border bg-background px-2 text-sm text-foreground">
              {planData.scenarios.map((scenario) => <option key={scenario.route_scenario_id} value={scenario.route_scenario_id}>{scenario.scenario_name}</option>)}
            </select>
          </label>
          {mode === 'scenario' && <>
            <input aria-label="New route scenario name" value={newScenarioName} onChange={(event) => setNewScenarioName(event.target.value)} className="h-9 rounded-md border border-border bg-background px-2 text-sm" />
            <button type="button" onClick={() => void addScenario()} disabled={createScenario.isPending} className="inline-flex h-9 items-center gap-1 rounded-md border border-border px-3 text-sm">
              <Plus className="h-4 w-4" /> Create scenario
            </button>
          </>}
        </div>
        {mode === 'scenario' && <DepotPlanCalendar days={planData.days} selectedDate={selectedDate} onSelect={(date) => updateContext({ date })} onSolve={(date) => void solveDay(date)} solvingDate={solve.isPending ? solve.variables : null} />}
      </div>

      {mode === 'scenario' && routeScenarioId === 'default' && (
        <div className="rounded-md border border-border bg-card p-4 text-sm text-muted-foreground">
          Select a scenario or create one to add changes.
        </div>
      )}
      {mode === 'scenario' && !day.data?.default_result && (
        <div role="status" className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm">
          <span>{pending ? 'Solving baseline…' : 'Baseline not solved for this date'}</span>
          {!pending && <button type="button" onClick={() => void solveDay(selectedDate)} disabled={solve.isPending} className="rounded-md border border-border px-3 py-1.5 text-xs font-medium">Solve baseline</button>}
        </div>
      )}
      {mode === 'scenario' && routeScenarioId !== 'default' && (
        <DepotOperationalOverrideForm
          key={draftKey}
          value={activeDraft}
          onChange={(value) => setDraft(draftKey, value)}
          onOptimize={() => void optimizeDay()}
          onReset={() => void resetDay()}
          busy={optimize.isPending || reset.isPending}
          canReset={Boolean(day.data?.override_status || day.data?.override_request || drafts[draftKey])}
          canOptimize={Boolean(day.data?.default_result)}
          depot={planData.depot}
          baselineRoutes={day.data?.default_result?.routes ?? currentResult?.routes ?? []}
        />
      )}

      {actionError && <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{actionError}</div>}
      {mode === 'scenario' && routeScenarioId !== 'default' && !showRelease && <button type="button" onClick={() => setShowRelease(true)} className="inline-flex w-fit items-center gap-1 rounded-md border border-border px-3 py-2 text-sm"><Plus className="h-4 w-4" />Release deliveries for reassignment</button>}
      {mode === 'scenario' && showRelease && (
        <DepotDemandReleasePanel
          key={`${runId}:${routeScenarioId}:${selectedDate}`}
          runId={runId}
          planSetId={planSetId}
          depotId={planData.depot.depot_id}
          routeScenarioId={routeScenarioId}
          serviceDate={selectedDate}
        />
      )}
      {day.isLoading && <Loading label={`Loading ${selectedDate}…`} />}
      {day.error && <ErrorState title="Could not load the selected route day" error={day.error} />}
      {mode === 'analyze' && <>
      {currentResult && (!day.data?.default_result || currentResult.result_id === day.data.default_result.result_id) && <KpiDeltaGrid baselineKpis={currentResult.kpis} />}
      {day.data && <DayStatus detail={day.data} pending={pending} />}
      {currentResult && currentResult.unserved_cases > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-md border border-destructive/35 bg-destructive/5 px-3 py-2">
          <p className="text-xs text-muted-foreground">Unserved: {currentResult.unserved_cases} cases</p>
        </div>
      )}
      {day.data?.default_result && day.data.selected_result && day.data.selected_result.result_id !== day.data.default_result.result_id ? (
        <>
          <DepotPlanCalendar days={planData.days} selectedDate={selectedDate} onSelect={(date) => updateContext({ date })} onSolve={(date) => void solveDay(date)} solvingDate={solve.isPending ? solve.variables : null} />
          <KpiDeltaGrid baselineKpis={day.data.default_result.kpis} scenarioKpis={day.data.selected_result.kpis} deltas={kpiDeltas(day.data.default_result.kpis, day.data.selected_result.kpis)} />
          <DualMap
            baselineDepot={planData.depot}
            scenarioDepot={day.data.selected_result.depot ?? planData.depot}
            baselineRoutes={day.data.default_result.routes}
            scenarioRoutes={day.data.selected_result.routes}
            status={day.data.selected_result.status === 'infeasible' ? 'infeasible' : 'succeeded'}
            baselineLabel="Stored default"
            scenarioLabel="Selected override"
          />
        </>
      ) : currentResult ? (
        <div className="flex h-[clamp(480px,65vh,680px)] overflow-hidden rounded-lg border border-border bg-card">
          <RouteSidebar routes={currentResult.routes} selectedRouteId={selectedRouteId} onSelectRoute={setSelectedRouteId} title={`${selectedDate} routes`} headerAction={<DepotPlanCalendar days={planData.days} selectedDate={selectedDate} onSelect={(date) => updateContext({ date })} onSolve={(date) => void solveDay(date)} solvingDate={solve.isPending ? solve.variables : null} />} />
          <div className="min-w-0 flex-1"><MapView depot={currentResult.depot ?? planData.depot} routes={currentResult.routes} selectedRouteId={selectedRouteId} onSelectRoute={setSelectedRouteId} /></div>
        </div>
      ) : !day.isLoading ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          <DepotPlanCalendar days={planData.days} selectedDate={selectedDate} onSelect={(date) => updateContext({ date })} onSolve={(date) => void solveDay(date)} solvingDate={solve.isPending ? solve.variables : null} />
          <p className="mt-3">No stored result yet for this date.</p>
          {day.data?.default_status === 'not_requested' && <button type="button" onClick={() => void solveDay(selectedDate)} disabled={solve.isPending} className="mt-3 rounded-md bg-primary px-3 py-2 font-semibold text-primary-foreground disabled:opacity-50">{solve.isPending ? 'Queueing solve…' : 'Solve this date'}</button>}
        </div>
      ) : null}
      </>}
    </div>
  )
}

function DayStatus({ detail, pending }: { detail: { default_status: string; override_status: string | null; selected_result: DepotPlanDayResult | null; error: string | null }; pending: boolean }) {
  if (!pending && !detail.error) return null
  return <div role="status" className="rounded-md border border-border px-3 py-2 text-sm">
    {pending && 'Optimizing…'}
    {detail.error && <div role="alert" className="text-destructive">{detail.error}</div>}
  </div>
}

function Loading({ label }: { label: string }) {
  return <div className="flex h-56 items-center justify-center text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{label}</div>
}

function kpiDeltas(base: Kpis, selected: Kpis): KpiDeltas {
  return {
    route_count: selected.route_count - base.route_count,
    driver_count: selected.driver_count - base.driver_count,
    vehicle_count: selected.vehicle_count - base.vehicle_count,
    total_miles: selected.total_miles - base.total_miles,
    drive_minutes: selected.drive_minutes - base.drive_minutes,
    service_minutes: selected.service_minutes - base.service_minutes,
    total_cases: selected.total_cases - base.total_cases,
    avg_stops_per_route: selected.avg_stops_per_route - base.avg_stops_per_route,
    avg_capacity_utilization_pct: selected.avg_capacity_utilization_pct - base.avg_capacity_utilization_pct,
    avg_driver_utilization_pct: selected.avg_driver_utilization_pct - base.avg_driver_utilization_pct,
    overtime_minutes: selected.overtime_minutes - base.overtime_minutes,
    missed_windows: selected.missed_windows - base.missed_windows,
    late_minutes: selected.late_minutes - base.late_minutes,
    total_revenue: selected.total_revenue - base.total_revenue,
    profit: selected.profit - base.profit,
    mileage_cost: selected.cost_breakdown.mileage_cost - base.cost_breakdown.mileage_cost,
    labor_cost: selected.cost_breakdown.labor_cost - base.cost_breakdown.labor_cost,
    overtime_cost: selected.cost_breakdown.overtime_cost - base.cost_breakdown.overtime_cost,
    fixed_vehicle_cost: selected.cost_breakdown.fixed_vehicle_cost - base.cost_breakdown.fixed_vehicle_cost,
    sla_penalty_cost: selected.cost_breakdown.sla_penalty_cost - base.cost_breakdown.sla_penalty_cost,
    carrier_linehaul_cost: selected.cost_breakdown.carrier_linehaul_cost - base.cost_breakdown.carrier_linehaul_cost,
    carrier_lane_cost: selected.cost_breakdown.carrier_lane_cost - base.cost_breakdown.carrier_lane_cost,
    carrier_stop_cost: selected.cost_breakdown.carrier_stop_cost - base.cost_breakdown.carrier_stop_cost,
    carrier_minimum_adjustment: selected.cost_breakdown.carrier_minimum_adjustment - base.cost_breakdown.carrier_minimum_adjustment,
    fuel_surcharge_cost: selected.cost_breakdown.fuel_surcharge_cost - base.cost_breakdown.fuel_surcharge_cost,
    accessorial_cost: selected.cost_breakdown.accessorial_cost - base.cost_breakdown.accessorial_cost,
    volume_tier_adjustment: selected.cost_breakdown.volume_tier_adjustment - base.cost_breakdown.volume_tier_adjustment,
    commitment_adjustment: selected.cost_breakdown.commitment_adjustment - base.cost_breakdown.commitment_adjustment,
    total_cost: selected.cost_breakdown.total_cost - base.cost_breakdown.total_cost,
  }
}
