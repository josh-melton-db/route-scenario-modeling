import { Plus, Trash2 } from 'lucide-react'
import type { NetworkCountryCode, NetworkTariffRule } from '@/api/types'

const COUNTRIES: Array<{ code: NetworkCountryCode; label: string }> = [
  { code: 'US', label: 'United States' },
  { code: 'MX', label: 'Mexico' },
  { code: 'CA', label: 'Canada' },
]

function newRule(start: string, end: string): NetworkTariffRule {
  return {
    rule_id: globalThis.crypto?.randomUUID?.() ?? `tariff-${Date.now()}`,
    origin_country: 'MX',
    destination_country: 'US',
    effective_start: start,
    effective_end: end,
    amount_per_case: 0,
  }
}

export default function NetworkTariffChangeCard({
  rules,
  horizonStart,
  horizonEnd,
  onChange,
}: {
  rules: NetworkTariffRule[]
  horizonStart: string
  horizonEnd: string
  onChange: (rules: NetworkTariffRule[]) => void
}) {
  const update = (ruleId: string, patch: Partial<NetworkTariffRule>) =>
    onChange(rules.map((rule) => (rule.rule_id === ruleId ? { ...rule, ...patch } : rule)))

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Add tariff</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Apply a directed border cost in USD per assigned case. Freight rates remain separate.
          </p>
        </div>
        <button
          type="button"
          onClick={() => onChange([...rules, newRule(horizonStart, horizonEnd)])}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent/40"
        >
          <Plus className="h-3.5 w-3.5" /> Add tariff rule
        </button>
      </div>

      {!rules.length ? (
        <p className="mt-3 rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
          No tariff change. Add a rule to price a specific border direction and date range.
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-3">
          {rules.map((rule) => (
            <div key={rule.rule_id} className="rounded-md border border-border/70 bg-background p-3">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_1fr_1fr_auto]">
                <Field label="Origin country">
                  <select value={rule.origin_country} onChange={(event) => update(rule.rule_id, { origin_country: event.target.value as NetworkCountryCode })} className="h-9 rounded-md border border-border bg-background px-2 text-sm">
                    {COUNTRIES.map((country) => <option key={country.code} value={country.code}>{country.label}</option>)}
                  </select>
                </Field>
                <Field label="Destination country">
                  <select value={rule.destination_country} onChange={(event) => update(rule.rule_id, { destination_country: event.target.value as NetworkCountryCode })} className="h-9 rounded-md border border-border bg-background px-2 text-sm">
                    {COUNTRIES.map((country) => <option key={country.code} value={country.code}>{country.label}</option>)}
                  </select>
                </Field>
                <Field label="Effective start">
                  <input type="date" value={rule.effective_start} onChange={(event) => update(rule.rule_id, { effective_start: event.target.value })} className="h-9 rounded-md border border-border bg-background px-2 text-sm" />
                </Field>
                <Field label="Effective end">
                  <input type="date" value={rule.effective_end} onChange={(event) => update(rule.rule_id, { effective_end: event.target.value })} className="h-9 rounded-md border border-border bg-background px-2 text-sm" />
                </Field>
                <Field label="USD / case">
                  <input type="number" min={0} step="0.01" value={rule.amount_per_case} onChange={(event) => update(rule.rule_id, { amount_per_case: Number(event.target.value) || 0 })} className="h-9 rounded-md border border-border bg-background px-2 text-sm" />
                </Field>
                <button type="button" aria-label={`Remove tariff ${rule.rule_id}`} onClick={() => onChange(rules.filter((item) => item.rule_id !== rule.rule_id))} className="mt-5 inline-flex h-9 items-center gap-1 rounded-md border border-border px-2 text-xs text-muted-foreground hover:text-destructive">
                  <Trash2 className="h-3.5 w-3.5" /> Remove
                </button>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {rule.origin_country} → {rule.destination_country} · {rule.effective_start || 'No start'} to {rule.effective_end || 'No end'} · ${rule.amount_per_case || 0}/case
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1 text-xs font-medium"><span>{label}</span>{children}</label>
}
