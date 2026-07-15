import { Trash2 } from 'lucide-react'
import type { CostOverride } from '@/api/types'

const DEFAULTS: Required<
  Pick<
    CostOverride,
    | 'cost_per_mile'
    | 'labor_regular_hour'
    | 'overtime_multiplier'
    | 'overtime_threshold_minutes'
    | 'fixed_truck_daily_cost'
    | 'late_delivery_penalty'
    | 'missed_delivery_penalty'
  >
> = {
  cost_per_mile: 3.0,
  labor_regular_hour: 80.0,
  overtime_multiplier: 1.5,
  overtime_threshold_minutes: 480,
  fixed_truck_daily_cost: 340.0,
  late_delivery_penalty: 75.0,
  missed_delivery_penalty: 400.0,
}

const FIELDS: Array<{
  key: keyof typeof DEFAULTS
  label: string
  help: string
  step?: number
}> = [
  {
    key: 'cost_per_mile',
    label: 'Cost per mile ($)',
    help: 'Mileage rate applied to road-adjusted miles.',
    step: 0.1,
  },
  {
    key: 'labor_regular_hour',
    label: 'Labor regular hour ($)',
    help: 'Fully loaded regular labor cost per hour.',
    step: 1,
  },
  {
    key: 'overtime_multiplier',
    label: 'Overtime multiplier',
    help: 'Multiplier applied to labor after the overtime threshold.',
    step: 0.1,
  },
  {
    key: 'overtime_threshold_minutes',
    label: 'Overtime threshold (min)',
    help: 'Minutes before overtime labor cost starts.',
    step: 15,
  },
  {
    key: 'fixed_truck_daily_cost',
    label: 'Fixed truck daily cost ($)',
    help: 'Fixed cost charged once per active route/vehicle.',
    step: 10,
  },
  {
    key: 'late_delivery_penalty',
    label: 'Late delivery penalty ($)',
    help: 'Penalty per late stop.',
    step: 5,
  },
  {
    key: 'missed_delivery_penalty',
    label: 'Missed delivery penalty ($)',
    help: 'Penalty per missed/unassigned stop.',
    step: 10,
  },
]

interface CostParameterFormProps {
  value: CostOverride
  onChange: (value: CostOverride) => void
  onRemove?: () => void
}

export default function CostParameterForm({
  value,
  onChange,
  onRemove,
}: CostParameterFormProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">Cost parameters</div>
          <p className="mt-1 text-xs text-muted-foreground">
            Overrides apply to both baseline and scenario costing so before/after
            deltas stay comparable.
          </p>
        </div>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Remove
          </button>
        )}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        {FIELDS.map((field) => {
          const current =
            value[field.key] === null || value[field.key] === undefined
              ? DEFAULTS[field.key]
              : Number(value[field.key])
          return (
            <label key={field.key} className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">{field.label}</span>
              <input
                type="number"
                step={field.step ?? 1}
                value={Number(current)}
                onChange={(event) =>
                  onChange({
                    ...value,
                    [field.key]: Number.parseFloat(event.target.value),
                  })
                }
                className="rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
              />
              <span className="text-xs leading-5 text-muted-foreground">
                {field.help} Default {DEFAULTS[field.key]}.
              </span>
            </label>
          )
        })}
      </div>
      <button
        type="button"
        className="mt-3 text-xs text-muted-foreground underline"
        onClick={() => onChange({})}
      >
        Reset to defaults
      </button>
    </div>
  )
}
