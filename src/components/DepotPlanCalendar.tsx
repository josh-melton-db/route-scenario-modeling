import type { DepotPlanDaySummary } from '@/api/types'
import { cn } from '@/lib/utils'

export default function DepotPlanCalendar({
  days,
  selectedDate,
  onSelect,
}: {
  days: DepotPlanDaySummary[]
  selectedDate: string
  onSelect: (serviceDate: string) => void
}) {
  return (
    <div className="grid grid-cols-4 gap-2 sm:grid-cols-7" aria-label="Depot plan dates">
      {days.map((day) => (
        <button
          key={day.service_date}
          type="button"
          onClick={() => onSelect(day.service_date)}
          className={cn(
            'rounded-md border px-2 py-2 text-left text-xs transition-colors hover:bg-accent',
            selectedDate === day.service_date && 'border-primary bg-primary/10',
          )}
        >
          <div className="font-medium">
            {new Date(`${day.service_date}T12:00:00`).toLocaleDateString(undefined, {
              weekday: 'short', month: 'short', day: 'numeric',
            })}
          </div>
          <div className={cn('mt-1 capitalize text-muted-foreground', statusTone(day.status))}>
            {day.status}
          </div>
          <div className="mt-1 tabular-nums text-muted-foreground">
            {day.routed_cases == null ? 'Pending' : `${day.routed_cases}/${day.assigned_cases} cases`}
          </div>
          {day.is_overridden && <div className="mt-1 text-primary">Override</div>}
        </button>
      ))}
    </div>
  )
}

function statusTone(status: DepotPlanDaySummary['status']) {
  if (status === 'failed' || status === 'infeasible') return 'text-destructive'
  if (status === 'completed') return 'text-emerald-500'
  return 'text-amber-500'
}
