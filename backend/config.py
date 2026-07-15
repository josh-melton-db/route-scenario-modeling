from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def get_catalog() -> str:
    return os.getenv("DATABRICKS_CATALOG", "demos")


def get_schema() -> str:
    return os.getenv("DATABRICKS_SCHEMA", "route_scenario_modeling")


def get_data_backend() -> str:
    return os.getenv("DATA_BACKEND", "stub").strip().lower() or "stub"


def get_lakebase_schema() -> str:
    return os.getenv("LAKEBASE_APP_SCHEMA", "route_scenario_modeling").strip() or "route_scenario_modeling"


def get_lakebase_endpoint() -> str | None:
    value = os.getenv("LAKEBASE_ENDPOINT", "").strip()
    return value or None


def get_lakebase_pool_min_size() -> int:
    return max(1, int(os.getenv("LAKEBASE_POOL_MIN_SIZE", "1")))


def get_lakebase_pool_max_size() -> int:
    return max(get_lakebase_pool_min_size(), int(os.getenv("LAKEBASE_POOL_MAX_SIZE", "5")))


def get_lakebase_connect_retries() -> int:
    return max(1, int(os.getenv("LAKEBASE_CONNECT_RETRIES", "4")))


def get_lakebase_connect_timeout_seconds() -> int:
    return max(1, int(os.getenv("LAKEBASE_CONNECT_TIMEOUT_SECONDS", "10")))


def get_sql_warehouse_id() -> str | None:
    value = os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", "").strip()
    return value or None


def get_sql_warehouse_name() -> str | None:
    value = os.getenv("DATABRICKS_SQL_WAREHOUSE_NAME", "").strip()
    return value or None


def get_route_solver_endpoint() -> str:
    return os.getenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", "route-solver-dev").strip() or "route-solver-dev"


def get_stub_dir() -> Path:
    configured = os.getenv("STUB_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).parent / "stubs"


def get_run_queued_duration() -> float:
    return float(os.getenv("RUN_QUEUED_DURATION_SECONDS", "1.5"))


def get_run_running_duration() -> float:
    return float(os.getenv("RUN_RUNNING_DURATION_SECONDS", "4.0"))


@lru_cache(maxsize=1)
def get_workspace_client():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()
