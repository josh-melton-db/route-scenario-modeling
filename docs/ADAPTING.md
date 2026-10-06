# Adapting the accelerator

Start with the smallest useful slice. The optimization library, generator, API, UI, state layer, network planner, and depot router communicate through explicit models and can be adopted separately.

## Component selection

| Component | Can be reused independently? | Dependencies | Good starting use |
|---|---:|---|---|
| `route_opt` | Yes | Python, OR-Tools | Batch route optimization or experimentation |
| Synthetic generator | Yes | Faker, Pandas | Demos, tests, and contract fixtures |
| Lakebase state layer | Mostly | Lakebase, migrations | Scenarios, edits, run history, decisions |
| FastAPI backend | Yes | Store implementation | Stable API over a custom data store |
| React UI | Yes | Backend API contract | Planning experience over another backend |
| Network planning | Yes | Canonical network tables | Facility and assignment scenarios |
| Depot routing | Yes | Matrix provider and solver | Daily vehicle routing at one facility |
| Valhalla | External | Independent service | Directed road travel time and distance |

## Preserve the layer boundaries

```text
Unity Catalog / Lakehouse → governed analytical and planning inputs
Lakebase                  → scenarios, runs, edits, decisions
Databricks App            → FastAPI and React interaction layer
Model Serving / Valhalla  → optional compute behind stable interfaces
```

Use Unity Catalog for data that benefits from lineage, governance, historical processing, and analytical access. Use Lakebase for low-latency state that users create or edit. Keep routing and solver implementations replaceable behind their provider interfaces.

## Replace synthetic inputs

Migrate table by table:

1. Generate the synthetic dataset and inspect its values and relationships.
2. Map source fields into the canonical contracts in [Architecture and data contracts](ARCHITECTURE.md).
3. Preserve stable business identifiers for depots, customers, vehicles, orders, scenarios, and runs.
4. Validate coordinates, time windows, capacities, service times, effective dates, and currency units before solving.
5. Run the same scenario against synthetic and mapped inputs, then compare counts and constraint behavior.
6. Change the store or job configuration only after the mapped dataset passes the checks.

Keep customer-specific extraction rules outside the solver. Normalize them into canonical planning tables so network planning, depot routing, and the UI consume one contract.

### Supply and handling inputs

`facility_supply_daily` contains `capacity_plan_version_id`, `service_date`, `facility_id`, and `supply_units` for distribution centers. Supply units are fresh cases available for dispatch that day. `facility_capacity_daily` remains the daily handling-throughput bound for DCs and depots. Tie both inputs to the same published version and dates. For this demo, normal DC supply is generated at120% of normal handling capacity so introducing stock data does not create default shortages.

Scenario assumptions `facility_supply_retained_pct` and `facility_capacity_retained_pct` independently scale normal availability from0% to200%. Above100% simulates an increase in stock or throughput; creating or relocating facilities remains a separate future scenario. Depots do not create independent stock: incoming DC flow supplies their deliveries. AIR replenishment consumes donor stock and handling, uses its dated arrival, and respects destination handling. Alternate direct linehaul and customer reassignment bypass processing bottlenecks through existing eligible paths.

Bootstrap can add the supply table to an existing otherwise complete snapshot, deriving rows from its current canonical facilities, capacity versions, and dates. It preserves existing demand, rates, lanes, and repaired road coordinates. Older snapshots without stock inputs use an explicitly labeled handling-derived supply fallback. Replace that fallback with a complete dated supply feed for real deployments.

The generated daily-availability contract is deliberately small: stock is not accumulated between planning horizons. A production inventory implementation should add opening stock, receipts, reservations, and carryover explicitly rather than treating handling capacity as available inventory.

## Choose a state store

- Use the stub store for local development, tests, and a self-contained demo.
- Use Lakebase for concurrent users, durable runs, edits, and accepted decisions.
- Implement another store when Lakebase is outside your platform boundary; preserve the API models and durable run identities.

Lakebase migrations are application state migrations. Keep them independent from Lakehouse transformations and deploy them with the application lifecycle.

## Choose a solver and matrix provider

For initial adoption, use local OR-Tools with the approximate matrix. It is deterministic, inexpensive, and exposes the planning workflow without infrastructure dependencies.

Add providers when the business question requires them:

- local OR-Tools + approximate matrix for workshops and functional validation;
- local OR-Tools + Valhalla for road-aware routing with local solve compute;
- Model Serving + Valhalla for managed interactive solving and road matrices.
- Model Serving + region-mapped Valhalla with an explicit approximate fallback
  outside configured coverage (`serving_regional`).

Use a deployment JSON under `configs/deployment/` as the adaptation boundary.
`preset` controls whether the full planning job and pipeline are included. The
small idempotent network-bootstrap job is required by both presets because the
App reads canonical network tables. `routing`
selects the solver endpoint, Valhalla App, coverage manifest, costing, and
fallback behavior. Run `scripts/deploy-demo ... --dry-run` and inspect the staged
bundle before deploying a new workspace or changing a preset.

Store solver, matrix, fleet, cost, and coverage provenance with every result. Historical comparisons should retain the inputs and execution mode that produced them.

## Use the API or UI independently

The React application depends on the HTTP API contract, not Lakebase directly. You can replace the UI while keeping FastAPI, or implement the same endpoints over another store while keeping the React experience.

When adding fields, make them optional through a compatibility window and update fixtures, Python models, TypeScript types, and persistence together.

## Production execution

The in-process queues provide bounded concurrency, recovery, and a responsive accelerator experience. Treat them as accelerator-grade workers. For production workloads, submit durable work to Lakeflow Jobs and persist its external run identity with the application run. This provides independent scaling, retries, scheduling, access control, and operational history.

Review [Supported feature boundaries](FEATURE_BOUNDARIES.md) before representing the accelerator as a production planning system.
