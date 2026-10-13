import { useQuery } from '@tanstack/react-query'
import { useSearchParams, Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { api } from '@/api/client'
import { useDepotPlan, useDepotPlanBootstrap } from '@/api/queries'
import { defaultDepotServiceDate } from '@/lib/networkLinks'
import ErrorState from './ErrorState'

export default function DepotInputsView() {
  const [params, setParams] = useSearchParams()
  const requestedId = params.get('depotPlan') || ''
  const scenario = params.get('routePlanScenario') || 'default'
  const bootstrap = useDepotPlanBootstrap(requestedId ? '' : params.get('networkRun') || '', params.get('depot') || '', params.get('date') || undefined)
  const planId = requestedId || bootstrap.data?.plan_set_id || ''
  const plan = useDepotPlan(planId, scenario)
  const data = plan.data || bootstrap.data
  const date = params.get('date') || (data ? defaultDepotServiceDate(data.horizon_start, data.horizon_end) : '')
  const inputs = useQuery({ queryKey: ['depot-inputs', planId, date, scenario], queryFn: () => api.depotInputs(planId, date, scenario), enabled: Boolean(planId && date), staleTime: 0 })
  const error = inputs.error || plan.error || bootstrap.error
  if (error) return <ErrorState title="Could not load depot inputs" error={error} />
  if (!inputs.data || !data) return <div role="status" className="flex items-center justify-center gap-2 p-10"><Loader2 className="h-4 w-4 animate-spin" />Loading depot inputs…</div>
  const orders = new Map(inputs.data.orders.map(row => [String(row.customer_id), row]))
  const deliveries = inputs.data.deliveries.map(row => ({ ...row, ...orders.get(String(row.customer_id)) }))
  return <div className="space-y-5 p-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-lg font-semibold">{data.depot.name} · Inputs</h1><p className="text-sm text-muted-foreground">Saved depot inputs and submitted scenario changes for {date}. Edit changes in <Link to={`/scenario?${params.toString()}`} className="underline">Scenarios</Link>.</p></div>
      <select aria-label="Inputs scenario" value={scenario} onChange={event => { const next = new URLSearchParams(params); next.set('routePlanScenario', event.target.value); setParams(next) }} className="rounded-md border border-border bg-background p-2">{data.scenarios.map(row => <option key={row.route_scenario_id} value={row.route_scenario_id}>{row.scenario_name}</option>)}</select>
    </div>
    <p className="text-xs text-muted-foreground">Source network run: {inputs.data.parent_run_id} · Costs: {inputs.data.cost_source}{inputs.data.override_status && ` · Scenario status: ${inputs.data.override_status}`}</p>
    <InputTable title="Deliveries" rows={deliveries} columns={['customer_name', 'customer_id', 'demand_cases', 'lat', 'lng', 'receiving_window_start', 'receiving_window_end', 'service_minutes']} />
    <InputTable title="Available fleet" rows={inputs.data.fleet} columns={['vehicle_id', 'capacity_cases', 'max_route_minutes', 'max_stops_per_route', 'available_dates']} />
    <InputTable title="Cost parameters" rows={Object.entries(inputs.data.cost_parameters).map(([parameter, value]) => ({ parameter, value }))} columns={['parameter', 'value']} />
  </div>
}
function InputTable({ title, rows, columns }: { title: string; rows: Array<Record<string, unknown>>; columns: string[] }) {
  return <section><h2 className="mb-2 font-semibold">{title} ({rows.length})</h2><div className="max-h-[400px] overflow-auto rounded-md border border-border"><table className="w-full text-left text-xs"><thead className="sticky top-0 bg-card"><tr>{columns.map(key => <th key={key} className="whitespace-nowrap p-3">{key.replaceAll('_', ' ')}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-t border-border">{columns.map(key => <td key={key} className="p-3">{row[key] == null ? '—' : Array.isArray(row[key]) ? row[key].join(', ') : String(row[key])}</td>)}</tr>)}</tbody></table></div></section>
}
