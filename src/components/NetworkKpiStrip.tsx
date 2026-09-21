import type { NetworkOverview } from '@/api/types'
import { formatCurrency, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

export default function NetworkKpiStrip({ overview }: { overview: NetworkOverview }) {
  const { kpis, context } = overview
  const period = `${formatShortDate(context.horizon_start)}–${formatShortDate(context.horizon_end)}`
  const cards: Array<{
    label: string
    value: string
    unit: string
    tone?: 'good' | 'bad' | 'warn' | 'neutral'
  }> = [
    { label: 'Demand', value: formatNumber(kpis.demand_units), unit: 'cases' },
    { label: 'Assigned flow', value: formatNumber(kpis.assigned_units), unit: 'cases' },
    {
      label: 'Unmet demand',
      value: formatNumber(kpis.unmet_units),
      unit: 'cases',
      tone: kpis.unmet_units > 0 ? 'bad' : 'good',
    },
    { label: 'Modeled cost', value: formatCurrency(kpis.total_cost), unit: 'USD' },
    {
      label: 'Cost per case',
      value: kpis.cost_per_unit.toLocaleString(undefined, {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }),
      unit: 'USD/case',
    },
    {
      label: 'On-time outlook',
      value: formatPercent(kpis.on_time_pct),
      unit: 'planned',
      tone: kpis.on_time_pct < 95 ? 'bad' : 'good',
    },
    {
      label: 'Utilization',
      value: formatPercent(kpis.utilization_pct),
      unit: 'supplied capacity',
      tone: kpis.utilization_pct >= 95 ? 'bad' : kpis.utilization_pct >= 85 ? 'warn' : 'neutral',
    },
  ]

  return (
    <section aria-label="Network key performance indicators">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{overview.summary}</span>
        <span title={overview.source}>{period} · published plan snapshot</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7">
        {cards.map((card) => (
          <div
            key={card.label}
            className={cn(
              'rounded-lg border bg-card p-3',
              card.tone === 'bad' && 'border-destructive/50 bg-destructive/5',
              card.tone === 'good' && 'border-success/40 bg-success/5',
              card.tone === 'warn' && 'border-warning/50 bg-warning/5',
              (!card.tone || card.tone === 'neutral') && 'border-border',
            )}
          >
            <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              {card.label}
            </div>
            <div className="mt-1 text-xl font-semibold tabular-nums">{card.value}</div>
            <div className="mt-1 truncate text-[10px] text-muted-foreground" title={overview.source}>
              {card.unit} · {period}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function formatShortDate(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}
