import type { KpiDeltas, Kpis } from '@/api/types'
import { deltaTone } from '@/lib/deltas'
import {
  formatCurrency,
  formatDelta,
  formatMinutes,
  formatNumber,
  formatPercent,
} from '@/lib/format'
import KpiCard from './KpiCard'

interface MetricConfig {
  key: keyof KpiDeltas
  label: string
  value: (kpis: Kpis) => string
  deltaSuffix?: string
}

const metrics: MetricConfig[] = [
  { key: 'route_count', label: 'Routes', value: (k) => formatNumber(k.route_count) },
  { key: 'driver_count', label: 'Drivers', value: (k) => formatNumber(k.driver_count) },
  { key: 'vehicle_count', label: 'Vehicles', value: (k) => formatNumber(k.vehicle_count) },
  { key: 'total_miles', label: 'Total miles', value: (k) => formatNumber(k.total_miles, 1), deltaSuffix: ' mi' },
  { key: 'drive_minutes', label: 'Drive time', value: (k) => formatMinutes(k.drive_minutes), deltaSuffix: 'm' },
  { key: 'service_minutes', label: 'Service time', value: (k) => formatMinutes(k.service_minutes), deltaSuffix: 'm' },
  { key: 'total_cases', label: 'Cases', value: (k) => formatNumber(k.total_cases) },
  { key: 'avg_stops_per_route', label: 'Avg stops / route', value: (k) => formatNumber(k.avg_stops_per_route, 1) },
  { key: 'avg_capacity_utilization_pct', label: 'Capacity util.', value: (k) => formatPercent(k.avg_capacity_utilization_pct), deltaSuffix: ' pts' },
  { key: 'avg_driver_utilization_pct', label: 'Driver util.', value: (k) => formatPercent(k.avg_driver_utilization_pct), deltaSuffix: ' pts' },
  { key: 'overtime_minutes', label: 'Overtime', value: (k) => formatMinutes(k.overtime_minutes), deltaSuffix: 'm' },
  { key: 'missed_windows', label: 'Missed windows', value: (k) => formatNumber(k.missed_windows) },
  { key: 'late_minutes', label: 'Late minutes', value: (k) => formatMinutes(k.late_minutes), deltaSuffix: 'm' },
  { key: 'total_cost', label: 'Total cost', value: (k) => formatCurrency(k.cost_breakdown.total_cost) },
]

interface KpiDeltaGridProps {
  baselineKpis: Kpis
  scenarioKpis?: Kpis | null
  deltas?: KpiDeltas | null
}

export default function KpiDeltaGrid({
  baselineKpis,
  scenarioKpis,
  deltas,
}: KpiDeltaGridProps) {
  const activeKpis = scenarioKpis ?? baselineKpis
  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
      {metrics.map((metric) => {
        const deltaValue = deltas?.[metric.key]
        return (
          <KpiCard
            key={metric.key}
            label={metric.label}
            value={metric.value(activeKpis)}
            delta={
              deltaValue === undefined
                ? undefined
                : formatDelta(deltaValue, metric.deltaSuffix ?? '')
            }
            tone={
              deltaValue === undefined
                ? 'default'
                : deltaTone(metric.key, deltaValue)
            }
          />
        )
      })}
    </section>
  )
}
