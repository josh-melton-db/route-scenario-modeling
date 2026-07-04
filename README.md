# Route Scenario Modeling

An end-to-end Databricks demo for **baseline route reconstruction** and **what-if scenario planning** on a multi-depot delivery network. Compare cost, service level, and route geometry side-by-side before changing fleet, depot, or customer assignments.

The stack is intentionally small and readable: synthetic data generation, a Lakeflow declarative pipeline, OR-Tools CVRPTW solving via MLflow Model Serving, Unity Catalog metric views, and a React + FastAPI control app.

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
backend/            FastAPI API + Databricks SQL store
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

Local development without a Databricks App:

```bash
npm install
pip install -r requirements.txt
npm run dev:all    # Vite on :5173, FastAPI on :8001 with stub data
```

## Scenario types

The demo ships with representative scenario levers:

- Baseline identity (no changes)
- Fleet reduction
- New account groups (M&A and organic growth)
- Delivery-day changes
- Depot relocation

Swap `notebooks/00_generate_synthetic_data.py` for your own ingest once real depot, account, fleet, and order tables are available — the downstream pipeline and app stay the same.
