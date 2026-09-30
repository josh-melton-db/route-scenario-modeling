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
