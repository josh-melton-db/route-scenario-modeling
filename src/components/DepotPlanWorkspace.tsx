import { useEffect, useState } from 'react'
import { Loader2, Plus } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import type { DepotPlanDayResult, KpiDeltas, Kpis } from '@/api/types'
import {
  useCreateDepotPlanScenario,
  useDepotPlan,
  useDepotPlanBootstrap,
  useDepotPlanDay,
  useOptimizeDepotPlanDay,
  useResetDepotPlanDay,
} from '@/api/queries'
import ErrorState from './ErrorState'
import KpiDeltaGrid from './KpiDeltaGrid'
import MapView from './MapView'
import DualMap from './DualMap'
import RouteSidebar from './RouteSidebar'
import DepotPlanCalendar from './DepotPlanCalendar'
import DepotDemandReleasePanel from './DepotDemandReleasePanel'
import DepotOperationalOverrideForm, {
  emptyOperationalDraft,
  type OperationalDraft,
} from './DepotOperationalOverrideForm'
import { useRouteContext } from '@/state/useRouteContext'

export default function DepotPlanWorkspace({ mode }: { mode: 'analyze' | 'scenario' }) {
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
  const selectedDate = requestedDate || planData?.horizon_start || ''
  const day = useDepotPlanDay(planSetId, selectedDate, routeScenarioId)
  const createScenario = useCreateDepotPlanScenario(planSetId)
  const optimize = useOptimizeDepotPlanDay(planSetId, selectedDate)
  const reset = useResetDepotPlanDay(planSetId, routeScenarioId, selectedDate)
  const setFacility = useRouteContext((state) => state.setFacility)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [newScenarioName, setNewScenarioName] = useState('Operational plan')
  const [drafts, setDrafts] = useState<Record<string, OperationalDraft>>({})
  const [actionError, setActionError] = useState<string | null>(null)

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
      next.set('date', planData.horizon_start)
      changed = true
    }
    if (!searchParams.get('routePlanScenario')) {
      next.set('routePlanScenario', routeScenarioId)
      changed = true
    }
    if (changed) setSearchParams(next, { replace: true })
  }, [planData, requestedDate, requestedPlanId, routeScenarioId, searchParams, setFacility, setSearchParams])

  const activeDraft = drafts[selectedDate] ?? emptyOperationalDraft
  const currentResult = day.data?.selected_result ?? day.data?.default_result ?? null
  const pending = day.data?.default_status === 'queued' || day.data?.default_status === 'running' || day.data?.override_status === 'queued' || day.data?.override_status === 'running'
  const error = bootstrap.error ?? plan.error ?? day.error

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
    if (routeScenarioId === 'default') return
    setActionError(null)
    try {
      await optimize.mutateAsync({ route_scenario_id: routeScenarioId, ...activeDraft })
    } catch (err) {
      setActionError(String(err))
    }
  }

  async function resetDay() {
    setActionError(null)
    try {
      await reset.mutateAsync()
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

  if (error) return <ErrorState title="Could not load depot horizon" error={error} />
  if (!planData || !planSetId) {
    return <Loading label="Creating the stored depot horizon…" />
  }

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">{planData.depot.name} daily route plan</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {planData.horizon_start} to {planData.horizon_end} · {planData.coverage.solved_days}/{planData.coverage.total_days} solved
              {planData.is_partial ? ' · partial rollup' : ' · complete rollup'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">Fleet source: {planData.resource_source}</p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-muted-foreground">
              Route scenario
              <select
                aria-label="Route plan scenario"
                value={routeScenarioId}
                onChange={(event) => updateContext({ routePlanScenario: event.target.value })}
                className="mt-1 block h-9 rounded-md border border-border bg-background px-2 text-sm text-foreground"
              >
                {planData.scenarios.map((scenario) => <option key={scenario.route_scenario_id} value={scenario.route_scenario_id}>{scenario.scenario_name}</option>)}
              </select>
            </label>
            <input aria-label="New route scenario name" value={newScenarioName} onChange={(event) => setNewScenarioName(event.target.value)} className="h-9 rounded-md border border-border bg-background px-2 text-sm" />
            <button type="button" onClick={() => void addScenario()} disabled={createScenario.isPending} className="inline-flex h-9 items-center gap-1 rounded-md border border-border px-3 text-sm">
              <Plus className="h-4 w-4" /> Create
            </button>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
          <Coverage label="Solved" value={planData.coverage.solved_days} />
          <Coverage label="Queued" value={planData.coverage.queued_days} />
          <Coverage label="Running" value={planData.coverage.running_days} />
          <Coverage label="Failed" value={planData.coverage.failed_days} />
          <Coverage label="Total days" value={planData.coverage.total_days} />
        </div>
      </section>

      <DepotPlanCalendar days={planData.days} selectedDate={selectedDate} onSelect={(date) => updateContext({ date })} />

      {planData.kpis && <KpiDeltaGrid baselineKpis={planData.kpis} />}
      {planData.is_partial && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
          Horizon totals include only {planData.coverage.solved_days} solved dates. Queued, running, and failed dates are not counted as zero-cost delivery.
        </div>
      )}

      {mode === 'scenario' && routeScenarioId === 'default' && (
        <div className="rounded-md border border-border bg-card p-4 text-sm text-muted-foreground">
          Create or select a named route scenario before adding a day-specific operational override.
        </div>
      )}
      {mode === 'scenario' && routeScenarioId !== 'default' && (
        <DepotOperationalOverrideForm
          value={activeDraft}
          onChange={(value) => setDrafts((current) => ({ ...current, [selectedDate]: value }))}
          onOptimize={() => void optimizeDay()}
          onReset={() => void resetDay()}
          busy={optimize.isPending || reset.isPending}
          canReset={Boolean(day.data?.selected_result && day.data.selected_result.result_id !== day.data.default_result?.result_id)}
        />
      )}

      {actionError && <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{actionError}</div>}
      {mode === 'scenario' && (
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
      {day.data && <DayStatus detail={day.data} pending={pending} />}
      {day.data?.default_result && day.data.selected_result && day.data.selected_result.result_id !== day.data.default_result.result_id ? (
        <>
          <KpiDeltaGrid baselineKpis={day.data.default_result.kpis} scenarioKpis={day.data.selected_result.kpis} deltas={kpiDeltas(day.data.default_result.kpis, day.data.selected_result.kpis)} />
          <DualMap
            baselineDepot={planData.depot}
            scenarioDepot={planData.depot}
            baselineRoutes={day.data.default_result.routes}
            scenarioRoutes={day.data.selected_result.routes}
            status={day.data.selected_result.status === 'infeasible' ? 'infeasible' : 'succeeded'}
            baselineLabel="Stored default"
            scenarioLabel="Selected override"
          />
        </>
      ) : currentResult ? (
        <div className="flex min-h-[560px] overflow-hidden rounded-lg border border-border bg-card">
          <RouteSidebar routes={currentResult.routes} selectedRouteId={selectedRouteId} onSelectRoute={setSelectedRouteId} title={`${selectedDate} routes`} />
          <div className="min-w-0 flex-1"><MapView depot={planData.depot} routes={currentResult.routes} selectedRouteId={selectedRouteId} onSelectRoute={setSelectedRouteId} /></div>
        </div>
      ) : !day.isLoading ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">No stored result yet for this date.</div>
      ) : null}
    </div>
  )
}

function DayStatus({ detail, pending }: { detail: { default_status: string; override_status: string | null; selected_result: DepotPlanDayResult | null; error: string | null }; pending: boolean }) {
  const result = detail.selected_result
  return (
    <div className="rounded-md border border-border bg-card px-4 py-3 text-sm">
      <span className="font-medium capitalize">Default: {detail.default_status}</span>
      {detail.override_status && <span className="ml-4 capitalize">Override: {detail.override_status}</span>}
      {pending && <span className="ml-4 text-amber-500">Optimization in progress; the prior selected result remains visible.</span>}
      {result && <span className="ml-4">Assigned {result.assigned_cases} · routed {result.routed_cases} · unserved {result.unserved_cases}</span>}
      {detail.error && <div className="mt-2 text-destructive">{detail.error}</div>}
    </div>
  )
}

function Coverage({ label, value }: { label: string; value: number }) {
  return <div className="rounded-md border border-border bg-background/40 p-2"><div className="font-semibold tabular-nums">{value}</div><div className="text-xs text-muted-foreground">{label}</div></div>
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
