import { useMemo, useState } from 'react'
import { ReceiptText, Route as RouteIcon } from 'lucide-react'
import type { Route } from '@/api/types'
import { formatCurrency, formatNumber } from '@/lib/format'

export default function CarrierCostAnalysis({
  routes,
  generatedAt,
}: {
  routes: Route[]
  generatedAt: string
}) {
  const carrierRoutes = useMemo(
    () => routes.filter((route) => route.fulfillment_method === 'carrier'),
    [routes],
  )
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(
    carrierRoutes[0]?.route_id ?? null,
  )
  const selected =
    carrierRoutes.find((route) => route.route_id === selectedRouteId) ??
    carrierRoutes[0]
  const total = carrierRoutes.reduce((sum, route) => sum + route.total_cost, 0)

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <ReceiptText className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">Carrier cost audit</h3>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Exact contract rules and formulas applied to each outsourced route.
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs text-muted-foreground">Carrier spend</div>
          <div className="mt-1 text-lg font-semibold tabular-nums">{formatCurrency(total)}</div>
          <div className="mt-1 text-[10px] text-muted-foreground">
            Scenario result generated {new Date(generatedAt).toLocaleString()}
          </div>
        </div>
      </div>

      {carrierRoutes.length === 0 ? (
        <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
          <RouteIcon className="h-7 w-7 text-muted-foreground" />
          <div className="mt-3 text-sm font-medium">No carrier routes in this plan</div>
          <p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">
            All demand was assigned to private-fleet capacity, so no carrier rate rules were applied.
          </p>
        </div>
      ) : (
        <div className="grid min-h-[340px] lg:grid-cols-[minmax(420px,0.9fr)_1.1fr]">
          <div className="overflow-x-auto border-b border-border lg:border-b-0 lg:border-r">
            <table className="w-full min-w-[620px] text-left text-sm">
              <thead className="bg-background/40 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">Route</th>
                  <th className="px-4 py-3">Contract</th>
                  <th className="px-4 py-3">Rated inputs</th>
                  <th className="px-4 py-3 text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {carrierRoutes.map((route) => (
                  <tr
                    key={route.route_id}
                    onClick={() => setSelectedRouteId(route.route_id)}
                    className={`cursor-pointer border-t border-border/60 ${selected?.route_id === route.route_id ? 'bg-primary/8' : 'hover:bg-accent/25'}`}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium">{route.route_name}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{route.rate_lane ?? 'Lane unavailable'}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium">{route.carrier_name}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{route.contract_name} · {route.contract_version_id}</div>
                    </td>
                    <td className="px-4 py-3 text-xs tabular-nums text-muted-foreground">
                      {formatNumber(route.total_miles, 1)} mi · {route.stops.length} stops
                    </td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums">{formatCurrency(route.total_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selected ? (
            <div className="min-w-0">
              <div className="border-b border-border bg-background/25 px-4 py-3">
                <div className="font-medium">{selected.route_name} charge lines</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Service date {selected.rated_service_date} · snapshot <span className="font-mono text-[10px]">{selected.rate_book_snapshot_id}</span>
                </div>
              </div>
              {selected.carrier_charge_lines.length ? (
                <div className="max-h-[390px] overflow-auto">
                  <table className="w-full min-w-[560px] text-left text-sm">
                    <thead className="sticky top-0 bg-card text-xs uppercase text-muted-foreground">
                      <tr><th className="px-4 py-3">Charge</th><th className="px-4 py-3">Formula</th><th className="px-4 py-3 text-right">Amount</th></tr>
                    </thead>
                    <tbody>
                      {selected.carrier_charge_lines.map((line, index) => (
                        <tr key={`${line.rule_id}-${line.category}-${index}`} className="border-t border-border/60">
                          <td className="px-4 py-3"><div className="font-medium">{line.label}</div><div className="mt-1 font-mono text-[10px] text-muted-foreground">{line.rule_id}</div></td>
                          <td className="px-4 py-3 text-xs tabular-nums text-muted-foreground">{line.formula}</td>
                          <td className={`px-4 py-3 text-right font-medium tabular-nums ${line.amount < 0 ? 'text-primary' : ''}`}>{formatCurrency(line.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="px-5 py-12 text-center text-sm text-muted-foreground">This legacy route has no persisted charge lines.</div>
              )}
            </div>
          ) : null}
        </div>
      )}
    </section>
  )
}
