from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from route_opt.demo_dates import demo_date_anchor


def get_catalog() -> str:
    return os.getenv("DATABRICKS_CATALOG", "demos")


def get_schema() -> str:
    return os.getenv("DATABRICKS_SCHEMA", "route_scenario_modeling")


def get_data_backend() -> str:
    return os.getenv("DATA_BACKEND", "stub").strip().lower() or "stub"


def get_demo_date_anchor():
    """Return the process-frozen synthetic snapshot data-as-of date."""

    return demo_date_anchor()


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


def get_route_solver_endpoint(*, required: bool = False) -> str:
    configured = os.getenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", "").strip()
    if required and not configured:
        raise RuntimeError(
            "DATABRICKS_ROUTE_SOLVER_ENDPOINT is required for strict route execution."
        )
    return configured or "route-solver-dev"


def get_route_execution_mode() -> str:
    """Resolve the dated depot execution path without silently weakening production."""

    configured = os.getenv("ROUTE_EXECUTION_MODE", "").strip().lower()
    aliases = {
        "strict": "strict_serving_road",
        "serving": "strict_serving_road",
        "local": "local_road",
        "approximate": "approximate_development",
    }
    configured = aliases.get(configured, configured)
    allowed = {
        "strict_serving_road",
        "local_road",
        "approximate_development",
    }
    if configured:
        if configured not in allowed:
            raise RuntimeError(
                "ROUTE_EXECUTION_MODE must be strict_serving_road, local_road, "
                "or approximate_development."
            )
        return configured
    return (
        "approximate_development"
        if get_data_backend() == "stub"
        else "strict_serving_road"
    )


def get_routing_coverage_manifest() -> str | None:
    value = os.getenv("ROUTING_COVERAGE_MANIFEST", "").strip()
    return value or None


def get_valhalla_app_url() -> str | None:
    value = os.getenv("VALHALLA_APP_URL", "").strip()
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        return value.rstrip("/")
    app = get_workspace_client().apps.get(name=value)
    resolved = str(app.url or "").strip()
    if not resolved.startswith(("http://", "https://")):
        raise RuntimeError(f"Databricks app {value!r} did not return a valid HTTPS URL.")
    return resolved.rstrip("/")


def get_valhalla_costing() -> str:
    return os.getenv("VALHALLA_COSTING", "truck").strip() or "truck"


def allow_haversine_fallback() -> bool:
    return os.getenv("VALHALLA_ALLOW_HAVERSINE_FALLBACK", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


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
