import type { DecisionExplanation, TransportationAllocation as Allocation } from '@/api/types'
import { formatCurrency, formatNumber } from '@/lib/format'

export default function TransportationAllocation({ allocations, decisions }: { allocations: Allocation[]; decisions: DecisionExplanation[] }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
      <section className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-4 py-3"><h3 className="text-sm font-semibold">Transportation allocation</h3><p className="mt-1 text-xs text-muted-foreground">How the optimized plan fulfills demand.</p></div>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs uppercase text-muted-foreground"><tr><th className="px-4 py-2">Option</th><th className="px-4 py-2">Deliveries</th><th className="px-4 py-2">Cases</th><th className="px-4 py-2">Miles</th><th className="px-4 py-2">Cost</th></tr></thead><tbody>{allocations.map((row) => <tr key={row.fulfillment_method} className="border-t border-border/50"><td className="px-4 py-2 font-medium">{row.label}</td><td className="px-4 py-2">{row.deliveries}</td><td className="px-4 py-2">{formatNumber(row.cases)}</td><td className="px-4 py-2">{formatNumber(row.miles, 1)}</td><td className="px-4 py-2">{formatCurrency(row.cost)}</td></tr>)}</tbody></table></div>
      </section>
      <section className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-semibold">Decision explanations</h3>
        <p className="mt-1 text-xs text-muted-foreground">Carrier and exception assignments with deterministic reason codes.</p>
        <div className="mt-3 max-h-56 space-y-2 overflow-y-auto">{decisions.length === 0 ? <p className="text-sm text-muted-foreground">No carrier or unserved exceptions.</p> : decisions.map((row) => <div key={`${row.customer_id}-${row.decision}`} className="rounded-md border border-border/60 p-2 text-xs"><div className="font-medium">{row.customer_name} · {row.decision}</div><div className="mt-1 text-muted-foreground">{row.reason}</div></div>)}</div>
      </section>
    </div>
  )
}
