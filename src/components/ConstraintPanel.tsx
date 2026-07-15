import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import type { ValidationResponse } from '@/api/types'

export default function ConstraintPanel({
  validation,
}: {
  validation: ValidationResponse | null
}) {
  if (!validation) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-start gap-2">
          <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-400" />
          <div>
            <div className="text-sm font-semibold">Ready to run</div>
            <p className="mt-1 text-sm text-muted-foreground">
              The server will precheck your changes before optimization starts.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-start gap-2">
        {validation.valid ? (
          <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-400" />
        ) : (
          <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-400" />
        )}
        <div>
          <div className="text-sm font-semibold">
            {validation.valid ? 'Ready to run' : 'Needs attention'}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {validation.summary}
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <Metric label="Affected customers" value={validation.estimated_affected_customers} />
        <Metric label="Affected routes" value={validation.estimated_affected_routes} />
      </div>

      {validation.missing_fields.length > 0 && (
        <div className="mt-4 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100">
          Missing fields: {validation.missing_fields.join(', ')}
        </div>
      )}

      {validation.hard_constraints.length > 0 && (
        <ul className="mt-4 space-y-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {validation.hard_constraints.map((issue, index) => (
            <li key={`${issue.field ?? 'hard'}-${index}`}>{issue.message}</li>
          ))}
        </ul>
      )}

      {validation.soft_penalties.length > 0 && (
        <ul className="mt-4 space-y-2 rounded-md border border-border/60 bg-background/40 p-3 text-xs text-muted-foreground">
          {validation.soft_penalties.map((issue, index) => (
            <li key={`${issue.field ?? 'soft'}-${index}`}>{issue.message}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border/60 bg-background/40 p-3">
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
    </div>
  )
}
