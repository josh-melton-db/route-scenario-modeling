from __future__ import annotations

from typing import Any

from ..config import (
    get_data_backend,
    get_route_execution_mode,
    get_route_solver_endpoint,
    get_routing_coverage_manifest,
    get_sql_warehouse_id,
    get_sql_warehouse_name,
)
from .lakebase_migrations import migration_status
from .lakebase_store import lakebase_store
from .network_run_jobs import network_run_manager
from .depot_plan_jobs import depot_plan_job_manager
from .routing_coverage import RoutingCoverageError, validated_routing_coverages


def readiness_snapshot() -> tuple[bool, dict[str, Any]]:
    """Perform bounded local/config checks; avoid waking remote services on probes."""
    checks: dict[str, Any] = {}
    backend = get_data_backend()
    if backend == "lakebase":
        migration = migration_status()
        database_ok = False
        database_error: str | None = None
        try:
            database_ok = bool(lakebase_store.postgres.query_one("SELECT 1 AS ready"))
        except Exception:
            database_error = "Lakebase connectivity check failed."
        checks["lakebase"] = {
            "ready": database_ok and migration["state"] == "ready",
            "migration": migration,
            "message": database_error,
        }
    else:
        checks["lakebase"] = {"ready": True, "skipped": True, "backend": backend}

    warehouse_configured = bool(get_sql_warehouse_id() or get_sql_warehouse_name() or backend == "stub")
    checks["sql_warehouse"] = {"ready": warehouse_configured, "configured": warehouse_configured}

    route_mode = get_route_execution_mode()
    solver_configured = route_mode != "strict_serving_road" or bool(get_route_solver_endpoint(required=False))
    checks["route_solver"] = {
        "ready": solver_configured,
        "mode": route_mode,
        "endpoint": get_route_solver_endpoint(required=False) if solver_configured else None,
    }
    depot_workers_ready = not depot_plan_job_manager._closed
    checks["durable_workers"] = {
        "ready": depot_workers_ready and network_run_manager.max_workers > 0,
        "network_max_workers": network_run_manager.max_workers,
        "network_max_queued": network_run_manager.max_queued,
        "depot_workers": len(depot_plan_job_manager._workers),
    }
    try:
        coverages = validated_routing_coverages(get_routing_coverage_manifest())
        coverage_error = None
    except RoutingCoverageError:
        coverages = []
        coverage_error = "Routing coverage manifest is invalid."
    strict_required = route_mode in {"strict_serving_road", "local_road"}
    checks["routing_coverage"] = {
        "ready": bool(coverages) if strict_required else True,
        "validated": coverages,
        "supported_depot_ids": sorted(
            {depot for coverage in coverages for depot in coverage["depot_ids"]}
        ),
        "message": coverage_error,
    }
    ready = all(bool(check.get("ready")) for check in checks.values())
    return ready, {"status": "ready" if ready else "not_ready", "checks": checks}
