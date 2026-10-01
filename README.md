# Route Scenario Modeling

An end-to-end Databricks demo for **baseline route reconstruction** and **what-if scenario planning** on a multi-depot delivery network. Compare cost, service level, and route geometry side-by-side before changing fleet, depot, or customer assignments.

The stack is intentionally small and readable: synthetic data generation, a Lakeflow declarative pipeline, OR-Tools CVRPTW solving via MLflow Model Serving, Unity Catalog metric views, Lakebase-backed interactive state, and a React + FastAPI control app.

## How it works

1. **Generate synthetic network data** — depots, delivery accounts, fleet, and orders land in a Unity Catalog volume, then flow through bronze/silver/gold tables.
2. **Reconstruct baseline routes** — deterministic heuristics rebuild the “as-run” plan from historical orders.
3. **Build and apply scenarios** — controlled levers (fleet changes, new accounts, depot moves, delivery-day shifts) materialize planning partitions.
4. **Solve routes** — an OR-Tools CVRPTW model runs locally in batch jobs and interactively via a Model Serving endpoint.
5. **Compare and publish** — scenario KPIs, customer impacts, and metric views feed the app and downstream analytics.

One schema (`demos.route_scenario_modeling` by default), one orchestrated job, serverless compute throughout.

## Layout

```
notebooks/          pipeline notebooks (data gen → solve → compare → validate)
route_opt/          shared Python library (baseline, scenarios, solver, synthetic data)
pipelines/          Lakeflow declarative pipeline SQL (bronze / silver / gold)
backend/            FastAPI API + Lakebase store (with temporary UC fallback)
src/                React UI (baseline map, scenario builder, comparison views)
resources/          DAB job and pipeline definitions
databricks.yml      bundle config (app, warehouse, jobs)
app.yaml            Databricks App runtime config
```

## Run it

Prerequisites:

- Databricks workspace with Unity Catalog and serverless enabled
- A catalog you can write to (defaults to `demos`)
- `databricks` CLI configured
- Node 20+ and npm for the React build

```bash
npm install
npm run build

databricks bundle deploy --profile DEFAULT
databricks bundle run route_scenario_modeling_plan --profile DEFAULT

databricks apps start route-scenario-modeling-dev --profile DEFAULT
```

Grant the app service principal `SELECT` on the schema (see `notebooks/10_grant_app_permissions.py`).

### Lakebase interactive backend

The app defaults to `DATA_BACKEND=lakebase`. Deploy the app resource first so its
service principal creates and owns the `LAKEBASE_APP_SCHEMA`, then seed the new
project from an authenticated Lakebase client:

```bash
PYTHONPATH=. python -m backend.services.lakebase_seed --source uc
# Or start a new demo dataset:
PYTHONPATH=. python -m backend.services.lakebase_seed --source synthetic
```

The seed command applies idempotent migrations, validates reference-data row
counts and relationships, migrates existing scenarios/overrides when using
`--source uc`, and rebuilds baseline snapshots with `route_opt.baseline`.
Set `DATA_BACKEND=databricks` only for the temporary Unity Catalog rollback path.

Local development without a Databricks App:

```bash
npm install
pip install -r requirements.txt
npm run dev:all    # Vite on :5180, FastAPI on :8002 with stub data
```

The synthetic network uses a date anchor frozen when the backend process starts.
By default it starts near today's local date and covers 28 days. For a repeatable
demo, set `DEMO_DATE_ANCHOR=2026-09-30` before starting the backend. Demand,
capacity, data-as-of timestamps, and seeded rate validity use that same anchor;
saved network runs never move forward with the clock. Changing the anchor is a
deliberate fixture refresh, not a reset of accepted planning history.

### Network-to-depot planning

Run a network scenario, then click a depot in **Plan flow** to open its stored
daily route horizon. A named route scenario inherits optimized defaults and can
override operating assumptions on individual dates. **Release for reassignment**
proposes that another eligible depot serves selected cases; it does not cancel
demand or immediately change the old routes. **Rerun network with releases**
creates a new immutable parent run, leaving the old network and depot plans
available for comparison. Eligibility in the demo is a labeled deterministic
nearby/same-region assumption, not a customer-provided territory policy.

On a solved network run, **Propose as baseline** and then **Accept as baseline**
changes the default network shown on the main page. Local route readiness is
reported separately and does not block network acceptance. **Reset to original
story** restores the original baseline pointer after confirmation, retaining
accepted revisions and historical plans. Promotion from a stale source baseline
requires a new scenario based on the active revision.

### Comparable tariff pricing and road-network execution

