import {
  AlertTriangle,
  ArrowRight,
  CircleDollarSign,
  Gauge,
  ShieldCheck,
} from 'lucide-react'
import type { NetworkInsight } from '@/api/types'
import { cn } from '@/lib/utils'

export default function NetworkInsightRail({
  insights,
  onSelect,
}: {
  insights: NetworkInsight[]
  onSelect: (entityType: 'facility' | 'lane', entityId: string) => void
}) {
  return (
    <aside className="flex min-h-0 flex-col rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Planning insights</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Exceptions and opportunities in the selected plan context.
        </p>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {insights.length === 0 ? (
          <div className="rounded-md border border-border bg-background/40 p-4 text-center text-xs text-muted-foreground">
            No material exceptions in this view.
          </div>
        ) : (
          insights.map((insight) => {
            const Icon = insightIcon(insight.insight_type)
            const selectable =
              insight.entity_type !== 'network' && Boolean(insight.entity_id)
            return (
              <button
                type="button"
                key={insight.insight_id}
                disabled={!selectable}
                onClick={() => {
                  if (selectable) {
                    onSelect(
                      insight.entity_type as 'facility' | 'lane',
                      insight.entity_id as string,
                    )
                  }
                }}
                className={cn(
                  'w-full rounded-md border p-3 text-left transition-colors',
                  insight.severity === 'critical' &&
                    'border-destructive/50 bg-destructive/5',
                  insight.severity === 'warning' &&
                    'border-warning/40 bg-warning/5',
                  insight.severity === 'info' && 'border-border bg-background/40',
                  selectable && 'hover:border-primary/50 hover:bg-accent',
                )}
              >
                <div className="flex items-start gap-2">
                  <Icon
                    className={cn(
                      'mt-0.5 h-4 w-4 flex-shrink-0',
                      insight.severity === 'critical' && 'text-destructive',
                      insight.severity === 'warning' && 'text-warning',
                      insight.severity === 'info' && 'text-primary',
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium leading-5">{insight.title}</div>
                    <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                      {insight.summary}
                    </p>
                    {insight.metric_value !== null && (
                      <div className="mt-2 text-[11px] font-medium tabular-nums text-foreground">
                        {formatMetric(insight.metric_value)} {insight.metric_unit}
                      </div>
                    )}
                  </div>
                  {selectable && <ArrowRight className="mt-1 h-3.5 w-3.5 text-muted-foreground" />}
                </div>
              </button>
            )
          })
        )}
      </div>
    </aside>
  )
}

function insightIcon(insightType: NetworkInsight['insight_type']) {
  if (insightType === 'high_cost') return CircleDollarSign
  if (insightType === 'bottleneck' || insightType === 'underutilized_capacity') return Gauge
  if (insightType === 'service_risk') return ShieldCheck
  return AlertTriangle
}

function formatMetric(value: number) {
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 })
}
