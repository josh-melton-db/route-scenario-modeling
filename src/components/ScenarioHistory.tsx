import { ArrowRight, Clock3, Loader2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useRecentScenarios } from '@/api/queries'
import type { ScenarioHistoryItem, ScenarioType } from '@/api/types'
import { cn } from '@/lib/utils'

const SCENARIO_TYPE_LABELS: Record<ScenarioType, string> = {
  baseline: 'Baseline',
  ma_new_customers: 'Locations added',
  new_customer_growth: 'Customer growth',
  driver_count_change: 'Driver count change',
  delivery_frequency_day_change: 'Delivery day change',
  facility_move: 'Facility moved',
  custom: 'Custom scenario',
}

export default function ScenarioHistory() {
  const history = useRecentScenarios(10)

  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="border-b border-border/70 px-4 py-3 text-center">
        <div className="flex items-center justify-center gap-2">
          <Clock3 className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Scenario history</h2>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">Latest 10 saved scenarios</p>
      </div>

      {history.isLoading && (
        <div className="flex items-center justify-center gap-2 px-4 py-8 text-xs text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading history…
        </div>
      )}

      {history.error && (
        <div className="px-4 py-6 text-sm text-destructive">
          Could not load scenario history.
        </div>
      )}

      {history.data?.length === 0 && (
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          Run a scenario to start building history.
        </div>
      )}

      {history.data && history.data.length > 0 && (
        <div className="divide-y divide-border/70">
          {history.data.map((scenario) => (
            <HistoryRow key={scenario.scenario_id} scenario={scenario} />
          ))}
        </div>
      )}
    </section>
  )
}

function HistoryRow({ scenario }: { scenario: ScenarioHistoryItem }) {
  const content = (
    <>
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{scenario.scenario_name}</div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {formatDate(scenario.created_at)} · {scenario.delivery_day}
          </div>
        </div>
        <StatusBadge status={scenario.status} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {scenarioTags(scenario).map((tag) => (
          <span
            key={tag}
            className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
          >
            {tag}
          </span>
        ))}
        {scenario.has_results && (
          <ArrowRight className="ml-auto h-3.5 w-3.5 text-muted-foreground" />
        )}
      </div>
    </>
  )

  if (!scenario.has_results) {
    return (
      <div className="px-4 py-3 opacity-75" title="Comparison is not available yet">
        {content}
      </div>
    )
  }

  return (
    <Link
      to={`/comparison/${scenario.scenario_id}`}
      className="block px-4 py-3 transition-colors hover:bg-accent/50"
      aria-label={`Analyze ${scenario.scenario_name}`}
    >
      {content}
    </Link>
  )
}

function StatusBadge({ status }: { status: ScenarioHistoryItem['status'] }) {
  const terminal = status === 'completed' || status === 'infeasible'
  return (
    <span
      className={cn(
        'shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium capitalize',
        terminal
          ? 'bg-primary/15 text-primary'
          : status === 'failed'
            ? 'bg-destructive/10 text-destructive'
            : 'bg-muted text-muted-foreground',
      )}
    >
      {status}
    </span>
  )
}

function scenarioTags(scenario: ScenarioHistoryItem): string[] {
  const tags: string[] = []
  const changes = scenario.parameters.changes
  if (Array.isArray(changes)) {
    for (const value of changes) {
      if (!isRecord(value)) continue
      if (value.kind === 'add_deliveries') {
        const count = Array.isArray(value.deliveries) ? value.deliveries.length : 0
        tags.push(`${count} ${count === 1 ? 'location' : 'locations'} added`)
      } else if (value.kind === 'driver_count_change') {
        const delta = typeof value.driver_delta === 'number' ? value.driver_delta : 0
        tags.push(driverChangeLabel(delta))
      } else if (value.kind === 'delivery_frequency_day_change') {
        const day = typeof value.target_day === 'string' ? value.target_day : 'new day'
        tags.push(`Delivery day → ${day}`)
      } else if (value.kind === 'facility_move') {
        tags.push('Facility moved')
      }
    }
  }
  if (isRecord(scenario.parameters.cost)) {
    tags.push('Cost parameters')
  }
  return tags.length > 0 ? tags : [SCENARIO_TYPE_LABELS[scenario.scenario_type]]
}

function driverChangeLabel(delta: number): string {
  if (delta === 0) return 'Driver count change'
  const count = Math.abs(delta)
  return `${count} ${count === 1 ? 'driver' : 'drivers'} ${delta > 0 ? 'added' : 'removed'}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Saved scenario'
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
  })
}
