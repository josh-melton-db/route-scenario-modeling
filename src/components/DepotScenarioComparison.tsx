import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import type { DepotPlanDayResult, DepotPlanSet } from '@/api/types'
import { useDepotPlanDay } from '@/api/queries'
import MapView, { type ViewState } from './MapView'
import KpiDeltaGrid from './KpiDeltaGrid'
import { kpiDeltas } from '@/lib/depotKpiDeltas'

const reasons: Record<string, string> = {
  no_contract_rate: 'No contract rate',
  road_unreachable: 'No reachable truck-road path',
  capacity_infeasible: 'Delivery exceeds vehicle capacity',
  time_window_infeasible: 'Delivery time window cannot be met',
  route_duration_infeasible: 'Delivery exceeds route duration',
  no_vehicle_available: 'No vehicle available',
  solver_no_solution: 'Solver did not find a feasible plan',
  dropped_by_solver_penalty: 'Solver left this delivery out; the binding constraint is not confirmed',
}
export default function DepotScenarioComparison({ plan, serviceDate, leftId, rightId, onSelect }: {
  plan: DepotPlanSet; serviceDate: string; leftId: string; rightId: string
  onSelect: (side: 'left' | 'right', id: string) => void
}) {
  const left = useDepotPlanDay(plan.plan_set_id, serviceDate, leftId)
  const right = useDepotPlanDay(rightId === 'none' ? '' : plan.plan_set_id, serviceDate, rightId)
  const [viewState, setViewState] = useState<ViewState | undefined>()
  const [selectedRoute, setSelectedRoute] = useState<string | null>(null)
  function state(query: typeof left, id: string) {
    const data = query.data
    const status = id === 'default' ? data?.default_status : data?.override_status
    const pending = query.isLoading || status === 'queued' || status === 'running' || (!data?.default_result && (data?.default_status === 'queued' || data?.default_status === 'running'))
    const result = id === 'default' ? data?.default_result : data?.selected_result?.result_id !== data?.default_result?.result_id ? data?.selected_result : null
    return { pending, result: pending ? null : result, error: query.error ? String(query.error) : data?.error }
  }
  const a = state(left, leftId), b = state(right, rightId)
  function panel(side: 'left' | 'right', id: string, value: typeof a) {
    return <section className="min-w-0 rounded-lg border border-border bg-card p-3">
      <label className="text-xs text-muted-foreground">{side === 'left' ? 'First scenario' : 'Compare with'}
        <select aria-label={`${side} comparison scenario`} value={id} onChange={event => onSelect(side, event.target.value)} className="mt-1 mb-3 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground">
          {side === 'right' && <option value="none">None — single map</option>}
          {plan.scenarios.map(row => <option key={row.route_scenario_id} value={row.route_scenario_id}>{row.scenario_name}</option>)}
        </select>
      </label>
      {value.pending ? <div role="status" className="flex h-[480px] items-center justify-center gap-2"><Loader2 className="h-5 w-5 animate-spin" />Optimizing…</div> : value.error ? <p role="alert" className="text-destructive">{value.error}</p> : value.result ? <>
        <p className="mb-2 text-xs text-muted-foreground">{serviceDate} routes</p>
        <div className="h-[480px]"><MapView depot={value.result.depot ?? plan.depot} routes={value.result.routes} selectedRouteId={selectedRoute} onSelectRoute={setSelectedRoute} viewState={viewState} onViewStateChange={setViewState} /></div>
        <Unserved result={value.result} />
      </> : <div className="flex h-[480px] items-center justify-center text-sm text-muted-foreground">No optimization saved for this scenario and date. Run it from Scenarios.</div>}
    </section>
  }
  return <>
    {a.result && <p className="text-xs text-muted-foreground">KPIs: {plan.scenarios.find(row => row.route_scenario_id === (b.result ? rightId : leftId))?.scenario_name}{b.result && ` · Change versus ${plan.scenarios.find(row => row.route_scenario_id === leftId)?.scenario_name}`}</p>}
    {a.result && <KpiDeltaGrid baselineKpis={a.result.kpis} scenarioKpis={b.result?.kpis} deltas={b.result ? kpiDeltas(a.result.kpis, b.result.kpis) : undefined} />}
    {rightId === 'none' && <label className="text-xs text-muted-foreground">Compare with<select aria-label="right comparison scenario" value="none" onChange={event => onSelect('right', event.target.value)} className="ml-2 rounded-md border border-border bg-background px-3 py-2 text-foreground"><option value="none">None — single map</option>{plan.scenarios.map(row => <option key={row.route_scenario_id} value={row.route_scenario_id}>{row.scenario_name}</option>)}</select></label>}
    <div className={`grid gap-4 ${rightId !== 'none' ? 'lg:grid-cols-2' : ''}`}>{panel('left', leftId, a)}{rightId !== 'none' && panel('right', rightId, b)}</div>
  </>
}
function Unserved({ result }: { result: DepotPlanDayResult }) {
  const money = (value: number) => value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
  const showOverflow = result.execution?.allow_contracted_overflow || result.fleet_cost != null || (result.contracted_deliveries ?? 0) > 0
  return <div className="mt-3 text-sm">
    {showOverflow && <>
      <p>Fleet cost: {money(result.fleet_cost ?? result.kpis.cost_breakdown.total_cost)} · Contracted cost: {money(result.contracted_cost ?? 0)} · Contracted revenue: {money(result.contracted_revenue ?? 0)} · Total cost: {money(result.kpis.cost_breakdown.total_cost)}</p>
      <p>Contracted: {result.contracted_deliveries ?? 0} deliveries · {result.contracted_cases ?? 0} cases</p>
      {(result.kpis.cost_breakdown.volume_tier_adjustment ?? 0) < 0 && <p>Total tier discount: {money(-result.kpis.cost_breakdown.volume_tier_adjustment)}</p>}
    </>}
    {(result.contracted_orders?.length ?? 0) > 0 && <details className="mt-2">
      <summary>Contracted delivery rates</summary>
      <p className="text-xs text-muted-foreground">Charge lines apply to the shared quote, not separately to each delivery.</p>
      {result.contracted_orders?.map((order, index) => <div key={`${order.quote_id}:${order.order_id ?? index}`} className="mt-2">
        <p>{order.customer_id} · {order.demand_cases} cases · {order.contract_id} · {order.contract_version_id} · {order.matched_lane}</p>
        <ul>{order.charge_lines.map((line, index) => <li key={`${line.rule_id}:${index}`}>{line.label}: {money(line.amount)}</li>)}</ul>
      </div>)}
    </details>}
    {result.execution?.available_vehicle_count != null && <p className="text-muted-foreground">Available vehicles: {result.execution.available_vehicle_count} · Requested driver change: {result.execution.driver_delta ?? 0}</p>}
    {result.unserved_cases > 0 && <details className="mt-2" open><summary className="font-medium text-destructive">Unserved: {result.unserved_cases} cases</summary>
      {result.unserved_orders?.length ? <ul className="mt-2 space-y-1">{result.unserved_orders.map((row, index) => <li key={`${row.customer_id}:${index}`}>{row.customer_name || row.customer_id} · {row.demand_cases} cases · {reasons[row.reason] || row.reason || 'Reason unavailable'}</li>)}</ul> : <p className="mt-2 text-muted-foreground">This saved run did not retain delivery-level reasons. Rerun the scenario to collect them.</p>}
    </details>}
  </div>
}
