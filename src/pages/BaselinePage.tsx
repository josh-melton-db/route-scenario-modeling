import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import type { KpiDeltas, Kpis } from '@/api/types'
import CarrierCostAnalysis from '@/components/CarrierCostAnalysis'
import CostBreakdown from '@/components/CostBreakdown'
import CustomerImpactTable from '@/components/CustomerImpactTable'
import DepotDayFilter from '@/components/DepotDayFilter'
import DualMap from '@/components/DualMap'
import ErrorState from '@/components/ErrorState'
import KpiDeltaGrid from '@/components/KpiDeltaGrid'
import MapView from '@/components/MapView'
import RouteSidebar from '@/components/RouteSidebar'
import ScenarioCombobox from '@/components/ScenarioCombobox'
import TransportationAllocation from '@/components/TransportationAllocation'
import {
  useBaselineKpis,
  useBaselineNetwork,
  useDays,
  useDepots,
  useRecentScenarios,
  useScenarioResults,
} from '@/api/queries'

export default function BaselinePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [depotId, setDepotId] = useState(
    () => searchParams.get('depot') || 'DPT_NORTH',
  )
  const [deliveryDay, setDeliveryDay] = useState(
    () =>
      searchParams.get('day') ||
      deliveryDayFromDate(searchParams.get('date')) ||
      'Tuesday',
  )
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const primaryScenarioId = searchParams.get('primary') || 'baseline'
  const comparisonScenarioId = searchParams.get('compare') || ''

  function updateSelection(primary: string, comparison: string) {
    const next = new URLSearchParams(searchParams)
    if (primary !== 'baseline') next.set('primary', primary)
    else next.delete('primary')
    if (comparison) next.set('compare', comparison)
    else next.delete('compare')
    setSearchParams(next, { replace: true })
  }

  const depots = useDepots()
  const days = useDays()
  const network = useBaselineNetwork(depotId, deliveryDay)
  const kpis = useBaselineKpis(depotId, deliveryDay)
  const scenarios = useRecentScenarios(50)
  const primaryResult = useScenarioResults(
    primaryScenarioId === 'baseline' ? undefined : primaryScenarioId,
  )
  const comparisonResult = useScenarioResults(
    comparisonScenarioId && comparisonScenarioId !== 'baseline'
      ? comparisonScenarioId
      : undefined,
  )
  const error =
    depots.error ?? days.error ?? network.error ?? kpis.error ?? scenarios.error ??
    primaryResult.error ?? comparisonResult.error

  if (error) return <ErrorState title="Could not load analysis" error={error} />

  const loading =
    depots.isLoading || days.isLoading || network.isLoading || kpis.isLoading

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      {safeNetworkReturn(searchParams.get('networkReturn')) && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-primary/30 bg-primary/5 px-3 py-2">
          <Link
            to={safeNetworkReturn(searchParams.get('networkReturn')) as string}
            className="inline-flex items-center gap-2 text-xs font-medium text-primary hover:underline"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Back to network baseline
          </Link>
          <span className="text-xs text-muted-foreground">
            Depot analysis · supplied by network plan
          </span>
        </div>
      )}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <ScenarioCombobox
            label="Scenario 1"
            value={primaryScenarioId}
            scenarios={scenarios.data ?? []}
            includeBaseline
            onChange={(scenarioId) => {
              updateSelection(
                scenarioId,
                scenarioId === comparisonScenarioId ? '' : comparisonScenarioId,
              )
            }}
          />
          <ScenarioCombobox
            label="Scenario 2"
            value={comparisonScenarioId}
            scenarios={scenarios.data ?? []}
            includeBaseline
            allowClear
            excludedScenarioId={primaryScenarioId}
            onChange={(scenarioId) => updateSelection(primaryScenarioId, scenarioId)}
          />
        </div>
        <DepotDayFilter
          depots={depots.data ?? []}
          days={days.data ?? []}
          depotId={depotId}
          deliveryDay={deliveryDay}
          onChange={(nextDepot, nextDay) => {
            setDepotId(nextDepot)
            setDeliveryDay(nextDay)
            setSelectedRouteId(null)
            const next = new URLSearchParams(searchParams)
            next.set('depot', nextDepot)
            next.set('day', nextDay)
            next.delete('date')
            setSearchParams(next, { replace: true })
          }}
        />
      </div>

      {loading || !network.data || !kpis.data || primaryResult.isLoading || comparisonResult.isLoading ? (
        <div className="flex h-96 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading analysis...
        </div>
      ) : (
        <>
          {comparisonScenarioId === 'baseline' && primaryResult.data ? (
            <>
              <KpiDeltaGrid
                baselineKpis={primaryResult.data.scenario_kpis ?? primaryResult.data.baseline_kpis}
                scenarioKpis={kpis.data}
                deltas={calculateKpiDeltas(
                  primaryResult.data.scenario_kpis ?? primaryResult.data.baseline_kpis,
                  kpis.data,
                )}
              />
              <DualMap
                baselineDepot={primaryResult.data.scenario_depot}
                scenarioDepot={network.data.depot}
                baselineRoutes={primaryResult.data.scenario_routes}
                scenarioRoutes={network.data.routes}
                status="succeeded"
                baselineLabel={primaryResult.data.scenario_name}
                scenarioLabel="Baseline"
              />
              <TransportationAllocation
                allocations={primaryResult.data.transportation_allocation ?? []}
                decisions={primaryResult.data.decision_explanations ?? []}
              />
              <CarrierCostAnalysis
                routes={primaryResult.data.scenario_routes}
                generatedAt={primaryResult.data.generated_at}
              />
              <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
                <CustomerImpactTable impacts={primaryResult.data.customer_impacts} />
                <CostBreakdown costs={kpis.data.cost_breakdown} />
              </div>
            </>
          ) : comparisonScenarioId && comparisonResult.data ? (
            <>
              <KpiDeltaGrid
                baselineKpis={primaryResult.data?.scenario_kpis ?? comparisonResult.data.baseline_kpis}
                scenarioKpis={comparisonResult.data.scenario_kpis}
                deltas={
                  comparisonResult.data.scenario_kpis
                    ? calculateKpiDeltas(
                        primaryResult.data?.scenario_kpis ?? comparisonResult.data.baseline_kpis,
                        comparisonResult.data.scenario_kpis,
                      )
                    : comparisonResult.data.kpi_deltas
                }
              />
              <DualMap
                baselineDepot={primaryResult.data?.scenario_depot ?? comparisonResult.data.baseline_depot}
                scenarioDepot={comparisonResult.data.scenario_depot}
                baselineRoutes={primaryResult.data?.scenario_routes ?? comparisonResult.data.baseline_routes}
                scenarioRoutes={comparisonResult.data.scenario_routes}
                status={comparisonResult.data.status}
                baselineLabel={scenarioName(primaryScenarioId, scenarios.data ?? [])}
                scenarioLabel={comparisonResult.data.scenario_name}
              />
              <TransportationAllocation
                allocations={comparisonResult.data.transportation_allocation ?? []}
                decisions={comparisonResult.data.decision_explanations ?? []}
              />
              <CarrierCostAnalysis
                routes={comparisonResult.data.scenario_routes}
                generatedAt={comparisonResult.data.generated_at}
              />
              <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
                <CustomerImpactTable impacts={comparisonResult.data.customer_impacts} />
                <CostBreakdown
                  costs={
                    comparisonResult.data.scenario_kpis?.cost_breakdown ??
                    comparisonResult.data.baseline_kpis.cost_breakdown
                  }
                />
              </div>
            </>
          ) : primaryScenarioId !== 'baseline' && primaryResult.data ? (
            <>
              <KpiDeltaGrid
                baselineKpis={primaryResult.data.baseline_kpis}
                scenarioKpis={primaryResult.data.scenario_kpis}
                deltas={primaryResult.data.kpi_deltas}
              />
              <DualMap
                baselineDepot={primaryResult.data.baseline_depot}
                scenarioDepot={primaryResult.data.scenario_depot}
                baselineRoutes={primaryResult.data.baseline_routes}
                scenarioRoutes={primaryResult.data.scenario_routes}
                status={primaryResult.data.status}
                scenarioLabel={primaryResult.data.scenario_name}
              />
              <TransportationAllocation
                allocations={primaryResult.data.transportation_allocation ?? []}
                decisions={primaryResult.data.decision_explanations ?? []}
              />
              <CarrierCostAnalysis
                routes={primaryResult.data.scenario_routes}
                generatedAt={primaryResult.data.generated_at}
              />
              <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
                <CustomerImpactTable impacts={primaryResult.data.customer_impacts} />
                <CostBreakdown costs={(primaryResult.data.scenario_kpis ?? primaryResult.data.baseline_kpis).cost_breakdown} />
              </div>
            </>
          ) : (
            <>
              <KpiDeltaGrid baselineKpis={kpis.data} />
              <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
                <div className="min-h-[620px]">
                  <div className="flex h-[620px] min-h-0 overflow-hidden rounded-lg border border-border">
                    <RouteSidebar
                      routes={network.data.routes}
                      selectedRouteId={selectedRouteId}
                      onSelectRoute={setSelectedRouteId}
                      title="Baseline routes"
                    />
                    <div className="min-w-0 flex-1 p-3">
                      <MapView
                        depot={network.data.depot}
                        routes={network.data.routes}
                        selectedRouteId={selectedRouteId}
                        onSelectRoute={setSelectedRouteId}
                      />
                    </div>
                  </div>
                </div>
                <CostBreakdown costs={kpis.data.cost_breakdown} />
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}

function deliveryDayFromDate(value: string | null) {
  if (!value) return null
  const parsed = new Date(`${value}T12:00:00`)
  if (Number.isNaN(parsed.valueOf())) return null
  return parsed.toLocaleDateString('en-US', { weekday: 'long' })
}

function safeNetworkReturn(value: string | null) {
  return value?.startsWith('/network') || value?.startsWith('/dc/')
    ? value
    : null
}

function scenarioName(id: string, scenarios: { scenario_id: string; scenario_name: string }[]) {
  return id === 'baseline'
    ? 'Baseline'
    : scenarios.find((scenario) => scenario.scenario_id === id)?.scenario_name ?? 'Scenario 1'
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
    carrier_lane_cost: (scenario.cost_breakdown.carrier_lane_cost ?? 0) - (baseline.cost_breakdown.carrier_lane_cost ?? 0),
    carrier_stop_cost: (scenario.cost_breakdown.carrier_stop_cost ?? 0) - (baseline.cost_breakdown.carrier_stop_cost ?? 0),
    carrier_minimum_adjustment: (scenario.cost_breakdown.carrier_minimum_adjustment ?? 0) - (baseline.cost_breakdown.carrier_minimum_adjustment ?? 0),
    fuel_surcharge_cost: (scenario.cost_breakdown.fuel_surcharge_cost ?? 0) - (baseline.cost_breakdown.fuel_surcharge_cost ?? 0),
    accessorial_cost: (scenario.cost_breakdown.accessorial_cost ?? 0) - (baseline.cost_breakdown.accessorial_cost ?? 0),
    volume_tier_adjustment: (scenario.cost_breakdown.volume_tier_adjustment ?? 0) - (baseline.cost_breakdown.volume_tier_adjustment ?? 0),
    commitment_adjustment: (scenario.cost_breakdown.commitment_adjustment ?? 0) - (baseline.cost_breakdown.commitment_adjustment ?? 0),
    total_cost: scenario.cost_breakdown.total_cost - baseline.cost_breakdown.total_cost,
  }
}
