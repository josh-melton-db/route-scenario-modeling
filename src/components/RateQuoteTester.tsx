import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { AlertTriangle, Calculator, CheckCircle2, Loader2 } from 'lucide-react'
import type { RateContractDetail, RateQuoteRequest } from '@/api/types'
import { useDepots, usePreviewRateQuote } from '@/api/queries'
import { formatCurrency, formatNumber } from '@/lib/format'

export default function RateQuoteTester({ contract }: { contract: RateContractDetail }) {
  const depots = useDepots()
  const fallbackDate = contract.version.effective_start ?? new Date().toISOString().slice(0, 10)
  const explicitOrigins = Array.from(
    new Set(contract.lane_rates.map((rule) => rule.origin).filter((value) => value !== '*')),
  )
  const hasOriginFallback = contract.lane_rates.some((rule) => rule.origin === '*')
  const originIds = Array.from(
    new Set([
      ...(depots.data ?? [])
        .filter((depot) => hasOriginFallback || explicitOrigins.includes(depot.depot_id))
        .map((depot) => depot.depot_id),
      ...explicitOrigins,
      ...(hasOriginFallback ? ['*'] : []),
    ]),
  )
  const initialOrigin = explicitOrigins[0] ?? originIds[0] ?? '*'

  function destinationsFor(origin: string) {
    const matchingRules = contract.lane_rates.filter(
      (rule) => rule.origin === origin || rule.origin === '*',
    )
    const exactDestinations = Array.from(
      new Set(
        matchingRules
          .map((rule) => rule.destination)
          .filter((destination) => destination !== '*'),
      ),
    )
    return [
      ...exactDestinations,
      ...(matchingRules.some((rule) => rule.destination === '*') ? ['*'] : []),
    ]
  }

  const [request, setRequest] = useState<RateQuoteRequest>({
    contract_id: contract.contract_id,
    version_id: contract.version.version_id,
    service_date: fallbackDate,
    origin: initialOrigin,
    destination: destinationsFor(initialOrigin)[0] ?? '*',
    miles: 70,
    stops: 6,
    cases: 720,
    period_volume: 54,
    accessorial_codes: [],
    accessorial_quantities: {},
    period_close: false,
  })
  const quote = usePreviewRateQuote()
  const destinationOptions = destinationsFor(request.origin)

  function selectOrigin(origin: string) {
    const destinations = destinationsFor(origin)
    setRequest((current) => ({
      ...current,
      origin,
      destination: destinations.includes(current.destination)
        ? current.destination
        : destinations[0] ?? '*',
    }))
  }

  function updateNumber(field: 'miles' | 'stops' | 'cases' | 'period_volume', value: string) {
    setRequest((current) => ({ ...current, [field]: Number(value) }))
  }

  function toggleAccessorial(code: string, checked: boolean) {
    setRequest((current) => ({
      ...current,
      accessorial_codes: checked
        ? [...current.accessorial_codes, code]
        : current.accessorial_codes.filter((value) => value !== code),
      accessorial_quantities: checked
        ? { ...current.accessorial_quantities, [code]: code === 'DETENTION' ? 1 : code === 'INSIDE_DELIVERY' ? current.stops : 1 }
        : Object.fromEntries(Object.entries(current.accessorial_quantities).filter(([key]) => key !== code)),
    }))
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    quote.mutate(request)
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2"><Calculator className="h-4 w-4 text-primary" /><h2 className="text-sm font-semibold">Quote inputs</h2></div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">Test this saved version without changing a route scenario.</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
          <Field label="Service date"><input aria-label="Quote service date" type="date" min={contract.version.effective_start ?? undefined} max={contract.version.effective_end ?? undefined} required value={request.service_date} onChange={(event) => setRequest({ ...request, service_date: event.target.value })} className="input" /></Field>
          <Field label="Origin depot"><select aria-label="Quote origin" required value={request.origin} onChange={(event) => selectOrigin(event.target.value)} className="input">{originIds.map((origin) => { const depot = depots.data?.find((row) => row.depot_id === origin); return <option key={origin} value={origin}>{origin === '*' ? 'Any origin (fallback)' : depot ? `${depot.name} · ${depot.depot_id}` : origin}</option> })}</select></Field>
          <Field label="Destination zone"><select aria-label="Quote destination zone" required value={request.destination} onChange={(event) => setRequest({ ...request, destination: event.target.value })} className="input">{destinationOptions.map((destination) => <option key={destination} value={destination}>{destination === '*' ? 'Other destination (regional fallback)' : destination}</option>)}</select></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Miles"><input aria-label="Quote miles" type="number" min="0" step="0.1" required value={request.miles} onChange={(event) => updateNumber('miles', event.target.value)} className="input" /></Field>
            <Field label="Stops"><input aria-label="Quote stops" type="number" min="1" step="1" required value={request.stops} onChange={(event) => updateNumber('stops', event.target.value)} className="input" /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Cases"><input aria-label="Quote cases" type="number" min="0" step="1" required value={request.cases} onChange={(event) => updateNumber('cases', event.target.value)} className="input" /></Field>
            <Field label="Projected period stops"><input aria-label="Quote period stops" type="number" min="0" step="1" required value={request.period_volume} onChange={(event) => updateNumber('period_volume', event.target.value)} className="input" /></Field>
          </div>
        </div>
        <div className="mt-4">
          <div className="text-xs font-medium">Accessorial triggers</div>
          <div className="mt-2 space-y-2">
            {contract.accessorials.map((rule) => {
              const checked = request.accessorial_codes.includes(rule.code)
              return <div key={rule.rule_id} className="flex items-center justify-between gap-3 text-xs"><label className="flex items-center gap-2"><input type="checkbox" checked={checked} onChange={(event) => toggleAccessorial(rule.code, event.target.checked)} />{rule.name}</label>{checked && rule.charge_type !== 'flat' ? <input aria-label={`${rule.name} quantity`} type="number" min="0" step="0.5" value={request.accessorial_quantities[rule.code] ?? 1} onChange={(event) => setRequest((current) => ({ ...current, accessorial_quantities: { ...current.accessorial_quantities, [rule.code]: Number(event.target.value) } }))} className="w-20 rounded border border-border bg-background px-2 py-1" /> : null}</div>
            })}
          </div>
        </div>
        <label className="mt-4 flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={request.period_close} onChange={(event) => setRequest({ ...request, period_close: event.target.checked })} />Evaluate end-of-period commitment shortfall</label>
        <button type="submit" disabled={quote.isPending} className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">{quote.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Calculator className="h-4 w-4" />}Calculate transparent quote</button>
        {quote.error ? <div className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">{String(quote.error)}</div> : null}
      </form>

      <section className="overflow-hidden rounded-lg border border-border bg-card">
        {!quote.data ? (
          <div className="flex min-h-[520px] flex-col items-center justify-center px-6 text-center"><Calculator className="h-8 w-8 text-muted-foreground" /><div className="mt-3 text-sm font-medium">Ready to calculate</div><p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">Enter route and period inputs to see every matched rule, formula, and charge.</p></div>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-4 py-4">
              <div className="flex items-start gap-2">{quote.data.eligible ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-primary" /> : <AlertTriangle className="mt-0.5 h-5 w-5 text-destructive" />}<div><h2 className="text-sm font-semibold">{quote.data.eligible ? 'Eligible contract quote' : 'Contract is not eligible'}</h2><p className="mt-1 text-xs text-muted-foreground">{quote.data.eligibility_message}</p></div></div>
              <div className="text-right"><div className="text-xs text-muted-foreground">Total carrier cost</div><div className="mt-1 text-2xl font-semibold tabular-nums">{formatCurrency(quote.data.total_cost)}</div></div>
            </div>
            {quote.data.charge_lines.length ? <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-background/40 text-xs uppercase text-muted-foreground"><tr><th className="px-4 py-3">Charge</th><th className="px-4 py-3">Formula</th><th className="px-4 py-3">Rule</th><th className="px-4 py-3 text-right">Amount</th></tr></thead><tbody>{quote.data.charge_lines.map((line, index) => <tr key={`${line.rule_id}-${line.category}-${index}`} className="border-t border-border/60"><td className="px-4 py-3"><div className="font-medium">{line.label}</div><div className="mt-0.5 text-xs capitalize text-muted-foreground">{line.category.replace('_', ' ')}</div></td><td className="px-4 py-3 text-xs tabular-nums text-muted-foreground">{line.formula}</td><td className="px-4 py-3 font-mono text-[11px] text-muted-foreground">{line.rule_id}</td><td className={`px-4 py-3 text-right font-medium tabular-nums ${line.amount < 0 ? 'text-primary' : ''}`}>{formatCurrency(line.amount)}</td></tr>)}</tbody><tfoot><tr className="border-t border-border"><td colSpan={3} className="px-4 py-3 font-semibold">Total</td><td className="px-4 py-3 text-right font-semibold tabular-nums">{formatCurrency(quote.data.total_cost)}</td></tr></tfoot></table></div> : null}
            <div className="grid gap-3 border-t border-border bg-background/30 p-4 text-xs sm:grid-cols-2 lg:grid-cols-4"><Meta label="Matched lane" value={quote.data.matched_lane ?? 'None'} /><Meta label="Volume tier" value={quote.data.matched_volume_tier ?? 'None'} /><Meta label="Commitment remaining" value={`${formatNumber(quote.data.commitment_remaining)} stops`} /><Meta label="Rate book snapshot" value={quote.data.rate_book_snapshot_id} mono /></div>
          </>
        )}
      </section>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="flex flex-col gap-1 text-xs"><span className="font-medium">{label}</span>{children}</label> }
function Meta({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) { return <div><div className="text-muted-foreground">{label}</div><div className={`mt-1 font-medium ${mono ? 'font-mono text-[11px]' : ''}`}>{value}</div></div> }
