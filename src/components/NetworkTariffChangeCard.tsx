import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import type { NetworkCountryCode, NetworkTariffRule } from '@/api/types'

const COUNTRIES: Array<{ code: NetworkCountryCode; label: string }> = [
  { code: 'US', label: 'United States' },
  { code: 'MX', label: 'Mexico' },
  { code: 'CA', label: 'Canada' },
]

export function createNetworkTariffRule(
  start: string,
  end: string,
): NetworkTariffRule {
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
  onChange,
}: {
  rules: NetworkTariffRule[]
  onChange: (rules: NetworkTariffRule[]) => void
}) {
  const update = (ruleId: string, patch: Partial<NetworkTariffRule>) =>
    onChange(rules.map((rule) => (rule.rule_id === ruleId ? { ...rule, ...patch } : rule)))

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Tariff rules</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Apply a directed border cost in USD per assigned case. Freight rates remain separate.
          </p>
        </div>
      </div>

      {!rules.length ? (
        <p className="mt-3 rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
          No tariff rules yet.
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
                  <TariffAmountInput value={rule.amount_per_case} onCommit={(amount) => update(rule.rule_id, { amount_per_case: amount })} />
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

function TariffAmountInput({ value, onCommit }: { value: number; onCommit: (amount: number) => void }) {
  const [text, setText] = useState(String(value))
  const [focused, setFocused] = useState(false)

  useEffect(() => {
    if (!focused) setText(String(value))
  }, [value, focused])

  return (
    <input
      type="text"
      inputMode="decimal"
      value={text}
      onFocus={() => setFocused(true)}
      onChange={(event) => {
        const next = event.target.value
        if (/^\d*(\.\d*)?$/.test(next)) setText(next)
      }}
      onBlur={() => {
        setFocused(false)
        const amount = Number(text)
        if (text.trim() && Number.isFinite(amount) && amount >= 0) {
          setText(String(amount))
          if (amount !== value) onCommit(amount)
        } else {
          setText(String(value))
        }
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault()
          event.currentTarget.blur()
        }
        if (event.key === 'Escape') {
          event.preventDefault()
          setText(String(value))
        }
      }}
      className="h-9 rounded-md border border-border bg-background px-2 text-sm"
    />
  )
}
