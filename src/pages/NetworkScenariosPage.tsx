import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Loader2, Plus, Trash2, Workflow } from 'lucide-react'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import {
  useCreateNetworkScenario,
  useDeleteNetworkScenario,
  useNetworkOptions,
  useNetworkScenarios,
} from '@/api/queries'
import type { NetworkScenario, NetworkScenarioStatus } from '@/api/types'
import { cn } from '@/lib/utils'

const STATUS_LABELS: Record<NetworkScenarioStatus, string> = {
  draft: 'Draft',
  validated: 'Validated',
  solving: 'Solving',
  solved: 'Solved',
  infeasible: 'Infeasible',
  failed: 'Failed',
  depot_plans_running: 'Depot plans running',
  reconciliation_required: 'Reconciliation required',
  reconciled: 'Reconciled',
  published: 'Published',
}

export default function NetworkScenariosPage() {
  const navigate = useNavigate()
  const options = useNetworkOptions()
  const scenarios = useNetworkScenarios()
  const createScenario = useCreateNetworkScenario()
  const deleteScenario = useDeleteNetworkScenario()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)

  if (options.error) {
    return <ErrorState title="Could not load network options" error={options.error} />
  }
  if (options.isLoading || !options.data) {
    return (
      <div className="flex h-96 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading network scenarios...
      </div>
    )
  }

  async function handleCreate() {
    setError(null)
    const trimmed = name.trim()
    if (!trimmed || !options.data) return
    try {
      const created = await createScenario.mutateAsync({
        scenario_name: trimmed,
        demand_plan_version_id: options.data.default_demand_plan_version_id,
        capacity_plan_version_id: options.data.default_capacity_plan_version_id,
        horizon_start: options.data.default_horizon_start,
        horizon_end: options.data.default_horizon_end,
        region_id: options.data.default_region_id,
      })
      setName('')
      navigate(`/network/scenarios/${created.scenario_id}/scenario`)
    } catch (err) {
      setError(String(err))
    }
  }

  async function handleDelete(scenario: NetworkScenario) {
    if (scenario.status === 'published') return
    if (
      !window.confirm(
        `Delete "${scenario.scenario_name}"? This cannot be undone.`,
      )
    ) {
      return
    }
    setError(null)
    try {
      await deleteScenario.mutateAsync(scenario.scenario_id)
    } catch (err) {
      setError(String(err))
    }
  }

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">Network scenarios</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Coordinated what-if plans across distribution centers, solved against
            fixed published capacity. Demand and capacity are consumed, never
            invented.
          </p>
        </div>
        <Link
          to="/network"
          className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-accent/50"
        >
          <Workflow className="h-4 w-4" />
          Back to overview
        </Link>
      </div>

      <section className="rounded-lg border border-border bg-card p-4">
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-medium">New scenario name</span>
          <div className="flex flex-wrap gap-2">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Southeast capacity relief"
              className="h-10 min-w-64 flex-1 rounded-md border border-border bg-background px-3 text-sm"
              onKeyDown={(event) => {
                if (event.key === 'Enter') void handleCreate()
              }}
            />
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={!name.trim() || createScenario.isPending}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              {createScenario.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Create scenario
            </button>
          </div>
          <span className="text-xs text-muted-foreground">
            Starts from the published plans and region shown in the network
            overview; assumptions are edited on the scenario page.
          </span>
        </label>
        {error && (
          <div className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}
      </section>

      {scenarios.error && (
        <ErrorState title="Could not load scenarios" error={scenarios.error} />
      )}

      {scenarios.isLoading ? (
        <div className="flex h-40 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading scenarios...
        </div>
      ) : !scenarios.data?.length ? (
        <EmptyState
          title="No network scenarios yet"
          description="Create your first coordinated plan above."
        />
      ) : (
        <section className="overflow-hidden rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/70 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2.5 font-medium">Scenario</th>
                <th className="px-4 py-2.5 font-medium">Region</th>
                <th className="px-4 py-2.5 font-medium">Horizon</th>
                <th className="px-4 py-2.5 font-medium">Revision</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {scenarios.data.map((scenario) => (
                <tr key={scenario.scenario_id} className="hover:bg-accent/40">
                  <td className="px-4 py-3">
                    <Link
                      to={`/network/scenarios/${scenario.scenario_id}/scenario`}
                      className="font-medium text-primary hover:underline"
                    >
                      {scenario.scenario_name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {regionLabel(options.data?.regions, scenario.region_id)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground tabular-nums">
                    {scenario.horizon_start} → {scenario.horizon_end}
                  </td>
                  <td className="px-4 py-3 tabular-nums">{scenario.revision}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={scenario.status} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => void handleDelete(scenario)}
                      disabled={scenario.status === 'published' || deleteScenario.isPending}
                      className="inline-flex items-center gap-1 rounded-md border border-destructive/50 px-2 py-1 text-xs font-medium text-destructive hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}

function regionLabel(
  regions: { region_id: string; region_name: string }[] | undefined,
  regionId: string,
) {
  if (regionId === 'ALL') return 'All regions'
  return regions?.find((row) => row.region_id === regionId)?.region_name ?? regionId
}

function StatusBadge({ status }: { status: NetworkScenarioStatus }) {
  const terminal = status === 'solved' || status === 'published'
  const failed = status === 'infeasible' || status === 'failed'
  return (
    <span
      className={cn(
        'rounded-full px-2 py-0.5 text-[10px] font-medium',
        terminal
          ? 'bg-primary/15 text-primary'
          : failed
            ? 'bg-destructive/10 text-destructive'
            : status === 'validated'
              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
              : 'bg-muted text-muted-foreground',
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  )
}
