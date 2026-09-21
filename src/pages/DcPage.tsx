import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Building2, ExternalLink, Loader2 } from 'lucide-react'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import KpiCard from '@/components/KpiCard'
import { useNetworkOptions, useNetworkOverview } from '@/api/queries'
import type { NetworkOverviewParams } from '@/api/types'
import { formatCurrency, formatNumber, formatPercent } from '@/lib/format'

export default function DcPage() {
  const { facilityId = '' } = useParams()
  const options = useNetworkOptions()

  const context = useMemo<NetworkOverviewParams | null>(
    () =>
      options.data
        ? {
            demand_plan_version_id: options.data.default_demand_plan_version_id,
            capacity_plan_version_id: options.data.default_capacity_plan_version_id,
            horizon_start: options.data.default_horizon_start,
            horizon_end: options.data.default_horizon_end,
            region_id: 'ALL',
            lane_type: 'LINEHAUL',
            metric: 'assigned_flow',
          }
        : null,
    [options.data],
  )
  const overview = useNetworkOverview(context)

  if (options.error) {
    return <ErrorState title="Could not load network options" error={options.error} />
  }
  if (overview.error) {
    return <ErrorState title="Could not load the network overview" error={overview.error} />
  }
  if (options.isLoading || overview.isLoading || !overview.data) {
    return (
      <div className="flex h-96 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading distribution center...
      </div>
    )
  }

  const dc = overview.data.facilities.find(
    (row) => row.facility_id === facilityId && row.facility_type === 'distribution_center',
  )
  const depots = overview.data.facilities.filter(
    (row) => row.parent_facility_id === facilityId,
  )
  if (!dc) {
    return (
      <EmptyState
        title="Distribution center not found"
        description="This facility does not exist in the current network context."
        action={{ label: 'Back to network', onClick: () => window.history.back() }}
      />
    )
  }

  const serviceDate = firstTuesday(overview.data.context.horizon_start, overview.data.context.horizon_end)
  const dcUnmet = Math.max(0, dc.demand_units - dc.assigned_units)
  const connectedLanes = overview.data.lanes
    .filter(
      (lane) =>
        lane.origin_endpoint_id === facilityId || lane.destination_endpoint_id === facilityId,
    )
    .sort((a, b) => b.assigned_units - a.assigned_units)
    .slice(0, 8)

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header>
        <Link
          to="/network"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Network overview
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="rounded-md bg-primary/15 p-2 text-primary">
            <Building2 className="h-4 w-4" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">{dc.facility_name}</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {dc.region_id.replaceAll('_', ' ').toLowerCase()} · serving {depots.length} depots ·{' '}
          {overview.data.context.horizon_start} → {overview.data.context.horizon_end}
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <KpiCard label="Depot demand" value={formatNumber(dc.demand_units)} />
        <KpiCard label="Assigned flow" value={formatNumber(dc.assigned_units)} />
        <KpiCard
          label="Unmet demand"
          value={formatNumber(dcUnmet)}
          tone={dcUnmet > 0 ? 'bad' : 'good'}
        />
        <KpiCard label="Supplied capacity" value={formatNumber(dc.capacity_units)} />
        <KpiCard label="Modeled cost" value={formatCurrency(dc.total_cost)} />
        <KpiCard label="On-time outlook" value={formatPercent(dc.on_time_pct)} />
      </div>

      <section className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="border-b border-border/70 px-4 py-2.5 text-sm font-medium">
          Depots served by this distribution center
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/70 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2 font-medium">Depot</th>
                <th className="px-4 py-2 text-right font-medium">Demand</th>
                <th className="px-4 py-2 text-right font-medium">Assigned</th>
                <th className="px-4 py-2 text-right font-medium">Unmet</th>
                <th className="px-4 py-2 text-right font-medium">Utilization</th>
                <th className="px-4 py-2 text-right font-medium">Cost</th>
                <th className="px-4 py-2 text-right font-medium">Analyze</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {depots.map((depot) => {
                const unmet = Math.max(0, depot.demand_units - depot.assigned_units)
                return (
                  <tr key={depot.facility_id} className="hover:bg-accent/40">
                    <td className="px-4 py-2.5 font-medium">{depot.facility_name}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatNumber(depot.demand_units)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatNumber(depot.assigned_units)}
                    </td>
                    <td
                      className={`px-4 py-2.5 text-right tabular-nums ${
                        unmet > 0 ? 'font-semibold text-destructive' : 'text-muted-foreground'
                      }`}
                    >
                      {formatNumber(unmet)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatPercent(depot.utilization_pct)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatCurrency(depot.total_cost)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Link
                        to={`/analyze?depot=${encodeURIComponent(depot.facility_id)}&date=${serviceDate}&networkReturn=${encodeURIComponent(`/dc/${facilityId}`)}`}
                        className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium hover:bg-accent/50"
                      >
                        Depot routes <ExternalLink className="h-3 w-3" />
                      </Link>
                    </td>
                  </tr>
                )
              })}
              {!depots.length && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                    No depots are parented to this distribution center.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {connectedLanes.length > 0 && (
        <section className="overflow-hidden rounded-lg border border-border bg-card">
          <div className="border-b border-border/70 px-4 py-2.5 text-sm font-medium">
            Busiest linehaul lanes touching this distribution center
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/70 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Lane</th>
                  <th className="px-4 py-2 text-right font-medium">Assigned cases</th>
                  <th className="px-4 py-2 text-right font-medium">Utilization</th>
                  <th className="px-4 py-2 text-right font-medium">Modeled cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {connectedLanes.map((lane) => (
                  <tr key={lane.lane_id} className="hover:bg-accent/40">
                    <td className="max-w-96 truncate px-4 py-2.5" title={lane.lane_name}>
                      {lane.lane_name}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatNumber(lane.assigned_units)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatPercent(lane.utilization_pct)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatCurrency(lane.total_cost)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

function firstTuesday(start: string, end: string) {
  const current = new Date(`${start}T12:00:00`)
  const final = new Date(`${end}T12:00:00`)
  while (current <= final) {
    if (current.getDay() === 2) return current.toISOString().slice(0, 10)
    current.setDate(current.getDate() + 1)
  }
  return start
}
