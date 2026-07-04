import type { CustomerImpact } from '@/api/types'
import { formatNumber } from '@/lib/format'

export default function CustomerImpactTable({
  impacts,
}: {
  impacts: CustomerImpact[]
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <div className="text-sm font-semibold">Customer impacts</div>
        <div className="mt-1 text-xs text-muted-foreground">
          {impacts.length} affected customers
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-muted-foreground">
            <tr className="border-b border-border/60">
              <th className="px-4 py-2">Customer</th>
              <th className="px-4 py-2">Change</th>
              <th className="px-4 py-2">Baseline</th>
              <th className="px-4 py-2">Scenario</th>
              <th className="px-4 py-2">Risk</th>
              <th className="px-4 py-2">Score</th>
            </tr>
          </thead>
          <tbody>
            {impacts.length === 0 ? (
              <tr>
                <td className="px-4 py-6 text-muted-foreground" colSpan={6}>
                  No customer-level impacts for this scenario.
                </td>
              </tr>
            ) : (
              impacts.map((impact) => (
                <tr key={impact.customer_id} className="border-b border-border/40">
                  <td className="px-4 py-3">
                    <div className="font-medium">{impact.customer_name}</div>
                    <div className="text-xs text-muted-foreground">{impact.summary}</div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {[
                      impact.is_new_customer && 'new',
                      impact.changed_route && 'route',
                      impact.changed_day && 'day',
                      impact.changed_depot && 'depot',
                    ]
                      .filter(Boolean)
                      .join(', ') || 'none'}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {impact.baseline_day ?? 'n/a'}
                    <div className="text-xs">{impact.baseline_route_id ?? 'n/a'}</div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {impact.scenario_day ?? 'n/a'}
                    <div className="text-xs">{impact.scenario_route_id ?? 'n/a'}</div>
                  </td>
                  <td className="px-4 py-3">{impact.window_risk}</td>
                  <td className="px-4 py-3 tabular-nums">
                    {formatNumber(impact.disruption_score, 2)}
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
