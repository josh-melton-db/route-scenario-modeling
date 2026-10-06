#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

required_vars=(DATABRICKS_CONFIG_PROFILE LAKEBASE_ENDPOINT PGHOST PGDATABASE PGUSER)
for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing ${var_name}. Copy .env.example to .env and set it." >&2
    exit 2
  fi
done

export DATA_BACKEND="${DATA_BACKEND:-lakebase}"
export LAKEBASE_APP_SCHEMA="${LAKEBASE_APP_SCHEMA:-route_scenario_modeling}"
export PGPORT="${PGPORT:-5432}"
export PGSSLMODE="${PGSSLMODE:-require}"
export ROUTE_EXECUTION_MODE="${ROUTE_EXECUTION_MODE:-approximate_development}"
export VALHALLA_ALLOW_HAVERSINE_FALLBACK="${VALHALLA_ALLOW_HAVERSINE_FALLBACK:-false}"

echo "Lakebase endpoint: ${LAKEBASE_ENDPOINT}"
echo "Lakebase database: ${PGDATABASE}"
echo "Databricks profile: ${DATABRICKS_CONFIG_PROFILE}"
echo "Routing mode: ${ROUTE_EXECUTION_MODE}"

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
