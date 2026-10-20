import type { NetworkScenarioResult } from '@/api/types'
import { formatCurrency, formatNumber } from '@/lib/format'

export function hasComparablePricing(result: NetworkScenarioResult) {
  return ['comparable_pinned_dated_contracts_v1', 'comparable_pinned_dated_contracts_v2_delivery_contracts'].includes(result.pricing_context?.pricing_basis ?? '')
}

export default function NetworkPricingNote({ result, detailed = false }: { result: NetworkScenarioResult; detailed?: boolean }) {
  if (!hasComparablePricing(result)) {
    return <p role="note" className="text-xs text-warning">Cost comparison unavailable for this legacy run. Rerun the plan.</p>
  }
  const baseline = result.baseline_rate_coverage
  const scenario = result.scenario_rate_coverage
  return (
    <div role="note" aria-label="Comparison pricing basis" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span>Pinned contracts</span>
      <span>{formatNumber(result.pricing_context!.load_size_cases)} cases / load</span>
      <span>{result.pricing_context?.pricing_basis === 'comparable_pinned_dated_contracts_v2_delivery_contracts'
        ? 'Linehaul + DELIVERY · 6 stops / 40 miles · lane demand, then depot average · planning fallback where unmatched'
        : 'Linehaul only'}</span>
      {result.objective_gap_material && (
        <span className="text-warning">Rated / solve gap: {formatCurrency(Math.abs(result.objective_to_rated_cost_gap ?? 0))} ({formatNumber(Math.abs(result.objective_to_rated_cost_gap_pct ?? 0))}%)</span>
      )}
      {detailed && <>
        <span className="basis-full">Baseline: {formatCurrency(result.baseline_freight_total_cost ?? 0)} freight + {formatCurrency(result.baseline_tariff_total_cost ?? 0)} tariff = {formatCurrency(result.baseline_total_modeled_cost ?? 0)}</span>
        <span className="basis-full">Scenario: {formatCurrency(result.freight_total_cost ?? 0)} freight + {formatCurrency(result.tariff_total_cost ?? 0)} tariff = {formatCurrency(result.scenario_total_modeled_cost ?? 0)}</span>
        {baseline && scenario && <span className="basis-full">Contract / estimated charges · baseline {formatNumber(baseline.governed_charge_count)} / {formatNumber(baseline.fallback_charge_count)} · scenario {formatNumber(scenario.governed_charge_count)} / {formatNumber(scenario.fallback_charge_count)}</span>}
        {result.original_published_baseline_cost != null && <span className="basis-full">Published baseline reference: {formatCurrency(result.original_published_baseline_cost)}</span>}
        {result.pricing_context?.pricing_basis === 'comparable_pinned_dated_contracts_v2_delivery_contracts' && <span className="basis-full">The published reference is stored unchanged; both comparison sides are re-rated with pinned DELIVERY contracts (v2).</span>}
      </>}
    </div>
  )
}
