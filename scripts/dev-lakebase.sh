#!/usr/bin/env bash
set -euo pipefail

export DATA_BACKEND=lakebase
export LAKEBASE_APP_SCHEMA=route_scenario_modeling
export LAKEBASE_ENDPOINT=projects/route-scenario-modeling-lakebase/branches/dev/endpoints/primary
export PGHOST=ep-falling-paper-d8sfx79b.database.us-east-2.cloud.databricks.com
export PGPORT=5432
export PGDATABASE=route_scenario_modeling
export PGUSER=josh.melton@databricks.com
export PGSSLMODE=require
export DATABRICKS_CONFIG_PROFILE=DEFAULT
export DATABRICKS_AUTH_STORAGE=plaintext
export DATABRICKS_ROUTE_SOLVER_ENDPOINT=route-solver-dev

echo "Lakebase branch: projects/route-scenario-modeling-lakebase/branches/dev"
echo "Lakebase database: route_scenario_modeling"

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Missing .venv dependencies. Run: npm run setup:python"
  exit 1
fi

cleanup() {
  if [[ -n "${backend_pid:-}" ]]; then
    kill "$backend_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

.venv/bin/uvicorn backend.main:app --reload --host 127.0.0.1 --port 8002 &
backend_pid=$!
npm run dev
