import type { Depot } from '@/api/types'

interface DepotDayFilterProps {
  depots: Depot[]
  days: string[]
  depotId: string
  deliveryDay: string
  onChange: (depotId: string, deliveryDay: string) => void
}

export default function DepotDayFilter({
  depots,
  days,
  depotId,
  deliveryDay,
  onChange,
}: DepotDayFilterProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-xs text-muted-foreground">
        Depot
        <select
          value={depotId}
          onChange={(event) => onChange(event.target.value, deliveryDay)}
          className="ml-2 rounded-md border border-border bg-card px-2 py-1.5 text-sm text-foreground"
        >
          {depots.map((depot) => (
            <option key={depot.depot_id} value={depot.depot_id}>
              {depot.name}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-muted-foreground">
        Delivery day
        <select
          value={deliveryDay}
          onChange={(event) => onChange(depotId, event.target.value)}
          className="ml-2 rounded-md border border-border bg-card px-2 py-1.5 text-sm text-foreground"
        >
          {days.map((day) => (
            <option key={day} value={day}>
              {day}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
