import { useState } from 'react'
import { CalendarDays, Check, ChevronDown } from 'lucide-react'
import type { DepotPlanDaySummary } from '@/api/types'
import { cn } from '@/lib/utils'

export default function DepotPlanCalendar({
  days,
  selectedDate,
  onSelect,
  onSolve,
  solvingDate,
}: {
  days: DepotPlanDaySummary[]
  selectedDate: string
  onSelect: (serviceDate: string) => void
  onSolve: (serviceDate: string) => void
  solvingDate?: string | null
}) {
  const [open, setOpen] = useState(false)
  const selected = days.find((day) => day.service_date === selectedDate)

  return (
    <div className="relative w-fit" aria-label="Depot plan date">
      <button type="button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-sm hover:bg-accent/50">
        <CalendarDays className="h-4 w-4 text-muted-foreground" />
        <span>{formatDate(selectedDate)}</span>
        {selected && <span className={cn('text-xs capitalize', statusTone(selected.status))}>{statusLabel(selected.status)}</span>}
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
      </button>
      {open && (
        <div role="listbox" aria-label="Depot plan dates" className="absolute left-0 top-10 z-30 max-h-72 w-72 overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-lg">
          {days.map((day) => (
            <div key={day.service_date} role="option" aria-selected={selectedDate === day.service_date} className={cn('flex items-center rounded-sm hover:bg-accent', selectedDate === day.service_date && 'bg-accent/60')}>
            <button type="button" onClick={() => { onSelect(day.service_date); setOpen(false) }} className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2 text-left text-sm">
              <Check className={cn('h-4 w-4 text-primary', selectedDate !== day.service_date && 'opacity-0')} />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{formatDate(day.service_date)}</span>
                <span className="block truncate text-xs text-muted-foreground">{day.routed_cases == null ? `${day.assigned_cases} assigned cases` : `${day.routed_cases}/${day.assigned_cases} cases`}{day.is_overridden ? ' · override' : ''}</span>
              </span>
              <span className={cn('text-xs capitalize', statusTone(day.status))}>{statusLabel(day.status)}</span>
            </button>
            {day.default_status === 'not_requested' && <button type="button" aria-label={`Solve ${formatDate(day.service_date)}`} disabled={Boolean(solvingDate)} onClick={() => onSolve(day.service_date)} className="mr-1.5 rounded border border-border px-1.5 py-1 text-[11px] font-medium text-primary hover:bg-background disabled:opacity-50">{solvingDate === day.service_date ? 'Queueing…' : 'Solve'}</button>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function formatDate(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

function statusLabel(status: string) {
  return status === 'not_requested' ? 'not solved' : status
}

function statusTone(status: DepotPlanDaySummary['status'] | 'not_requested') {
  if (status === 'failed' || status === 'infeasible') return 'text-destructive'
  if (status === 'completed') return 'text-emerald-500'
  return 'text-amber-500'
}
