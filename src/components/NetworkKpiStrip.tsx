import type { NetworkOverview } from '@/api/types'
import { formatCurrency, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

export default function NetworkKpiStrip({ overview }: { overview: NetworkOverview }) {
  const { kpis, context } = overview
  const horizonDays =
    Math.max(
      1,
      Math.round(
        (Date.parse(`${context.horizon_end}T00:00:00`) -
          Date.parse(`${context.horizon_start}T00:00:00`)) /
          86_400_000,
      ) + 1,
    )
  const window = `${horizonDays}d`
  const cards: Array<{
    label: string
    value: string
    measure: string
    tone?: 'good' | 'bad' | 'warn' | 'neutral'
  }> = [
    { label: 'Demand', value: formatNumber(kpis.demand_units), measure: `${window} cases` },
    {
      label: 'Assigned flow',
      value: formatNumber(kpis.assigned_units),
      measure: `${window} cases`,
    },
    {
      label: 'Unmet demand',
      value: formatNumber(kpis.unmet_units),
      measure: `${window} cases`,
      tone: kpis.unmet_units > 0 ? 'bad' : 'good',
    },
    { label: 'Modeled cost', value: formatCurrency(kpis.total_cost), measure: `${window} USD` },
    {
      label: 'Cost per case',
      value: kpis.cost_per_unit.toLocaleString(undefined, {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }),
      measure: 'USD',
    },
    {
      label: 'On-time outlook',
      value: formatPercent(kpis.on_time_pct),
      measure: 'planned',
      tone: kpis.on_time_pct < 95 ? 'bad' : 'good',
    },
    {
      label: 'Utilization',
      value: formatPercent(kpis.utilization_pct),
      measure: 'of capacity',
      tone: kpis.utilization_pct >= 95 ? 'bad' : kpis.utilization_pct >= 85 ? 'warn' : 'neutral',
    },
  ]

  return (
    <section aria-label="Network key performance indicators">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7">
        {cards.map((card) => (
          <div
            key={card.label}
            className={cn(
              'rounded-lg border bg-card px-3 py-2',
              card.tone === 'bad' && 'border-destructive/50 bg-destructive/5',
              card.tone === 'good' && 'border-success/40 bg-success/5',
              card.tone === 'warn' && 'border-warning/50 bg-warning/5',
              (!card.tone || card.tone === 'neutral') && 'border-border',
            )}
          >
            <div className="flex min-w-0 items-baseline gap-1.5">
              <span className="whitespace-nowrap text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {card.label}
              </span>
              <span
                className="truncate text-[9px] text-muted-foreground/70"
                title={overview.source}
              >
                {card.measure}
              </span>
            </div>
            <div className="mt-0.5 text-lg font-semibold tabular-nums">{card.value}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
