# Carrier-aware dated depot planning

Named dated scenarios can enable **Outsource stops when the contractor is cheaper**
under **Allow contracted overflow**. Both options default off. The API returns 422
with an explanatory message if cost-based outsourcing is requested without overflow.
Default/baseline and scheduled solves do not enable the option.

## Decision and accounting policy

The backend runs the private-fleet solve unchanged, then evaluates deterministic
post-solve swaps. It rebuilds ordered fleet routes with
`build_route_from_ordered_stops` and `route_cost`, ranks individual removal savings,
and considers singles plus the highest-saving prefixes of up to six stops globally
and per route. After each accepted swap it recomputes the marginal savings.
This is a greedy heuristic, not a globally optimal fleet/carrier assignment.

Each trial re-runs the existing overflow allocator on the original overflow orders
followed by the chosen stops. This preserves the frozen book, lane eligibility,
six-stop chunks, accessorials, carrier capacity and graduated volume consumption.
Existing contracted deliveries cannot be displaced. A swap is accepted only if
all chosen stops receive eligible quotes, total revenue is unchanged, and the
whole day's cost is strictly lower than the last accepted result. There is no
minimum savings margin beyond the existing cent-level currency precision.

Fleet capacity, receiving windows, waiting time, return travel and the tighter of
the vehicle/day route-duration limits are checked again after removal. Retained
stop order is unchanged. Empty fleet routes stay in the result: `route_cost`
charges the daily vehicle cost and a guaranteed regular shift even with zero
miles/minutes. Those costs are **not avoidable** in this implementation. They do
not become savings when a route is emptied.

The execution adapter passes the in-memory solve matrix to the postprocessor,
including partition matrices. It is not stored in results or sent to the serving
endpoint. Directed matrix distances/durations are reused for fleet repricing and
carrier chunk mileage when the required arcs are available. The development
adapter regenerates the same deterministic haversine matrix used by its solve.
When no matrix is exposed by a custom/legacy executor, both fleet alternatives
use the existing haversine/circuity builder; carrier chunks use that same estimator.
The original fleet cost is the accounting anchor. Any discrepancy between its
stored cost and the rebuilt estimate is retained as a mileage-cost calibration,
floored at zero, so it cannot erase guaranteed shift/vehicle costs. Execution
metadata records the matrix/estimate basis and fixed-cost policy; each carrier
quote records its mileage source. A cross-partition carrier chunk without all
matrix arcs retains the overflow allocator's explicitly identified mileage estimate.

Fleet KPIs exclude informational contracted routes. Day totals combine fleet
and carrier costs; outsourcing moves revenue between fleet and carrier, rather
than adding it twice. Day summaries and horizon rollups sum the recorded
outsourced-by-cost counts and savings. Contracted orders distinguish
`outsourced_by_cost` from `overflow`. Contracted routes have separate IDs, a sky-blue
map/list style and a Contracted badge; unserved deliveries remain warnings.
Contractor geometry/timing is informational, not a contractor vehicle schedule.

## San Antonio audit

The reproducible local audit uses the demo seed anchored at **2026-10-06**,
`DPT_TOLA_SAN_ANTONIO`, the full default fixture of **16 vehicles × 720 cases**
(600 minutes and 12 stops per route), overflow enabled, and no projected-period
volume override. Each day's single fleet solution is cloned for the off/on
comparison, eliminating solver-search variation between the two alternatives.

| October 6 metric | Cost-based option off | Cost-based option on |
| --- | ---: | ---: |
| Fleet stops | 100 | 100 |
| Contracted stops | 0 | 0 |
| Unserved stops | 0 | 0 |
| Fleet cost | $12,514.42 | $12,514.42 |
| Carrier cost | $0.00 | $0.00 |
| Total cost | $12,514.42 | $12,514.42 |
| Revenue | $47,893.75 | $47,893.75 |
| Outsourced-by-cost stops / savings | 0 / $0.00 | 0 / $0.00 |

Across **October 6–November 2 (28 days / 2,800 fleet stops)**, the option fires on
**0/28 days**, outsourcing **0 stops** and saving **$0.00**. The seeded carriers
are expensive relative to avoidable private-fleet costs, and the daily vehicle
and regular shift remain payable. This intentionally does not manufacture a
demo saving by changing the seed, dropping sunk costs, or weakening the comparison.
The focused tests demonstrate positive swaps, shared-minimum batching and cases
that remain on the fleet.

Reproduce the audit (local only):

```sh
DEMO_DATE_ANCHOR=2026-10-06 /Users/josh.melton/Desktop/route-scenario-modeling/.venv/bin/python -m pytest backend/tests/test_carrier_aware_demo.py -q -s
```

The audit prints the before/after counts and costs for every day, plus its firing
frequency. OR-Tools uses a timed search, so a new local solve can find a slightly
different fleet plan; each recorded off/on pair still shares exactly one source.

## Change boundary

This is a **two-way door**: disable the opt-in or revert the code. New fields live
in existing JSON results, with backward-compatible defaults; there is no migration.
The blast radius is dated named scenario postprocessing and contracted-route
presentation. There are no solver, serving-model, endpoint, classic-modeler,
network-flow, seed-data or rate-book/tier-semantic changes. Tests use local stub
data and synthetic matrices. No production routing service, live rate book,
workspace write or deployment is exercised.
