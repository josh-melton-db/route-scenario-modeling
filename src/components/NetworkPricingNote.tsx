import type { NetworkScenarioResult } from '@/api/types'
import { formatCurrency, formatNumber } from '@/lib/format'

export function hasComparablePricing(result: NetworkScenarioResult) {
  return result.pricing_context?.pricing_basis === 'comparable_pinned_dated_contracts_v1'
}

export default function NetworkPricingNote({ result, detailed = false }: { result: NetworkScenarioResult; detailed?: boolean }) {
  if (!hasComparablePricing(result)) {
    return <p role="note" className="text-xs text-warning">Legacy pricing basis: baseline estimates and scenario charges may use different methods. Rerun this plan for a comparable cost comparison.</p>
  }
  const baseline = result.baseline_rate_coverage
  const scenario = result.scenario_rate_coverage
  return (
    <div role="note" aria-label="Comparison pricing basis" className="text-xs text-muted-foreground">
      <p>Comparable linehaul pricing: both plans use the same pinned, dated rate books and {formatNumber(result.pricing_context!.load_size_cases)}-case whole-load basis. Costs cover the selected network region, not optimized last-mile routes.</p>
      {detailed && <>
        <p className="mt-1">Baseline freight {formatCurrency(result.baseline_freight_total_cost ?? 0)} + tariffs {formatCurrency(result.baseline_tariff_total_cost ?? 0)} = {formatCurrency(result.baseline_total_modeled_cost ?? 0)}. Scenario freight {formatCurrency(result.freight_total_cost ?? 0)} + tariffs {formatCurrency(result.tariff_total_cost ?? 0)} = {formatCurrency(result.scenario_total_modeled_cost ?? 0)}.</p>
        {baseline && scenario && <p className="mt-1">Rate coverage · baseline: {formatNumber(baseline.governed_charge_count)} contract / {formatNumber(baseline.fallback_charge_count)} estimated charges · scenario: {formatNumber(scenario.governed_charge_count)} contract / {formatNumber(scenario.fallback_charge_count)} estimated charges. Uncovered lanes use the same estimation policy in both plans.</p>}
        {result.original_published_baseline_cost != null && <p className="mt-1">Original published baseline cost: {formatCurrency(result.original_published_baseline_cost)} (provenance only; not used to calculate the comparable delta).</p>}
        <p className="mt-1">The solver chooses allocations using dated linear full-load estimates; reported freight rounds to whole loads. Tariffs are charged on actual assigned cases.</p>
      </>}
    </div>
  )
}
