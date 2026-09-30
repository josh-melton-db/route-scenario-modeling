import { CalendarRange } from 'lucide-react'
import type {
  NetworkOptions,
  NetworkOverviewParams,
} from '@/api/types'
import { cn } from '@/lib/utils'

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
    <section
      aria-label="Network baseline filters"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border bg-card px-3 py-2.5"
    >
      <ContextSelect
        label="Demand plan"
        className="flex-1 basis-52"
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
        className="flex-1 basis-52"
        value={value.capacity_plan_version_id}
        onChange={(next) => onChange({ capacity_plan_version_id: next })}
        options={options.capacity_plans.map((plan) => ({
          value: plan.plan_version_id,
          label: plan.display_name,
        }))}
      />
      <DateField
        label="Start"
        className="basis-44"
        value={value.horizon_start}
        min={
          options.demand_plans.find(
            (row) => row.plan_version_id === value.demand_plan_version_id,
          )?.horizon_start
        }
        max={value.horizon_end}
        onChange={(next) => onChange({ horizon_start: next })}
      />
      <DateField
        label="End"
        className="basis-44"
        value={value.horizon_end}
        min={value.horizon_start}
        max={
          options.demand_plans.find(
            (row) => row.plan_version_id === value.demand_plan_version_id,
          )?.horizon_end
        }
        onChange={(next) => onChange({ horizon_end: next })}
      />
      <ContextSelect
        label="Region"
        className="flex-1 basis-36"
        value={value.region_id}
        onChange={(next) => onChange({ region_id: next })}
        options={options.regions.map((region) => ({
          value: region.region_id,
          label: region.region_name,
        }))}
      />
      <ContextSelect
        label="Planning layer"
        className="flex-1 basis-44"
        value={value.lane_type}
        onChange={(next) =>
          onChange({ lane_type: next as NetworkOverviewParams['lane_type'] })
        }
        options={options.lane_types.map((laneType) => ({
          value: laneType,
          label: laneLabels[laneType],
        }))}
      />
    </section>
  )
}

function ContextSelect({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  className?: string
}) {
  return (
    <label
      className={cn(
        'flex min-w-0 items-center gap-2 text-[11px] font-medium text-muted-foreground',
        className,
      )}
    >
      <span className="whitespace-nowrap">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full min-w-0 rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
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

function DateField({
  label,
  value,
  min,
  max,
  onChange,
  className,
}: {
  label: string
  value: string
  min?: string
  max?: string
  onChange: (value: string) => void
  className?: string
}) {
  return (
    <label
      className={cn(
        'flex min-w-0 items-center gap-2 text-[11px] font-medium text-muted-foreground',
        className,
      )}
    >
      <span className="flex items-center gap-1 whitespace-nowrap">
        <CalendarRange className="h-3 w-3" /> {label}
      </span>
      <input
        type="date"
        value={value}
        min={min}
        max={max}
        onChange={(event) => onChange(event.target.value)}
        className="w-full min-w-[7.5rem] rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
      />
    </label>
  )
}