New network results price unchanged baseline flows and scenario flows using the
same frozen, dated rate-book inputs, 900-case whole-load rules, and symmetric
fallback estimates. Existing baseline tariffs and proposed scenario tariffs are
charged separately. The rate audit can switch between the comparable baseline
and scenario; original published costs remain provenance, not the savings basis.
Comparison KPIs and charges share the selected region's linehaul scope. They do
not include optimized last-mile costs. The assignment objective uses dated linear
full-load estimates; reported freight rounds to whole loads. Legacy runs are not
rewritten and are explicitly labeled when their pricing basis differs.

Network-linked daily routing supports these explicit execution modes:

- `strict_serving_road`: validated Valhalla truck coverage and Model Serving;
  default for non-stub backends. No silent distance/local-solver fallback.
- `local_road`: the same validated road matrix with local OR-Tools.
- `approximate_development`: local OR-Tools with approximate travel assumptions;
  default for stub development, clearly labeled in the UI.

Set `ROUTE_EXECUTION_MODE` to override the default. Road modes require
`ROUTING_COVERAGE_MANIFEST`; strict mode additionally requires
`DATABRICKS_ROUTE_SOLVER_ENDPOINT`. Pin exact-depot fleet, route costs, and supported
customer/vehicle constraints when creating the depot plan. Missing strict-mode
resources or unsupported inputs produce explicit errors rather than substituting
the synthetic fleet. The stored day result shows the solver, matrix, coverage
artifact, and fleet/cost provenance.

The dated adapter currently rejects carrier fallback/contracts, required
vehicle/equipment matching, and explicit shift-clock/route-start constraints
rather than ignoring them. Supported receiving windows, service times, vehicle
capacity, route duration/stop limits, breaks, and pinned costs reach the solver.
These adapter boundaries are distinct from the original legacy route workflow.

The Texas manifest in `routing_coverage_samples/texas-candidates.v1.json` is a
candidate template for Dallas and San Antonio, **not provisioned coverage**.
Copy it into an operator-owned deployment file, replace endpoint/artifact/build
metadata, and run the smoke check against the actual service before enabling it.
Set the bundle variable `routing_coverage_manifest` to that deployed file path.
Bounds checks do not guarantee routability: every solve validates the full
directed matrix and rejects unreachable or misaligned arcs. Changed stops are
checked again. Matrix caching is currently disabled.

Valhalla tooling is in a separate repository tracked at `valhalla_poc`. A fresh
checkout needs `git submodule update --init valhalla_poc` (or clone with
`--recurse-submodules`). Changes inside it must be committed there before a parent
gitlink update can publish those changes; the parent commit alone is insufficient.
The new setup/check tooling requires the updated Valhalla repository revision.

To inspect a Texas setup request without making platform calls:

```bash
scripts/setup-valhalla-extract texas \
  --coverage-id texas-delivery --artifact-version tx-v1 \
  --volume-path '/Volumes/<catalog>/<schema>/<volume>' \
  --cluster-id '<authorized-cluster-id>' \
  --notebook-path '/Workspace/<path>/build_valhalla'
```

Replace the placeholders with your values. Execution additionally requires
`--execute --profile <chosen-profile>`; no profile is inferred. Existing engine
assets can be reused; rebuilding the engine is an explicit option. Once the
matching region/artifact is deployed, `scripts/check-valhalla-coverage` checks
artifact identity and reachable bidirectional truck matrix cells and records the
result in the manifest. See `valhalla_poc/README.md` for configuration and examples.
The smoke command requires `--profile <chosen-profile>` for authenticated managed
Apps, or explicit `--unauthenticated` for local/public endpoints. Each mapped
managed App endpoint needs `CAN_USE` permission; the solver endpoint needs
`CAN_QUERY`. The bundle grants these for its configured Valhalla App and solver,
not automatically for additional mapped endpoints.
No Texas tiles, live endpoints, or workspace permissions were provisioned as part
of the code implementation.

Run the focused browser checks against an already-running local frontend without
starting or stopping any local apps:

```bash
E2E_BASE_URL=http://localhost:5180 npx playwright test --config playwright.local.config.ts e2e/network-lifecycle.spec.ts e2e/depot-horizon.spec.ts e2e/network-parent-navigation.spec.ts
```

To run locally against the isolated Lakebase `dev` branch using the `DEFAULT`
Databricks profile:

```bash
npm run setup:python
npm run dev:lakebase
```

The launcher uses OAuth credential refresh and contains no database password.
It targets `projects/route-scenario-modeling-lakebase/branches/dev`; the protected
`production` branch is not modified by local development.

## Scenario types

The demo ships with representative scenario levers:

- Baseline identity (no changes)
- Fleet reduction
- New account groups (M&A and organic growth)
- Delivery-day changes
- Depot relocation

Swap `notebooks/00_generate_synthetic_data.py` for your own ingest once real depot, account, fleet, and order tables are available — the downstream pipeline and app stay the same.
