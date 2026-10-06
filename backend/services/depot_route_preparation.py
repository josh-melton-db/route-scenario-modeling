"""Prepare saved depot defaults ahead of a demo or the start of a working day."""

from __future__ import annotations

import argparse
import json
import time
import threading
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def prepare_depot_routes(
    *, baseline: Any, plans: Any, service_date: str | None = None,
    timeout_seconds: float = 1800,
) -> dict[str, Any]:
    """Use the same full-horizon run identity as the UI; never overwrite results.

    First-day preparation is the default. A dated invocation also requests that
    day in each plan, leaving every other date lazy. Completed and infeasible
    results are reused by the normal idempotent plan service.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive.")
    snapshot = baseline.get_plan_run()
    selected_date = service_date or snapshot.scenario.horizon_start
    if not snapshot.scenario.horizon_start <= selected_date <= snapshot.scenario.horizon_end:
        raise ValueError(f"{selected_date} is outside the active planning horizon.")
    run_id = snapshot.result.run_id
    depot_ids = sorted({
        str(row["facility_id"]) for row in snapshot.network_rows["dim_facilities"]
        if row["facility_type"] == "depot"
    })
    # Use the bounded worker pool in small batches rather than flooding it with
    # all depots. Each batch finishes before admitting more work.
    deadline = time.monotonic() + timeout_seconds
    results: list[dict[str, Any]] = []
    for offset in range(0, len(depot_ids), 8):
        pending: dict[str, str] = {}
        for depot_id in depot_ids[offset:offset + 8]:
            if time.monotonic() >= deadline:
                raise TimeoutError("Depot route preparation timed out; saved results are retained.")
            try:
                plan = plans.get_or_create_plan(run_id, depot_id, priority_date=selected_date)
                plans.solve_day(plan.plan_set_id, selected_date)
                pending[depot_id] = plan.plan_set_id
            except Exception as exc:
                results.append({"depot_id": depot_id, "status": "failed", "error": str(exc)})
        while pending:
            for depot_id, plan_id in list(pending.items()):
                day = plans.get_day(plan_id, selected_date)
                if day.default_status in {"completed", "infeasible", "failed"}:
                    results.append({
                        "depot_id": depot_id, "plan_set_id": plan_id,
                        "status": day.default_status,
                        "result_id": day.default_result.result_id if day.default_result else None,
                        "error": day.error,
                    })
                    del pending[depot_id]
            if pending:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Depot route preparation timed out; saved results are retained.")
                plans.job_manager.wait_for_idle(timeout=min(1, max(0, deadline - time.monotonic())))
                # Another worker can own a durable job; don't spin when our pool
                # is idle but that job has not yet finished.
                time.sleep(0.05)
    return {
        "run_id": run_id, "service_date": selected_date, "depots": results,
        "ready": sum(row["status"] in {"completed", "infeasible"} for row in results),
        "failed": sum(row["status"] == "failed" for row in results),
    }


def prepare_active_depot_routes(**kwargs: Any) -> dict[str, Any]:
    from .baseline_service import baseline_service
    from .depot_plans import depot_plan_service

    return prepare_depot_routes(baseline=baseline_service, plans=depot_plan_service, **kwargs)


class DepotRoutePreparationManager:
    """Let a scheduled job request work through the running app's identity."""

    def __init__(self, prepare: Any = prepare_active_depot_routes) -> None:
        self.prepare = prepare
        self._lock = threading.RLock()
        self._status: dict[str, Any] = {}

    def start(self, service_date: str | None = None) -> dict[str, Any]:
        from fastapi import HTTPException
        from .demo_state_gate import demo_state_gate

        with demo_state_gate.admission(), self._lock:
            if self._status.get("state") == "running":
                if self._status["service_date"] != service_date:
                    raise HTTPException(status_code=409, detail="Another route preparation is running.")
                return dict(self._status)
            preparation_id = str(uuid.uuid4())
            self._status = {
                "preparation_id": preparation_id, "state": "running",
                "service_date": service_date, "report": None, "error": None,
            }
            threading.Thread(target=self._run, args=(service_date,),
                name="depot-route-preparation", daemon=True).start()
            return dict(self._status)

    def status(self, preparation_id: str) -> dict[str, Any]:
        from fastapi import HTTPException

        with self._lock:
            if self._status.get("preparation_id") != preparation_id:
                raise HTTPException(status_code=404, detail="Route preparation not found; retry preparation.")
            return dict(self._status)

    def is_running(self) -> bool:
        with self._lock:
            return self._status.get("state") == "running"

    def _run(self, service_date: str | None) -> None:
        try:
            report = self.prepare(service_date=service_date)
            with self._lock:
                self._status.update(state="failed" if report["failed"] else "completed", report=report)
        except Exception as exc:
            with self._lock:
                self._status.update(state="failed", error=str(exc))


depot_route_preparation_manager = DepotRoutePreparationManager()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-date", default="first", help="first, today, or YYYY-MM-DD")
    parser.add_argument("--timezone", default="America/Indiana/Indianapolis")
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    from ..config import get_data_backend

    if get_data_backend() != "lakebase":
        parser.error("Set DATA_BACKEND=lakebase so prepared routes survive this process.")
    selected_date = None if args.service_date == "first" else args.service_date
    if selected_date == "today":
        selected_date = datetime.now(ZoneInfo(args.timezone)).date().isoformat()
    elif selected_date is not None:
        from datetime import date
        selected_date = date.fromisoformat(selected_date).isoformat()
    report = prepare_active_depot_routes(service_date=selected_date, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2))
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
