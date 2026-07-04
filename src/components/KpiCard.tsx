import { cn } from '@/lib/utils'

interface KpiCardProps {
  label: string
  value: string | number
  delta?: string
  tone?: 'default' | 'good' | 'bad' | 'neutral'
}

export default function KpiCard({
  label,
  value,
  delta,
  tone = 'default',
}: KpiCardProps) {
  const toneClass = {
    default: 'border-border bg-card',
    good: 'border-emerald-500/40 bg-emerald-500/5',
    bad: 'border-rose-500/40 bg-rose-500/5',
    neutral: 'border-border bg-card',
  }[tone]

  return (
    <div className={cn('rounded-lg border p-3', toneClass)}>
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {delta !== undefined && (
        <div className="mt-1 text-xs text-muted-foreground tabular-nums">
          {delta}
        </div>
      )}
    </div>
  )
}
