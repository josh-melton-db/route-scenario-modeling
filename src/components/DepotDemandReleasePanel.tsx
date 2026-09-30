import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'

export default function DepotDemandReleasePanel({ runId, planSetId, depotId, routeScenarioId, serviceDate }: {
  runId: string; planSetId: string; depotId: string; routeScenarioId: string; serviceDate: string
}) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const [customerId, setCustomerId] = useState('')
  const [cases, setCases] = useState('')
  const changes = useQuery({ queryKey: ['network-demand-changes', runId], queryFn: () => api.networkDemandChanges(runId) })
  const targets = useQuery({ queryKey: ['network-release-targets', runId, depotId, serviceDate], queryFn: () => api.networkReleaseTargets(runId, depotId, serviceDate) })
  const customers = targets.data ?? []
  const selected = customers.find((customer) => customer.customer_id === customerId)
  const pending = (changes.data ?? []).filter((change) => change.status === 'pending')
  const release = useMutation({
    mutationFn: () => api.releaseNetworkDemand(runId, {
      kind: 'release', depot_plan_id: planSetId, route_scenario_id: routeScenarioId,
      service_date: serviceDate, customer_id: customerId, cases: Number(cases),
    }),
    onSuccess: async () => {
      setCases('')
      await client.invalidateQueries({ queryKey: ['network-demand-changes', runId] })
    },
  })
  const rerun = useMutation({
    mutationFn: () => api.reassignNetworkDemand(runId),
    onSuccess: async (response) => {
      await client.invalidateQueries({ queryKey: ['network-demand-changes', runId] })
      await client.invalidateQueries({ queryKey: ['network-scenarios'] })
      const run = response.result.run_id
      navigate(`/network/scenarios/${encodeURIComponent(response.scenario.scenario_id)}/flow${run ? `?run=${encodeURIComponent(run)}` : ''}`)
    },
  })
  const busy = release.isPending || rerun.isPending
  return (
    <section aria-label="Release for reassignment" className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">Release for reassignment</h2>
      <p className="mt-1 text-xs text-muted-foreground">Propose that another eligible depot serves these cases on {serviceDate}. Required demand is preserved. This plan and its routes remain unchanged until a new parent network run is created.</p>
      {targets.isLoading && <p className="mt-2 text-xs text-muted-foreground">Loading assigned deliveries, including route-unserved cases…</p>}
      {!targets.isLoading && !targets.error && customers.length === 0 && <p className="mt-2 text-xs text-muted-foreground">There are no assigned deliveries to release on this date.</p>}
      {routeScenarioId === 'default' ? <p className="mt-2 text-xs text-muted-foreground">Select a named route scenario to propose a release.</p> : (
        <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); release.mutate() }}>
          <label className="text-xs">Customer
            <select aria-label="Release customer" value={customerId} onChange={(event) => { setCustomerId(event.target.value); setCases('') }} className="mt-1 block h-9 rounded-md border border-border bg-background px-2 text-sm">
              <option value="">Select a delivery</option>
              {customers.map((customer) => <option key={customer.customer_id} value={customer.customer_id}>{customer.customer_name}</option>)}
            </select>
          </label>
          <label className="text-xs">Cases
            <input aria-label="Release cases" type="number" min="1" max={selected?.assigned_cases} step="1" required value={cases} onChange={(event) => setCases(event.target.value)} className="mt-1 block h-9 w-28 rounded-md border border-border bg-background px-2 text-sm" />
          </label>
          <button disabled={busy || !selected || !Number.isInteger(Number(cases)) || Number(cases) <= 0 || Number(cases) > selected.assigned_cases} className="h-9 rounded-md border border-border px-3 text-sm disabled:opacity-50">Propose release</button>
        </form>
      )}
      {pending.length > 0 && <div className="mt-3 text-xs">
        <p>{pending.length} pending release{pending.length === 1 ? '' : 's'} · {pending.reduce((sum, change) => sum + change.cases, 0).toLocaleString()} cases across this parent run</p>
        <ul className="mt-1 space-y-1">{pending.map((change) => <li key={change.change_id}>{change.service_date} · {change.customer_id} · {change.cases.toLocaleString()} cases</li>)}</ul>
        <button type="button" onClick={() => rerun.mutate()} disabled={busy} className="mt-2 rounded-md bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50">Rerun network with releases</button>
        <p className="mt-1 text-muted-foreground">Creates a new network run. Cases without feasible eligible capacity remain explicitly unmet.</p>
      </div>}
      {(release.error || rerun.error || changes.error || targets.error) && <p role="alert" className="mt-2 text-xs text-destructive">{String(release.error || rerun.error || changes.error || targets.error)}</p>}
    </section>
  )
}
