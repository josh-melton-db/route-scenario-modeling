import type { ConstraintViolation } from '@/api/types'
import { formatNumber } from '@/lib/format'

export default function ConstraintViolationsTable({
  violations,
}: {
  violations: ConstraintViolation[]
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <div className="text-sm font-semibold">Constraint diagnostics</div>
        <div className="mt-1 text-xs text-muted-foreground">
          {violations.length} violations
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-muted-foreground">
            <tr className="border-b border-border/60">
              <th className="px-4 py-2">Severity</th>
              <th className="px-4 py-2">Scope</th>
              <th className="px-4 py-2">Metric</th>
              <th className="px-4 py-2">Actual / limit</th>
              <th className="px-4 py-2">Message</th>
              <th className="px-4 py-2">Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {violations.length === 0 ? (
              <tr>
                <td className="px-4 py-6 text-muted-foreground" colSpan={6}>
                  No hard or soft constraint violations.
                </td>
              </tr>
            ) : (
              violations.map((violation) => (
                <tr key={violation.violation_id} className="border-b border-border/40">
                  <td className="px-4 py-3 font-medium">{violation.severity}</td>
                  <td className="px-4 py-3 text-muted-foreground">{violation.scope}</td>
                  <td className="px-4 py-3">{violation.metric}</td>
                  <td className="px-4 py-3 tabular-nums text-muted-foreground">
                    {violation.actual_value === null
                      ? 'n/a'
                      : formatNumber(violation.actual_value, 1)}
                    {' / '}
                    {violation.limit_value === null
                      ? 'n/a'
                      : formatNumber(violation.limit_value, 1)}
                  </td>
                  <td className="px-4 py-3">{violation.message}</td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {violation.recommendation}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
