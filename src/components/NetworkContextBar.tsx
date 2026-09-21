import { CalendarRange, Database, Layers3 } from 'lucide-react'
import type {
  NetworkOptions,
  NetworkOverviewParams,
} from '@/api/types'

interface NetworkContextBarProps {
  options: NetworkOptions
  value: NetworkOverviewParams
  onChange: (patch: Partial<NetworkOverviewParams>) => void
}

const laneLabels = {
  ALL: 'All planning layers',
  LINEHAUL: 'Linehaul',
  MARKET: 'Market allocation',
  DELIVERY: 'Depot delivery',
}

export default function NetworkContextBar({
  options,
  value,
  onChange,
}: NetworkContextBarProps) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="rounded-md bg-primary/15 p-2 text-primary">
            <Layers3 className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold">Network baseline</h1>
              <span className="rounded-full border border-border bg-background px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                Published inputs
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {options.source} · refreshed {formatFreshness(options.freshness_at)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Database className="h-3.5 w-3.5" />
          Demand and capacity are read-only
        </div>
      </div>

      <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-[1.4fr_1.4fr_1fr_1fr_1fr_1fr_1fr]">
        <ContextSelect
          label="Demand plan"
          value={value.demand_plan_version_id}
          onChange={(next) => {
            const plan = options.demand_plans.find(
              (row) => row.plan_version_id === next,
            )
            onChange({
              demand_plan_version_id: next,
              ...(plan
                ? {
                    horizon_start: plan.horizon_start,
                    horizon_end: plan.horizon_end,
                  }
                : {}),
            })
          }}
          options={options.demand_plans.map((plan) => ({
            value: plan.plan_version_id,
            label: plan.display_name,
          }))}
        />
        <ContextSelect
          label="Capacity plan"
          value={value.capacity_plan_version_id}
          onChange={(next) => onChange({ capacity_plan_version_id: next })}
          options={options.capacity_plans.map((plan) => ({
            value: plan.plan_version_id,
            label: plan.display_name,
          }))}
        />
        <label className="text-[11px] font-medium text-muted-foreground">
          <span className="flex items-center gap-1">
            <CalendarRange className="h-3 w-3" /> Start
          </span>
          <input
            type="date"
            value={value.horizon_start}
            min={
              options.demand_plans.find(
                (row) => row.plan_version_id === value.demand_plan_version_id,
              )?.horizon_start
            }
            max={value.horizon_end}
            onChange={(event) => onChange({ horizon_start: event.target.value })}
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
          />
        </label>
        <label className="text-[11px] font-medium text-muted-foreground">
          <span className="flex items-center gap-1">
            <CalendarRange className="h-3 w-3" /> End
          </span>
          <input
            type="date"
            value={value.horizon_end}
            min={value.horizon_start}
            max={
              options.demand_plans.find(
                (row) => row.plan_version_id === value.demand_plan_version_id,
              )?.horizon_end
            }
            onChange={(event) => onChange({ horizon_end: event.target.value })}
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
          />
        </label>
        <ContextSelect
          label="Region"
          value={value.region_id}
          onChange={(next) => onChange({ region_id: next })}
          options={options.regions.map((region) => ({
            value: region.region_id,
            label: region.region_name,
          }))}
        />
        <ContextSelect
          label="Planning layer"
          value={value.lane_type}
          onChange={(next) =>
            onChange({ lane_type: next as NetworkOverviewParams['lane_type'] })
          }
          options={options.lane_types.map((laneType) => ({
            value: laneType,
            label: laneLabels[laneType],
          }))}
        />
        <ContextSelect
          label="Map metric"
          value={value.metric}
          onChange={(next) =>
            onChange({ metric: next as NetworkOverviewParams['metric'] })
          }
          options={options.metrics.map((metric) => ({
            value: metric.metric_id,
            label: metric.label,
          }))}
        />
      </div>
    </section>
  )
}

function ContextSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}) {
  return (
    <label className="min-w-0 text-[11px] font-medium text-muted-foreground">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function formatFreshness(value: string) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.valueOf())) return value
  return parsed.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}
