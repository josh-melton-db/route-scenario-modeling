import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react'
import type { RunStatusResponse } from '@/api/types'
import { cn } from '@/lib/utils'

export default function RunStatusBanner({ run }: { run: RunStatusResponse }) {
  const terminal = ['succeeded', 'infeasible', 'failed'].includes(run.status)
  const Icon =
    run.status === 'succeeded'
      ? CheckCircle2
      : run.status === 'infeasible' || run.status === 'failed'
        ? AlertTriangle
        : Loader2

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-start gap-3">
        <Icon
          className={cn(
            'mt-0.5 h-5 w-5',
            !terminal && 'animate-spin text-primary',
            run.status === 'succeeded' && 'text-emerald-400',
            ['infeasible', 'failed'].includes(run.status) && 'text-amber-400',
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-lg font-semibold">Run {run.run_id}</div>
              <p className="mt-1 text-sm text-muted-foreground">{run.message}</p>
            </div>
            <div className="rounded-full border border-border px-3 py-1 text-xs uppercase tracking-wider text-muted-foreground">
              {run.status}
            </div>
          </div>

          <div className="mt-5 h-2 overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${run.progress_pct}%` }}
            />
          </div>
          <div className="mt-2 text-right text-xs text-muted-foreground">
            {run.progress_pct}%
          </div>

          <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {run.stages.map((stage) => (
              <div
                key={stage.stage_id}
                className="rounded-md border border-border/60 bg-background/40 p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{stage.label}</span>
                  <span
                    className={cn(
                      'h-2 w-2 rounded-full',
                      stage.status === 'completed' && 'bg-emerald-400',
                      stage.status === 'running' && 'bg-primary',
                      stage.status === 'pending' && 'bg-muted-foreground',
                      stage.status === 'failed' && 'bg-destructive',
                      stage.status === 'skipped' && 'bg-muted-foreground/50',
                    )}
                  />
                </div>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  {stage.message}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
