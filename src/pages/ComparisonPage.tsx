import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, Loader2 } from 'lucide-react'
import ConstraintViolationsTable from '@/components/ConstraintViolationsTable'
import CostBreakdown from '@/components/CostBreakdown'
import CustomerImpactTable from '@/components/CustomerImpactTable'
import DualMap from '@/components/DualMap'
import ErrorState from '@/components/ErrorState'
import KpiDeltaGrid from '@/components/KpiDeltaGrid'
import { useScenarioResults } from '@/api/queries'

export default function ComparisonPage() {
  const { scenarioId } = useParams()
  const result = useScenarioResults(scenarioId)

  if (result.error) {
    return <ErrorState title="Could not load comparison" error={result.error} />
  }

  if (result.isLoading || !result.data) {
    return (
      <div className="flex h-96 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading comparison...
      </div>
    )
  }

  const comparison = result.data
  const infeasible = comparison.status === 'infeasible'

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {comparison.scenario_name}
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
        baselineKpis={comparison.baseline_kpis}
        scenarioKpis={comparison.scenario_kpis}
        deltas={comparison.kpi_deltas}
      />

      <DualMap
        baselineDepot={comparison.baseline_depot}
        scenarioDepot={comparison.scenario_depot}
        baselineRoutes={comparison.baseline_routes}
        scenarioRoutes={comparison.scenario_routes}
        status={comparison.status}
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
