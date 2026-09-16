import { Link, useParams, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Loader2 } from 'lucide-react'
import ConstraintViolationsTable from '@/components/ConstraintViolationsTable'
import CostBreakdown from '@/components/CostBreakdown'
import CustomerImpactTable from '@/components/CustomerImpactTable'
import DualMap from '@/components/DualMap'
import ErrorState from '@/components/ErrorState'
import KpiDeltaGrid from '@/components/KpiDeltaGrid'
import TransportationAllocation from '@/components/TransportationAllocation'
import { useScenarioResults } from '@/api/queries'
import type { KpiDeltas, Kpis } from '@/api/types'

export default function ComparisonPage() {
  const { scenarioId } = useParams()
  const [searchParams] = useSearchParams()
  const baselineId = searchParams.get('baselineId') ?? 'baseline'
  const result = useScenarioResults(scenarioId)
  const selectedBaseline = useScenarioResults(
    baselineId === 'baseline' ? undefined : baselineId,
  )

  if (result.error || selectedBaseline.error) {
    return <ErrorState title="Could not load comparison" error={result.error ?? selectedBaseline.error} />
  }

  if (result.isLoading || !result.data || selectedBaseline.isLoading) {
    return (
      <div className="flex h-96 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading comparison...
      </div>
    )
  }

  const comparison = result.data
  const customBaseline = selectedBaseline.data
  const baselineName = customBaseline?.scenario_name ?? 'Baseline'
  const baselineDepot = customBaseline?.scenario_depot ?? comparison.baseline_depot
  const baselineRoutes = customBaseline?.scenario_routes ?? comparison.baseline_routes
  const baselineKpis = customBaseline?.scenario_kpis ?? comparison.baseline_kpis
  const deltas = comparison.scenario_kpis
    ? calculateKpiDeltas(baselineKpis, comparison.scenario_kpis)
    : comparison.kpi_deltas
  const infeasible = comparison.status === 'infeasible'

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {baselineName} vs. {comparison.scenario_name}
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            {comparison.summary}
          </p>
        </div>
        <Link
          to="/scenario"
          className="rounded-md border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          New scenario
        </Link>
      </header>

      {infeasible && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div>
            <div className="font-semibold">Scenario is infeasible</div>
            <p className="mt-1 text-amber-100/80">
              Review the constraint diagnostics below before changing route, depot, or service-window assumptions.
            </p>
          </div>
        </div>
      )}

      <KpiDeltaGrid
        baselineKpis={baselineKpis}
        scenarioKpis={comparison.scenario_kpis}
        deltas={deltas}
      />

      <DualMap
        baselineDepot={baselineDepot}
        scenarioDepot={comparison.scenario_depot}
        baselineRoutes={baselineRoutes}
        scenarioRoutes={comparison.scenario_routes}
        status={comparison.status}
        baselineLabel={baselineName}
        scenarioLabel={comparison.scenario_name}
      />

      <TransportationAllocation
        allocations={comparison.transportation_allocation ?? []}
        decisions={comparison.decision_explanations ?? []}
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <CustomerImpactTable impacts={comparison.customer_impacts} />
        <CostBreakdown
          costs={
            comparison.scenario_kpis?.cost_breakdown ??
            comparison.baseline_kpis.cost_breakdown
          }
        />
      </div>

      <ConstraintViolationsTable violations={comparison.constraint_violations} />
    </div>
  )
}

function calculateKpiDeltas(baseline: Kpis, scenario: Kpis): KpiDeltas {
  return {
    route_count: scenario.route_count - baseline.route_count,
    driver_count: scenario.driver_count - baseline.driver_count,
    vehicle_count: scenario.vehicle_count - baseline.vehicle_count,
    total_miles: scenario.total_miles - baseline.total_miles,
    drive_minutes: scenario.drive_minutes - baseline.drive_minutes,
    service_minutes: scenario.service_minutes - baseline.service_minutes,
    total_cases: scenario.total_cases - baseline.total_cases,
    avg_stops_per_route: scenario.avg_stops_per_route - baseline.avg_stops_per_route,
    avg_capacity_utilization_pct: scenario.avg_capacity_utilization_pct - baseline.avg_capacity_utilization_pct,
    avg_driver_utilization_pct: scenario.avg_driver_utilization_pct - baseline.avg_driver_utilization_pct,
    overtime_minutes: scenario.overtime_minutes - baseline.overtime_minutes,
    missed_windows: scenario.missed_windows - baseline.missed_windows,
    late_minutes: scenario.late_minutes - baseline.late_minutes,
    total_revenue: scenario.total_revenue - baseline.total_revenue,
    profit: scenario.profit - baseline.profit,
    mileage_cost: scenario.cost_breakdown.mileage_cost - baseline.cost_breakdown.mileage_cost,
    labor_cost: scenario.cost_breakdown.labor_cost - baseline.cost_breakdown.labor_cost,
    overtime_cost: scenario.cost_breakdown.overtime_cost - baseline.cost_breakdown.overtime_cost,
    fixed_vehicle_cost: scenario.cost_breakdown.fixed_vehicle_cost - baseline.cost_breakdown.fixed_vehicle_cost,
    sla_penalty_cost: scenario.cost_breakdown.sla_penalty_cost - baseline.cost_breakdown.sla_penalty_cost,
    carrier_linehaul_cost: (scenario.cost_breakdown.carrier_linehaul_cost ?? 0) - (baseline.cost_breakdown.carrier_linehaul_cost ?? 0),
    carrier_stop_cost: (scenario.cost_breakdown.carrier_stop_cost ?? 0) - (baseline.cost_breakdown.carrier_stop_cost ?? 0),
    fuel_surcharge_cost: (scenario.cost_breakdown.fuel_surcharge_cost ?? 0) - (baseline.cost_breakdown.fuel_surcharge_cost ?? 0),
    total_cost: scenario.cost_breakdown.total_cost - baseline.cost_breakdown.total_cost,
  }
}
