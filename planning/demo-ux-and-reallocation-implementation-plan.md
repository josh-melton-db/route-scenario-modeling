# Demo UX, rate coverage, and supply reallocation

## Outcomes

- Seed comprehensive published national rates; report only actual dated canonical coverage gaps.
- Make the As of date the confirmed reset entry point; remove standalone reset buttons while retaining progress, recovery, and warm-up feedback.
- Solve the first depot day automatically; leave future days unrequested until explicitly selected for optimization. Replace the date strip with a compact accessible calendar.
- Bound route list/map height, collapse unselected routes, and fit the map to the selected route.
- Restore the constraint-builder scenario tab using repository history and existing components; keep persistent daily scenarios and side-by-side comparison in the depot tab.
- Diagnose infeasibility before attributing it to coordinates. Validate bounded truck-road snapping and regeneration, preserving original/access metadata and rejecting truly unreachable matrices.
- Add shortage-context supply reallocation and percentage facility capacity, with real solver constraints and conserved supply. Ground linehaul is straight; express air transfers are arcs if confirmed.

## Confirmed choices

The user confirmed express-air DC transfers, retained percentage of normal daily capacity (100% normal, 50% half, 0% closed), and bounded road snapping with regeneration. Transfers must conserve source supply and respect arrival times and tariffs. Generated points retain original/snapped provenance and require truck reachability validation.

## Delegation

1. Wegener: national rate seed, dated match validation, regression tests.
2. Ohm: lazy daily jobs/API, infeasibility diagnosis and bounded reachability tooling.
3. Sagan: depot UI, route map/list sizing, calendar and restored constraint builder/comparison.
4. Banach: As of reset trigger, confirmation and standalone reset removal.
5. Kant: network capacity/transfer model, supply conservation and solver tests.
6. Chandrasekhar: shortage actions, capacity editor, transfer workflow and network map semantics.

Workers share the checkout and must preserve unrelated existing edits. Rate validation and transfer solver portions of network_scenarios.py have separate owners. Coordinate generation and depot API contracts through the integrator before overlapping edits.

## Verification

Run focused backend checks for actual published coverage, lazy scheduling/recovery, road reachability and supply conservation. Build/type-check the frontend after integration. Exercise first-day and on-demand solves, selection bounds, scenario comparison, confirmed reset and shortage-to-transfer flow. Use DEFAULT for any live dev verification authorized by the existing deployment task; never claim an infeasible solve as successful route feasibility. Preserve immutable historical results and explicit approximation provenance.

## Integration findings

- Default rate warnings previously counted non-Great-Lakes lanes rather than actual dated matches. All nine national books are now seeded and follow the configured demo-date anchor.
- Existing Lakebase constraints needed migration v16 to permit unrequested daily jobs. Live readiness confirmed the migration applied.
- A live strict-road solve rejected a 0.298-mile snap against the 0.250-mile limit. The bound remains enforced.
- Texas repair is scoped to validated depot IDs; the current dev snapshot has 300 covered customers. Other regions retain their existing coordinates and routing policy.
- Serverless notebook credentials redirected to Apps login. The repeatable repair uses an explicitly profiled local validator and a credential-free, source-hash-bound proof publisher. It revalidates final road-access coordinates and aborts before publication on unresolved inputs.
- A worker started a concurrent app deployment during the first acceptance run. All subsequent remote deployments are owned by the integrator and acceptance is paused during deployment.
- Current live evidence and limitations are recorded in `demo-ux-dev-verification.md`; browser verification requires an authenticated workspace browser session.
- Texas publication run `398992635550844` succeeded on DEFAULT: 300 covered generated customers validated, 10 regenerated, all final coordinates are revalidated road-access coordinates, maximum final snap 0.003 miles, and 300 delivery lanes refreshed. The publisher verified current source and repaired hashes before writing.
- Transfer model review caught imported cases bypassing retained DC throughput. A shared handling gate now caps normal, imported, and onward-transfer cases together. The correction was deployed as `01f1c19b70dc108eb30e33a52e68d080`; bootstrap run `879832234123374` succeeded. Separate generated supply/inventory data is a pending user choice for a positive stock-shortage transfer demonstration; air transfers cannot repair a pure handling bottleneck.
- Final integrated acceptance caught the transfer solver admitting unrelated national sources into regional solves. Its scope now matches the standard solver, with requested donor/destination DCs and their existing assigned demand included to reserve capacity. A regression proves an unused AIR request cannot open an unrelated regional source; all six transfer tests passed. Final redeployment and independent rerun are recorded in the verification report.
