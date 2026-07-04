import type { CostBreakdown as CostBreakdownType } from '@/api/types'
import { formatCurrency } from '@/lib/format'

interface CostBreakdownProps {
  costs: CostBreakdownType
}

export default function CostBreakdown({ costs }: CostBreakdownProps) {
  const rows = [
    ['Mileage', costs.mileage_cost],
    ['Labor', costs.labor_cost],
    ['Overtime', costs.overtime_cost],
    ['Fixed vehicle', costs.fixed_vehicle_cost],
    ['SLA penalties', costs.sla_penalty_cost],
  ] as const

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-sm font-semibold">Cost breakdown</div>
      <div className="mt-3 space-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between">
            <span className="text-muted-foreground">{label}</span>
            <span className="font-medium tabular-nums">{formatCurrency(value)}</span>
          </div>
        ))}
        <div className="flex items-center justify-between border-t border-border pt-2 font-semibold">
          <span>Total cost</span>
          <span className="tabular-nums">{formatCurrency(costs.total_cost)}</span>
        </div>
      </div>
    </div>
  )
}
