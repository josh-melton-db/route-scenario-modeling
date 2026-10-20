# Network DELIVERY contract pricing

`NetworkScenarioAssumptions.use_delivery_contract_rates` defaults to `false`.
The network scenario editor exposes the same switch. It affects reporting only:
the optimizer's objective, costs, and allocated flows are not changed.

When enabled, each positive DELIVERY flow is quoted against published, dated
DELIVERY rules from the run's pinned contract snapshot. Customer endpoints are
resolved to their customer/market/territory identifiers before quoting. LINEHAUL
rules in a mixed contract cannot supply a DELIVERY quote. The lowest quoted cost
per case wins, with contract/version IDs breaking ties deterministically.

## Synthetic route and audit

- Route: 6 stops, 40 miles, period volume 1, commitment policy `honor`.
- Cases per stop: mean positive demand per customer stop for the lane's depot,
  customer, service date, and demand plan. If the lane has no positive demand,
  use that depot's positive customer-demand average for the same date and plan.
- Route cases: round `6 × cases_per_stop` to an integer, at least one case.
  No depot demand means no invented denominator: retain the planning estimate.
- Quote the synthetic route through `route_opt.rates.quote_contract`; divide its
  total by route cases, then multiply by assigned cases. Do not round the unit
  rate before multiplying. Round the lane total to cents.
- Scale the original charge lines by assigned cases / route cases. Reconcile
  cent rounding on the largest line so the ledger equals the lane freight total.
- `delivery_contract` records the selected contract/version, matched lane rule,
  snapshot, per-case rate, route inputs, and charge lines. An unmatched contract
  or missing demand uses `delivery_planning_fallback` with a planning charge line
  and a missing-rate warning. Zero flows remain zero and have no ledger entry.

Both comparison sides use the same option, frozen contracts, and dated tariffs.
Reassignment also reuses the parent snapshot. Coverage summaries count DELIVERY
contract and fallback entries in both memory and SQL audit paths.

## Versioned comparison scope

Off preserves v1 behavior, including the existing linehaul-only scenario
comparison/audit. On uses
`comparable_pinned_dated_contracts_v2_delivery_contracts` and includes LINEHAUL
and DELIVERY costs in the network comparison/audit; MARKET is an intermediate
layer and is not charged twice. The UI identifies the expanded cost scope and
explains that the published reference is not retroactively re-rated. Historical
saved results stay as stored. Assumptions and result/audit payloads are already
JSONB; no migration is needed.

## Demo evidence

Local stub scenarios, `DEMO_DATE_ANCHOR=2026-10-06`, one service day
2026-10-06, `REGION_TOLA`, default demand/capacity plans:

| Report | Off | On |
| --- | ---: | ---: |
| Scenario comparison total | $73,413.84 (v1 linehaul only) | $154,293.84 (v2 linehaul + delivery) |
| Baseline comparison total | $73,413.84 | $154,293.84 |
| Like-for-like linehaul + delivery cost rows | $123,104.89 | $154,293.84 |
| San Antonio DELIVERY cost rows | $7,861.85 | $13,480.00 |
| DELIVERY contract charge entries in comparison | 0 | 600 |
| Solver objective (national solve) | $639,575.47 | $639,575.47 |

The complete allocated flow rows are identical off/on. The off like-for-like
total adds $49,691.05 of existing planning DELIVERY estimates to the v1 comparison
total. This distinguishes a real pricing change from the expanded report scope.

The seed PR's unchanged-network-rating regression now explicitly passes the
option OFF. This preserves the seed's compatibility guarantee while permitting
the new, intentionally opt-in DELIVERY prices.
