from __future__ import annotations

import hashlib
import json
import re
import uuid
import threading
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any

from route_opt.cost import CostParameters
from route_opt.depot_planning import materialize_depot_targets

from ..depot_plan_models import DayDetail, PlanSet, RouteScenario
from ..config import get_route_execution_mode
from .depot_route_execution import dated_route_executor
from .depot_plan_jobs import DepotPlanJobManager, JobKey, depot_plan_job_manager
from .depot_plan_repository import depot_plan_repository
from .network_scenarios import network_scenario_service
from .store_provider import get_store


DEFAULT_SCENARIO_ID = "default"
FINISHED_STATUSES = {"completed", "infeasible"}
PENDING_STATUSES = {"queued", "running"}
MAX_ROUTE_SCENARIOS_PER_PLAN = 20
MAX_PENDING_OVERRIDE_JOBS_PER_PLAN = 20


class DepotPlanService:
    def __init__(
        self,
        *,
        repository: object,
        snapshot_provider: Callable[[str], object],
        fleet_provider: Callable[
            [object, str],
            Sequence[Mapping[str, object]]
            | tuple[Sequence[Mapping[str, object]], str],
        ]
        | None = None,
        solver: Callable[..., dict[str, object]] = dated_route_executor,
        job_manager: DepotPlanJobManager = depot_plan_job_manager,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.snapshot_provider = snapshot_provider
        self.fleet_provider = fleet_provider or _default_fleet_provider
        self.solver = solver
        self.job_manager = job_manager
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.worker_id = f"depot-worker-{uuid.uuid4()}"

    def get_or_create_plan(
        self,
        run_id: str,
        depot_id: str,
        priority_date: str | date | None = None,
    ) -> PlanSet:
        existing = self.repository.find(run_id, depot_id)
        if existing is not None:
            self._queue_pending_record(existing, priority_date=priority_date)
            return self.get_plan(str(existing["plan_set_id"]))

        snapshot = self.snapshot_provider(run_id)
        horizon_start, horizon_end = _snapshot_horizon(snapshot)
        dates = _date_range(horizon_start, horizon_end)
        priority_date_text = _optional_date_text(priority_date)
        if priority_date_text is not None and priority_date_text not in dates:
            raise ValueError("priority_date must be inside the parent run horizon.")

        network_rows, customer_constraint_snapshot = _freeze_customer_constraints(
            _snapshot_value(snapshot, "network_rows"), depot_id
        )
        flow_rows = list(_snapshot_value(snapshot, "flow_rows"))
        daily_targets = {
            service_date: materialize_depot_targets(network_rows, flow_rows, depot_id, service_date)
            for service_date in dates
        }
        depot_target = daily_targets[priority_date_text or dates[0]]
        fleet_value = (
            self.fleet_provider(snapshot, depot_id)
            if any(int(target["assigned_cases"]) > 0 for target in daily_targets.values())
            else ([], "not_required_no_work", [], "not_required_no_work")
        )
        frozen_cost_rows: list[dict[str, object]] = []
        cost_resource_source = "snapshot:none"
        if isinstance(fleet_value, tuple) and len(fleet_value) == 4:
            fleet_rows, resource_source, cost_rows, cost_resource_source = fleet_value
            frozen_cost_rows = [dict(row) for row in cost_rows]
        elif isinstance(fleet_value, tuple):
            fleet_rows, resource_source = fleet_value
            frozen_cost_rows, cost_resource_source = _snapshot_cost_rows(snapshot)
        else:
            fleet_rows, resource_source = fleet_value, "injected_fleet"
            frozen_cost_rows, cost_resource_source = _snapshot_cost_rows(snapshot)
        fleet = [dict(row) for row in fleet_rows]
        if get_route_execution_mode() == "strict_serving_road" and _fleet_source_is_unpinned(
            str(resource_source)
        ):
            raise ValueError(
                "Strict route execution requires a real pinned fleet source; "
                f"received {resource_source!r}."
            )
        frozen_fleet = [deepcopy(row) for row in fleet]
        fleet_snapshot = _fleet_snapshot_provenance(frozen_fleet, str(resource_source))
        cost_snapshot = _cost_snapshot_provenance(
            frozen_cost_rows, str(cost_resource_source)
        )
        plan_set_id = f"depot-plan-{uuid.uuid4()}"
        created_at = self._timestamp()
        record: dict[str, object] = {
            "plan_set_id": plan_set_id,
            "parent_run_id": run_id,
            "depot": depot_target["depot"],
            "horizon_start": horizon_start,
            "horizon_end": horizon_end,
            "resource_source": resource_source,
            "fleet": frozen_fleet,
            "fleet_snapshot": fleet_snapshot,
            "customer_constraint_snapshot": customer_constraint_snapshot,
            "route_cost_parameters": deepcopy(frozen_cost_rows),
            "cost_resource_source": cost_resource_source,
            "cost_snapshot": cost_snapshot,
            "scenarios": {
                DEFAULT_SCENARIO_ID: {
                    "route_scenario_id": DEFAULT_SCENARIO_ID,
                    "scenario_name": "Optimized default",
                    "is_default": True,
                }
            },
            "days": {},
            "created_at": created_at,
            "updated_at": created_at,
        }
        for service_date in dates:
            targets = daily_targets[service_date]
            job_id = f"default-{service_date}"
            default_status = (
                "queued" if service_date == horizon_start else "not_requested"
            )
            record["days"][service_date] = {
                "service_date": service_date,
                "assigned_cases": int(targets["assigned_cases"]),
                "default_status": default_status,
                "default_result_id": None,
                "results": {},
                "selected_result_ids": {},
                "latest_override_job_ids": {},
                "override_statuses": {},
                "override_errors": {},
                "jobs": {
                    job_id: {
                        "job_id": job_id,
                        "route_scenario_id": DEFAULT_SCENARIO_ID,
                        "status": default_status,
                        "request": None,
                    }
                },
                "error": None,
            }

        try:
            created = self.repository.create(record)
        except Exception:
            existing = self.repository.find(run_id, depot_id)
            if existing is None:
                raise
            created = existing
        self._queue_pending_record(created, priority_date=priority_date_text)
        return self.get_plan(str(created["plan_set_id"]))

    def solve_day(
        self, plan_set_id: str, service_date: str | date
    ) -> DayDetail:
        """Idempotently request the default solve for one horizon day."""
        service_date_text = _date_text(service_date)
        job_id = f"default-{service_date_text}"
        should_submit = False

        def request_default(day: dict[str, object]) -> None:
            nonlocal should_submit
            current = str(day.get("default_status", "not_requested"))
            if current in PENDING_STATUSES | FINISHED_STATUSES:
                return
            job = day.setdefault("jobs", {}).setdefault(
                job_id,
                {
                    "job_id": job_id,
                    "route_scenario_id": DEFAULT_SCENARIO_ID,
                    "request": None,
                },
            )
            job.update(status="queued", error=None, retryable=False, retry_at=None)
            day["default_status"] = "queued"
            day["error"] = None
            should_submit = True

        self._mutate_day(plan_set_id, service_date_text, request_default)
        if should_submit:
            self._submit_job(
                plan_set_id,
                service_date_text,
                DEFAULT_SCENARIO_ID,
                job_id,
                None,
                priority=0,
            )
        return self.get_day(plan_set_id, service_date_text)

    def get_plan(
        self, plan_set_id: str, route_scenario_id: str = DEFAULT_SCENARIO_ID
    ) -> PlanSet:
        record = self.repository.get(plan_set_id)
        _require_scenario(record, route_scenario_id)
        payload = _plan_set_payload(record, route_scenario_id)
        return PlanSet.model_validate(payload)

    def get_day(
        self,
        plan_set_id: str,
        service_date: str | date,
        route_scenario_id: str = DEFAULT_SCENARIO_ID,
    ) -> DayDetail:
        record = self.repository.get(plan_set_id)
        service_date_text = _date_text(service_date)
        _require_scenario(record, route_scenario_id)
        day = _require_day(record, service_date_text)
        return DayDetail.model_validate(
            _day_detail_payload(record, day, route_scenario_id)
        )

    def list_day_results(
        self,
        plan_set_id: str,
        service_date: str | date,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, object]:
        service_date_text = _date_text(service_date)
        lister = getattr(self.repository, "list_results", None)
        if callable(lister):
            return lister(
                plan_set_id, service_date_text, limit=limit, offset=offset
            )
        record = self.repository.get(plan_set_id)
        day = _require_day(record, service_date_text)
        results = sorted(
            day.get("results", {}).values(),
            key=lambda result: str(result.get("created_at", "")),
            reverse=True,
        )
        return {
            "items": results[offset:offset + limit],
            "total": len(results),
            "limit": limit,
            "offset": offset,
        }

    def list_result_routes(
        self,
        plan_set_id: str,
        result_id: str,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, object]:
        lister = getattr(self.repository, "list_result_routes", None)
        if not callable(lister):
            raise RuntimeError("Selected depot repository cannot page result routes.")
        return lister(plan_set_id, result_id, limit=limit, offset=offset)

    def create_scenario(self, plan_set_id: str, scenario_name: str) -> RouteScenario:
        name = scenario_name.strip()
        if not name:
            raise ValueError("scenario_name is required.")
        route_scenario_id = f"route-scenario-{uuid.uuid4()}"

        def add_scenario(record: dict[str, object]) -> None:
            if len(record["scenarios"]) >= MAX_ROUTE_SCENARIOS_PER_PLAN:
                raise ValueError(
                    f"A depot plan supports at most {MAX_ROUTE_SCENARIOS_PER_PLAN} route scenarios."
                )
            record["scenarios"][route_scenario_id] = {
                "route_scenario_id": route_scenario_id,
                "scenario_name": name,
                "is_default": False,
            }
            record["updated_at"] = self._timestamp()

        record = self.repository.mutate(plan_set_id, add_scenario)
        return RouteScenario.model_validate(record["scenarios"][route_scenario_id])

    def optimize_day(
        self,
        plan_set_id: str,
        service_date: str | date,
        request: object,
    ) -> DayDetail:
        request_payload = _request_payload(request)
        route_scenario_id = str(request_payload.get("route_scenario_id", ""))
        if not route_scenario_id or route_scenario_id == DEFAULT_SCENARIO_ID:
            raise ValueError("A named route_scenario_id is required for an override.")
        service_date_text = _date_text(service_date)
        job_id = f"override-{route_scenario_id}-{uuid.uuid4()}"

        current = self.repository.get(plan_set_id)
        _require_scenario(current, route_scenario_id, named=True)
        pending_overrides = sum(
            1
            for candidate_day in current["days"].values()
            for candidate_job in candidate_day["jobs"].values()
            if candidate_job.get("route_scenario_id") != DEFAULT_SCENARIO_ID
            and candidate_job.get("status") in PENDING_STATUSES
        )
        if pending_overrides >= MAX_PENDING_OVERRIDE_JOBS_PER_PLAN:
            raise ValueError(
                f"A depot plan supports at most {MAX_PENDING_OVERRIDE_JOBS_PER_PLAN} "
                "queued or running override jobs."
            )

        def queue_override(day: dict[str, object]) -> None:
            day.setdefault("latest_override_job_ids", {})
            day["override_statuses"][route_scenario_id] = "queued"
            day["override_errors"][route_scenario_id] = None
            day["latest_override_job_ids"][route_scenario_id] = job_id
            day["jobs"][job_id] = {
                "job_id": job_id,
                "route_scenario_id": route_scenario_id,
                "status": "queued",
                "request": request_payload,
            }

        self._mutate_day(plan_set_id, service_date_text, queue_override)
        self._submit_job(
            plan_set_id,
            service_date_text,
            route_scenario_id,
            job_id,
            request_payload,
            priority=0,
        )
        return self.get_day(plan_set_id, service_date_text, route_scenario_id)

    def reset_day_override(
        self,
        plan_set_id: str,
        route_scenario_id: str,
        service_date: str | date,
    ) -> DayDetail:
        if route_scenario_id == DEFAULT_SCENARIO_ID:
            raise ValueError("The default scenario cannot be reset.")
        service_date_text = _date_text(service_date)

        current = self.repository.get(plan_set_id)
        _require_scenario(current, route_scenario_id, named=True)

        def reset(day: dict[str, object]) -> None:
            day.setdefault("latest_override_job_ids", {})
            day["selected_result_ids"].pop(route_scenario_id, None)
            day["override_statuses"].pop(route_scenario_id, None)
            day["override_errors"].pop(route_scenario_id, None)
            day["latest_override_job_ids"].pop(route_scenario_id, None)
            for job in day["jobs"].values():
                if (
                    str(job.get("route_scenario_id")) == route_scenario_id
                    and str(job.get("status")) in PENDING_STATUSES
                ):
                    job["discard_selection"] = True

        self._mutate_day(plan_set_id, service_date_text, reset)
        return self.get_day(plan_set_id, service_date_text, route_scenario_id)

    def recover_pending_plans(self) -> int:
        queued = 0
        for record in self.repository.list_pending():
            queued += self._queue_pending_record(record)
        return queued

    def _queue_pending_record(
        self,
        record: Mapping[str, object],
        *,
        priority_date: str | date | None = None,
    ) -> int:
        priority_date_text = _optional_date_text(priority_date)
        pending: list[tuple[int, str, str, str, dict[str, object] | None]] = []
        for service_date, day in record["days"].items():
            for job_id, job in day["jobs"].items():
                if str(job["status"]) not in PENDING_STATUSES:
                    continue
                priority = 0 if service_date == priority_date_text else 100
                pending.append(
                    (
                        priority,
                        str(service_date),
                        str(job["route_scenario_id"]),
                        str(job_id),
                        deepcopy(job.get("request")),
                    )
                )
        submitted = 0
        for priority, service_date, scenario_id, job_id, request in sorted(pending):
            submitted += int(
                self._submit_job(
                    str(record["plan_set_id"]),
                    service_date,
                    scenario_id,
                    job_id,
                    request,
                    priority=priority,
                )
            )
        return submitted

    def _submit_job(
        self,
        plan_set_id: str,
        service_date: str,
        route_scenario_id: str,
        job_id: str,
        request: dict[str, object] | None,
        *,
        priority: int,
    ) -> bool:
        key: JobKey = (plan_set_id, service_date, route_scenario_id, job_id)
        return self.job_manager.submit(
            key,
            lambda: self._execute_job(
                plan_set_id,
                service_date,
                route_scenario_id,
                job_id,
                request,
            ),
            priority=priority,
        )

    def _execute_job(
        self,
        plan_set_id: str,
        service_date: str,
        route_scenario_id: str,
        job_id: str,
        request: dict[str, object] | None,
    ) -> None:
        claim = getattr(self.repository, "claim_job", None)
        attempt = (
            claim(plan_set_id, service_date, job_id, self.worker_id)
            if callable(claim)
            else 1
        )
        if attempt is None:
            return

        def mark_running(day: dict[str, object]) -> None:
            job = day["jobs"].get(job_id)
            if job is None or str(job["status"]) in FINISHED_STATUSES | {"failed"}:
                return
            job["status"] = "running"
            job["attempt_count"] = attempt
            job["worker_id"] = self.worker_id
            job["lease_expires_at"] = (
                self.now() + timedelta(seconds=600)
            ).isoformat()
            if route_scenario_id == DEFAULT_SCENARIO_ID:
                day["default_status"] = "running"
            else:
                day["override_statuses"][route_scenario_id] = "running"

        running_record = self._mutate_day(plan_set_id, service_date, mark_running)
        day = _require_day(running_record, service_date)
        job = day["jobs"].get(job_id)
        if job is None or str(job["status"]) != "running":
            return

        try:
            heartbeat_stop = threading.Event()
            heartbeat = getattr(self.repository, "heartbeat_job", None)
            heartbeat_thread = threading.Thread(
                target=_heartbeat_loop,
                args=(heartbeat_stop, heartbeat, plan_set_id, job_id, self.worker_id),
                daemon=True,
            ) if callable(heartbeat) else None
            if heartbeat_thread is not None:
                heartbeat_thread.start()
            snapshot = self.snapshot_provider(str(running_record["parent_run_id"]))
            network_rows = deepcopy(_snapshot_value(snapshot, "network_rows"))
            network_rows = _apply_customer_constraint_snapshot(
                network_rows, running_record.get("customer_constraint_snapshot")
            )
            flow_rows = list(_snapshot_value(snapshot, "flow_rows"))
            fleet = [deepcopy(row) for row in running_record["fleet"]]
            _verify_fleet_snapshot(fleet, running_record.get("fleet_snapshot"))
            frozen_cost_rows = running_record.get("route_cost_parameters")
            if frozen_cost_rows is None:
                # Compatibility for records created before route inputs were frozen.
                frozen_cost_rows, legacy_cost_source = _snapshot_cost_rows(snapshot)
            else:
                legacy_cost_source = str(
                    running_record.get("cost_resource_source") or "legacy_snapshot"
                )
            _verify_cost_snapshot(
                frozen_cost_rows, running_record.get("cost_snapshot")
            )
            cost_parameters, cost_parameter_source = _route_cost_parameters(
                frozen_cost_rows,
                str(running_record["depot"]["depot_id"]),
                service_date,
                strict=(
                    get_route_execution_mode() == "strict_serving_road"
                    and int(day["assigned_cases"]) > 0
                ),
                source=legacy_cost_source,
            )
            if request:
                fleet, network_rows, cost_parameters = _apply_override(
                    fleet,
                    network_rows,
                    str(running_record["depot"]["depot_id"]),
                    service_date,
                    request,
                    cost_parameters,
                )
                flow_rows.extend(network_rows.pop("__daily_override_flow_rows", []))
            solved = self.solver(
                network_rows=network_rows,
                flow_rows=flow_rows,
                depot_id=str(running_record["depot"]["depot_id"]),
                service_date=service_date,
                fleet=fleet,
                scenario_id=f"{plan_set_id}:{route_scenario_id}",
                cost_parameters=cost_parameters,
            )
            execution = solved.get("execution")
            if isinstance(execution, dict):
                execution["resource_source"] = running_record["resource_source"]
                execution["fleet_snapshot"] = deepcopy(
                    running_record.get("fleet_snapshot")
                    or _fleet_snapshot_provenance(
                        fleet, str(running_record["resource_source"])
                    )
                )
                execution["customer_constraint_snapshot"] = deepcopy(
                    running_record.get("customer_constraint_snapshot")
                )
                execution["cost_parameter_source"] = cost_parameter_source
                execution["cost_snapshot"] = deepcopy(
                    running_record.get("cost_snapshot")
                    or _cost_snapshot_provenance(
                        frozen_cost_rows, legacy_cost_source
                    )
                )
                execution["job_attempt"] = attempt
            result = _day_result(solved, service_date, self._timestamp())
        except Exception as exc:
            if "heartbeat_stop" in locals():
                heartbeat_stop.set()
            if "heartbeat_thread" in locals() and heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1)
            self._store_failure(
                plan_set_id,
                service_date,
                route_scenario_id,
                job_id,
                str(exc),
                retryable=_is_transient_route_error(exc) and attempt < 3,
                attempt=attempt,
            )
            return
        if heartbeat_thread is not None:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)

        def store_result(current_day: dict[str, object]) -> None:
            current_job = current_day["jobs"].get(job_id)
            if current_job is None:
                return
            result_id = str(result["result_id"])
            current_day["results"][result_id] = result
            current_job["status"] = str(result["status"])
            current_job["result_id"] = result_id
            if route_scenario_id == DEFAULT_SCENARIO_ID:
                current_day["default_status"] = str(result["status"])
                current_day["default_result_id"] = result_id
                current_day["error"] = None
            else:
                current_day.setdefault("latest_override_job_ids", {})
                is_latest = (
                    current_day["latest_override_job_ids"].get(route_scenario_id)
                    == job_id
                )
                if is_latest and not current_job.get("discard_selection"):
                    current_day["override_statuses"][route_scenario_id] = str(
                        result["status"]
                    )
                    current_day["override_errors"][route_scenario_id] = None
                    current_day["selected_result_ids"][route_scenario_id] = result_id

        self._mutate_day(plan_set_id, service_date, store_result)

    def _store_failure(
        self,
        plan_set_id: str,
        service_date: str,
        route_scenario_id: str,
        job_id: str,
        message: str,
        *,
        retryable: bool = False,
        attempt: int = 1,
    ) -> None:
        def fail(day: dict[str, object]) -> None:
            job = day["jobs"].get(job_id)
            if job is not None:
                job["status"] = "queued" if retryable else "failed"
                job["error"] = message
                job["retryable"] = retryable
                job["retry_at"] = (
                    self.now() + timedelta(seconds=min(30 * (2 ** (attempt - 1)), 300))
                ).isoformat() if retryable else None
            if route_scenario_id == DEFAULT_SCENARIO_ID:
                day["default_status"] = "queued" if retryable else "failed"
                day["error"] = message
            else:
                day.setdefault("latest_override_job_ids", {})
                is_latest = (
                    day["latest_override_job_ids"].get(route_scenario_id) == job_id
                )
                if is_latest and not (job or {}).get("discard_selection"):
                    day["override_statuses"][route_scenario_id] = (
                        "queued" if retryable else "failed"
                    )
                    day["override_errors"][route_scenario_id] = message

        self._mutate_day(plan_set_id, service_date, fail)

    def _mutate_day(
        self,
        plan_set_id: str,
        service_date: str,
        callback: Callable[[dict[str, object]], None],
    ) -> dict[str, object]:
        mutate_day = getattr(self.repository, "mutate_day", None)
        if callable(mutate_day):
            return mutate_day(plan_set_id, service_date, callback)

        def legacy(record: dict[str, object]) -> None:
            callback(_require_day(record, service_date))
            record["updated_at"] = self._timestamp()

        return self.repository.mutate(plan_set_id, legacy)

    def _timestamp(self) -> str:
        return self.now().isoformat().replace("+00:00", "Z")


def _plan_set_payload(record: Mapping[str, object], scenario_id: str) -> dict[str, object]:
    day_payloads = [
        _day_summary_payload(record, day, scenario_id)
        for _, day in sorted(record["days"].items())
    ]
    coverage = {
        "total_days": len(day_payloads),
        "solved_days": sum(day["status"] in FINISHED_STATUSES for day in day_payloads),
        "queued_days": sum(day["status"] == "queued" for day in day_payloads),
        "running_days": sum(day["status"] == "running" for day in day_payloads),
        "failed_days": sum(day["status"] == "failed" for day in day_payloads),
        "not_requested_days": sum(
            day["status"] == "not_requested" for day in day_payloads
        ),
    }
    selected_results = [
        _selected_result(day, scenario_id)
        for day in record["days"].values()
        if _selected_result(day, scenario_id) is not None
    ]
    return {
        "plan_set_id": record["plan_set_id"],
        "parent_run_id": record["parent_run_id"],
        "depot": record["depot"],
        "horizon_start": record["horizon_start"],
        "horizon_end": record["horizon_end"],
        "route_scenario_id": scenario_id,
        "scenarios": list(record["scenarios"].values()),
        "days": day_payloads,
        "coverage": coverage,
        "kpis": _rollup_kpis(selected_results) if selected_results else None,
        "is_partial": coverage["solved_days"] != coverage["total_days"],
        "resource_source": record["resource_source"],
        "fleet_snapshot": record.get("fleet_snapshot"),
        "customer_constraint_snapshot": record.get("customer_constraint_snapshot"),
    }


def _day_summary_payload(
    record: Mapping[str, object], day: Mapping[str, object], scenario_id: str
) -> dict[str, object]:
    status = _selected_status(day, scenario_id)
    result = _selected_result(day, scenario_id)
    return {
        "service_date": day["service_date"],
        "status": status,
        "default_status": day["default_status"],
        "assigned_cases": result["assigned_cases"] if result else day["assigned_cases"],
        "routed_cases": result["routed_cases"] if result else None,
        "unserved_cases": result["unserved_cases"] if result else None,
        "total_cost": result["kpis"]["cost_breakdown"]["total_cost"] if result else None,
        "is_overridden": scenario_id != DEFAULT_SCENARIO_ID
        and scenario_id in day["selected_result_ids"],
        "selected_result_id": result["result_id"] if result else None,
        "error": _selected_error(day, scenario_id),
    }


def _day_detail_payload(
    record: Mapping[str, object], day: Mapping[str, object], scenario_id: str
) -> dict[str, object]:
    default_result = _result_by_id(day, day.get("default_result_id"))
    latest_job_id = day.get("latest_override_job_ids", {}).get(scenario_id)
    latest_job = day.get("jobs", {}).get(latest_job_id, {})
    return {
        "plan_set_id": record["plan_set_id"],
        "service_date": day["service_date"],
        "route_scenario_id": scenario_id,
        "default_status": day["default_status"],
        "override_status": None
        if scenario_id == DEFAULT_SCENARIO_ID
        else day["override_statuses"].get(scenario_id),
        "override_request": deepcopy(latest_job.get("request")),
        "default_result": default_result,
        "selected_result": _selected_result(day, scenario_id),
        "error": _selected_error(day, scenario_id),
    }


def _selected_status(day: Mapping[str, object], scenario_id: str) -> str:
    if scenario_id == DEFAULT_SCENARIO_ID:
        return str(day["default_status"])
    return str(day["override_statuses"].get(scenario_id) or day["default_status"])


def _selected_error(day: Mapping[str, object], scenario_id: str) -> object:
    if scenario_id == DEFAULT_SCENARIO_ID:
        return day.get("error")
    return day["override_errors"].get(scenario_id)


def _selected_result(
    day: Mapping[str, object], scenario_id: str
) -> Mapping[str, object] | None:
    result_id = (
        day.get("default_result_id")
        if scenario_id == DEFAULT_SCENARIO_ID
        else day["selected_result_ids"].get(scenario_id) or day.get("default_result_id")
    )
    return _result_by_id(day, result_id)


def _result_by_id(
    day: Mapping[str, object], result_id: object
) -> Mapping[str, object] | None:
    if result_id is None:
        return None
    return day["results"].get(str(result_id))


def _day_result(
    solved: Mapping[str, object], service_date: str, created_at: str
) -> dict[str, object]:
    unserved_cases = int(solved["unserved_cases"])
    status = "infeasible" if unserved_cases > 0 else "completed"
    return {
        "result_id": f"depot-result-{uuid.uuid4()}",
        "service_date": service_date,
        "status": status,
        "routes": deepcopy(solved["routes"]),
        "depot": deepcopy(solved.get("depot")),
        "kpis": deepcopy(solved["kpis"]),
        "assigned_cases": int(solved["assigned_cases"]),
        "routed_cases": int(solved["routed_cases"]),
        "unserved_cases": unserved_cases,
        "diagnostics": deepcopy(solved["diagnostics"]),
        "matrix_source": solved["matrix_source"],
        "execution": deepcopy(solved.get("execution")),
        "created_at": created_at,
    }


def _rollup_kpis(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    kpis = [result["kpis"] for result in results]
    route_count = sum(int(row["route_count"]) for row in kpis)
    cost_keys = list(kpis[0]["cost_breakdown"]) if kpis else []

    def weighted(field: str) -> float:
        if route_count == 0:
            return 0.0
        return round(
            sum(float(row[field]) * int(row["route_count"]) for row in kpis)
            / route_count,
            1,
        )

    total_revenue = round(sum(float(row.get("total_revenue", 0)) for row in kpis), 2)
    total_cost = round(
        sum(float(row["cost_breakdown"]["total_cost"]) for row in kpis), 2
    )
    return {
        "route_count": route_count,
        "driver_count": sum(int(row["driver_count"]) for row in kpis),
        "vehicle_count": sum(int(row["vehicle_count"]) for row in kpis),
        "total_miles": round(sum(float(row["total_miles"]) for row in kpis), 1),
        "drive_minutes": sum(int(row["drive_minutes"]) for row in kpis),
        "service_minutes": sum(int(row["service_minutes"]) for row in kpis),
        "waiting_minutes": sum(int(row.get("waiting_minutes", 0)) for row in kpis),
        "total_cases": sum(int(row["total_cases"]) for row in kpis),
        "avg_stops_per_route": weighted("avg_stops_per_route"),
        "avg_capacity_utilization_pct": weighted("avg_capacity_utilization_pct"),
        "avg_driver_utilization_pct": weighted("avg_driver_utilization_pct"),
        "overtime_minutes": sum(int(row["overtime_minutes"]) for row in kpis),
        "missed_windows": sum(int(row["missed_windows"]) for row in kpis),
        "late_minutes": sum(int(row["late_minutes"]) for row in kpis),
        "total_revenue": total_revenue,
        "profit": round(total_revenue - total_cost, 2),
        "cost_breakdown": {
            key: round(sum(float(row["cost_breakdown"].get(key, 0)) for row in kpis), 2)
            for key in cost_keys
        },
    }


def _apply_override(
    fleet: list[dict[str, object]],
    network_rows: Mapping[str, Sequence[Mapping[str, object]]],
    depot_id: str,
    service_date: str,
    request: Mapping[str, object],
    params: CostParameters,
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, object]]], CostParameters]:
    adjusted_fleet = [deepcopy(row) for row in fleet]
    driver_delta = int(request.get("driver_delta") or 0)
    if driver_delta < 0:
        adjusted_fleet = adjusted_fleet[: max(0, len(adjusted_fleet) + driver_delta)]
    elif driver_delta > 0:
        if not adjusted_fleet:
            raise ValueError("driver_delta cannot add resources without a frozen fleet profile.")
        templates = [deepcopy(row) for row in adjusted_fleet]
        for index in range(driver_delta):
            vehicle = deepcopy(templates[index % len(templates)])
            vehicle["vehicle_id"] = f"{vehicle['vehicle_id']}-OVERRIDE-{index + 1}"
            adjusted_fleet.append(vehicle)

    max_route_minutes = request.get("max_route_minutes")
    allow_overtime = request.get("allow_overtime")
    max_stops = request.get("max_stops_per_route")
    for vehicle in adjusted_fleet:
        if max_route_minutes is not None:
            vehicle["max_route_minutes"] = int(max_route_minutes)
        elif allow_overtime is False:
            vehicle["max_route_minutes"] = min(
                int(vehicle.get("max_route_minutes", params.max_route_minutes)),
                params.overtime_threshold_minutes,
            )
        elif allow_overtime is True:
            vehicle["max_route_minutes"] = max(
                int(vehicle.get("max_route_minutes", params.max_route_minutes)),
                params.max_route_minutes,
            )
        if max_stops is not None:
            vehicle["max_stops_per_route"] = int(max_stops)
        vehicle["available_dates"] = [service_date]

    adjusted_rows = {
        table_name: [dict(row) for row in rows]
        for table_name, rows in network_rows.items()
    }
    changes = request.get("changes") or []
    if not isinstance(changes, list):
        raise ValueError("changes must be a list.")
    facility_changes = [
        change for change in changes
        if isinstance(change, Mapping) and change.get("kind") == "facility_move"
    ]
    if len(facility_changes) > 1:
        raise ValueError("A daily override supports at most one facility_move.")
    new_location = request.get("new_depot_location")
    if facility_changes:
        new_location = facility_changes[0].get("new_depot_location")
    if new_location is not None:
        location = _request_payload(new_location)
        facilities = adjusted_rows.get("dim_facilities", [])
        depot = next(
            (row for row in facilities if str(row.get("facility_id")) == depot_id),
            None,
        )
        if depot is None:
            raise ValueError(f"Unknown depot_id {depot_id!r} for location override.")
        depot["lat"] = float(location["lat"])
        depot["lng"] = float(location["lng"])
    for change in changes:
        if not isinstance(change, Mapping):
            raise ValueError("Each daily override change must be an object.")
        kind = str(change.get("kind", ""))
        if kind == "add_deliveries":
            _apply_added_deliveries(
                adjusted_rows, depot_id, service_date, change.get("deliveries")
            )
        elif kind == "time_window_change":
            _apply_time_window_change(adjusted_rows, change)
        elif kind != "facility_move":
            raise ValueError(f"Unsupported daily override change kind: {kind!r}.")
    return adjusted_fleet, adjusted_rows, params


def _apply_added_deliveries(
    rows: dict[str, list[dict[str, object]]],
    depot_id: str,
    service_date: str,
    deliveries: object,
) -> None:
    if not isinstance(deliveries, list) or not deliveries:
        raise ValueError("add_deliveries requires a nonempty deliveries list.")
    facilities = rows.get("dim_facilities", [])
    depot = next(
        (row for row in facilities if str(row.get("facility_id")) == depot_id), None
    )
    if depot is None:
        raise ValueError(f"Unknown depot_id {depot_id!r} for added deliveries.")
    customers = rows.setdefault("dim_network_customers", [])
    lanes = rows.setdefault("dim_network_lanes", [])
    flow_rows = rows.setdefault("__daily_override_flow_rows", [])
    existing_customer_ids = {str(row.get("customer_id")) for row in customers}
    existing_lane_ids = {str(row.get("lane_id")) for row in lanes}
    for index, raw in enumerate(deliveries, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError("Each added delivery must be an object.")
        requested_day = raw.get("delivery_day")
        if requested_day not in (None, "", service_date):
            raise ValueError(
                "Daily add_deliveries cannot move work to another date; "
                "delivery_day must be omitted or match the endpoint service_date."
            )
        seed = json.dumps(dict(raw), sort_keys=True, default=str)
        customer_id = str(raw.get("customer_id") or (
            "DAILY-" + hashlib.sha256(
                f"{depot_id}|{service_date}|{index}|{seed}".encode()
            ).hexdigest()[:12].upper()
        ))
        if customer_id in existing_customer_ids:
            raise ValueError(f"Added delivery customer_id {customer_id!r} already exists.")
        lane_id = f"LNE-DAILY-{depot_id}-{customer_id}"
        if lane_id in existing_lane_ids:
            raise ValueError(f"Added delivery lane {lane_id!r} already exists.")
        cases = int(raw.get("demand_cases") or 0)
        if cases < 1:
            raise ValueError("Added delivery demand_cases must be at least 1.")
        customer = {
            "customer_id": customer_id,
            "customer_name": str(raw.get("customer_name") or customer_id),
            "customer_tier": "standard",
            "region_id": depot.get("region_id"),
            "distribution_center_id": depot.get("parent_facility_id"),
            "depot_id": depot_id,
            "market_id": str(raw.get("market_id") or f"DAILY-{depot_id}"),
            "lat": float(raw["lat"]), "lng": float(raw["lng"]),
            "receiving_window_start": str(raw.get("receiving_window_start") or "08:00"),
            "receiving_window_end": str(raw.get("receiving_window_end") or "16:00"),
            "service_minutes": int(raw.get("service_minutes") or 30),
        }
        customers.append(customer)
        lanes.append({
            "lane_id": lane_id, "lane_name": f"{depot_id} to {customer_id}",
            "lane_type": "DELIVERY", "origin_endpoint_id": depot_id,
            "origin_endpoint_type": "facility", "destination_endpoint_id": customer_id,
            "destination_endpoint_type": "customer", "mode": "ground",
            "distance_miles": 0.0, "transit_minutes": 0, "active": True,
        })
        flow_rows.append({
            "service_date": service_date, "lane_id": lane_id,
            "lane_type": "DELIVERY", "assigned_units": cases,
        })
        existing_customer_ids.add(customer_id)
        existing_lane_ids.add(lane_id)


def _apply_time_window_change(
    rows: dict[str, list[dict[str, object]]],
    change: Mapping[str, object],
) -> None:
    customer_id = str(change.get("customer_id") or "").strip()
    if not customer_id:
        raise ValueError("time_window_change requires customer_id.")
    start_text = change.get("receiving_window_start")
    end_text = change.get("receiving_window_end")
    if not isinstance(start_text, str) or _TIME_PATTERN.fullmatch(start_text) is None:
        raise ValueError("receiving_window_start must use 24-hour HH:MM format.")
    if not isinstance(end_text, str) or _TIME_PATTERN.fullmatch(end_text) is None:
        raise ValueError("receiving_window_end must use 24-hour HH:MM format.")
    if start_text >= end_text:
        raise ValueError(
            "time_window_change receiving_window_end must be after its start."
        )
    customers = rows.get("dim_network_customers", [])
    target = next(
        (row for row in customers if str(row.get("customer_id")) == customer_id),
        None,
    )
    if target is None:
        raise ValueError(
            f"time_window_change target customer {customer_id!r} not found in dated snapshot."
        )
    target["receiving_window_start"] = start_text
    target["receiving_window_end"] = end_text


def _default_fleet_provider(
    snapshot: object, depot_id: str
) -> tuple[list[dict[str, object]], str, list[dict[str, object]], str]:
    network_rows = _snapshot_value(snapshot, "network_rows")
    snapshot_costs, snapshot_cost_source = _snapshot_cost_rows(snapshot)
    for table_name in ("dim_fleet_assets", "fleet_assets"):
        supplied = [
            dict(row)
            for row in network_rows.get(table_name, [])
            if str(row.get("depot_id")) == depot_id
        ]
        if supplied:
            operating_rows = network_rows.get("operating_parameters", [])
            policy_source = f"snapshot:{table_name}"
            if any(row.get("max_stops_per_route") is None for row in supplied) and not operating_rows:
                loader = getattr(get_store(), "load_solver_base_tables", None)
                operating_rows = loader().get("operating_parameters", []) if callable(loader) else []
                policy_source += ":configured_store:operating_parameters"
            supplied, policy_source = _bind_fleet_operating_policy(
                supplied, operating_rows, policy_source
            )
            return supplied, policy_source, snapshot_costs, snapshot_cost_source
    store = get_store()
    loader = getattr(store, "load_solver_base_tables", None)
    configured_costs: list[dict[str, object]] = []
    if callable(loader):
        base = loader()
        supplied = [
            dict(row) for row in base.get("fleet", [])
            if str(row.get("depot_id")) == depot_id
        ]
        configured_costs = [
            dict(row) for row in base.get("cost_parameters", [])
        ]
        if supplied:
            fixture = all(
                any(
                    marker in str(row.get("source_system", "")).lower()
                    for marker in ("synthetic", "demo", "fixture")
                )
                for row in supplied
            )
            label = "demo_fixture" if fixture else "master_data"
            supplied, resource_source = _bind_fleet_operating_policy(
                supplied,
                base.get("operating_parameters", []),
                f"configured_store:solver_base:fleet:{label}",
            )
            return (
                supplied,
                resource_source,
                configured_costs or snapshot_costs,
                "configured_store:solver_base:cost_parameters"
                if configured_costs else snapshot_cost_source,
            )
    fixture = [
            {
                "vehicle_id": f"SYN-{depot_id}-{index + 1:02d}",
                "depot_id": depot_id,
                "capacity_cases": 720,
                "max_route_minutes": 600,
                "max_stops_per_route": 12,
                "fixed_truck_daily_cost": 340.0,
            }
            for index in range(16)
        ]
    fixture_revision = "fixed_16x720_normal_shift.v1"
    fixture_hash = _fleet_content_hash(fixture)
    return (
        fixture,
        f"pinned_fixture:{fixture_revision}:sha256:{fixture_hash}",
        configured_costs or snapshot_costs,
        "configured_store:solver_base:cost_parameters"
        if configured_costs else snapshot_cost_source,
    )



def _bind_fleet_operating_policy(
    fleet: Sequence[Mapping[str, object]],
    operating_rows: Sequence[Mapping[str, object]],
    source: str,
) -> tuple[list[dict[str, object]], str]:
    """Pin absent vehicle stop limits to the explicitly configured default policy."""
    copied = [dict(row) for row in fleet]
    missing = [row for row in copied if row.get("max_stops_per_route") is None]
    if not missing:
        return copied, source
    defaults = [row for row in operating_rows if str(row.get("parameter_set_id")) == "default"]
    if len(defaults) != 1:
        raise ValueError("Fleet stop limits require exactly one explicit default operating parameter set.")
    value = defaults[0].get("max_stops_per_route")
    try:
        limit = int(value)
        valid = not isinstance(value, bool) and float(value) == limit and limit > 0
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError("Default operating max_stops_per_route must be a positive integer.")
    for row in missing:
        row["max_stops_per_route"] = limit
        row["max_stops_policy_source"] = "operating_parameters:default"
    return copied, f"{source}:operating_parameters:default:max_stops_per_route:{limit}"


def _fleet_content_hash(fleet: Sequence[Mapping[str, object]]) -> str:
    canonical = sorted(
        (dict(row) for row in fleet), key=lambda row: str(row.get("vehicle_id", ""))
    )
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cost_content_hash(rows: Sequence[Mapping[str, object]]) -> str:
    canonical = sorted(
        (dict(row) for row in rows),
        key=lambda row: str(row.get("parameter_set_id", "")),
    )
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fleet_snapshot_provenance(
    fleet: Sequence[Mapping[str, object]], resource_source: str
) -> dict[str, object]:
    return {
        "source": resource_source,
        "vehicle_count": len(fleet),
        "content_hash": f"sha256:{_fleet_content_hash(fleet)}",
        "immutable": not _fleet_source_is_unpinned(resource_source),
    }


def _verify_fleet_snapshot(
    fleet: Sequence[Mapping[str, object]], provenance: object
) -> None:
    """Reconcile frozen rows with their immutable provenance before every solve."""
    if provenance is None:
        return  # Compatibility for plans created before fleet provenance existed.
    if not isinstance(provenance, Mapping):
        raise ValueError("Fleet snapshot provenance is malformed.")
    expected = str(provenance.get("content_hash", ""))
    actual = f"sha256:{_fleet_content_hash(fleet)}"
    if expected != actual or int(provenance.get("vehicle_count", -1)) != len(fleet):
        raise ValueError(
            "Frozen fleet rows do not reconcile with the pinned fleet snapshot."
        )


def _cost_snapshot_provenance(
    rows: Sequence[Mapping[str, object]], resource_source: str
) -> dict[str, object]:
    return {
        "source": resource_source,
        "row_count": len(rows),
        "content_hash": f"sha256:{_cost_content_hash(rows)}",
        "immutable": bool(rows),
    }


def _verify_cost_snapshot(rows: object, provenance: object) -> None:
    """Reconcile frozen cost rows with their immutable provenance before solving."""
    if provenance is None:
        return  # Compatibility for plans created before cost provenance existed.
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("Frozen route cost parameters are malformed.")
    if not isinstance(provenance, Mapping):
        raise ValueError("Route cost snapshot provenance is malformed.")
    expected = str(provenance.get("content_hash", ""))
    actual = f"sha256:{_cost_content_hash(rows)}"
    if expected != actual or int(provenance.get("row_count", -1)) != len(rows):
        raise ValueError(
            "Frozen route cost rows do not reconcile with the pinned cost snapshot."
        )


def _fleet_source_is_unpinned(resource_source: str) -> bool:
    normalized = resource_source.strip().lower()
    return (
        normalized == "injected_fleet"
        or normalized.startswith("synthetic_unpinned:")
        or normalized.startswith("unpinned:")
    )


_GENERATED_CUSTOMER_ID = re.compile(r"^NET-CUST-[A-Z]+-\d{4}$")
_TIME_PATTERN = re.compile(r"^(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d)$")
_CUSTOMER_CONSTRAINT_FIXTURE_VERSION = "generated_customer_route_constraints.v1"
_CUSTOMER_CONSTRAINT_KEYS = (
    "receiving_window_start",
    "receiving_window_end",
    "service_minutes",
)


def _customer_constraint_hash(rows: Sequence[Mapping[str, object]]) -> str:
    canonical = sorted(
        (dict(row) for row in rows), key=lambda row: str(row.get("customer_id", ""))
    )
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _freeze_customer_constraints(
    network_rows: Mapping[str, Sequence[Mapping[str, object]]], depot_id: str
) -> tuple[dict[str, list[dict[str, object]]], dict[str, object]]:
    frozen_network = {
        name: [dict(row) for row in rows] for name, rows in network_rows.items()
    }
    constraint_rows: list[dict[str, object]] = []
    overlay_used = False
    for customer in frozen_network.get("dim_network_customers", []):
        if str(customer.get("depot_id")) != depot_id:
            continue
        missing = [key for key in _CUSTOMER_CONSTRAINT_KEYS if customer.get(key) in (None, "")]
        customer_id = str(customer.get("customer_id", ""))
        if missing and _GENERATED_CUSTOMER_ID.fullmatch(customer_id):
            customer.update(
                receiving_window_start="08:00",
                receiving_window_end="17:00",
                service_minutes=20,
            )
            overlay_used = True
        constraint_rows.append({
            "customer_id": customer_id,
            **{key: customer.get(key) for key in _CUSTOMER_CONSTRAINT_KEYS},
        })
    digest = _customer_constraint_hash(constraint_rows)
    source = (
        f"pinned_fixture_overlay:{_CUSTOMER_CONSTRAINT_FIXTURE_VERSION}"
        if overlay_used
        else "snapshot:dim_network_customers"
    )
    return frozen_network, {
        "source": source,
        "version": _CUSTOMER_CONSTRAINT_FIXTURE_VERSION,
        "customer_count": len(constraint_rows),
        "content_hash": f"sha256:{digest}",
        "constraints": constraint_rows,
        "immutable": True,
    }


def _apply_customer_constraint_snapshot(
    network_rows: Mapping[str, Sequence[Mapping[str, object]]], provenance: object
) -> dict[str, list[dict[str, object]]]:
    adjusted = {name: [dict(row) for row in rows] for name, rows in network_rows.items()}
    if provenance is None:
        return adjusted
    if not isinstance(provenance, Mapping):
        raise ValueError("Customer constraint snapshot provenance is malformed.")
    constraints = provenance.get("constraints")
    if not isinstance(constraints, list) or not all(isinstance(row, Mapping) for row in constraints):
        raise ValueError("Customer constraint snapshot rows are malformed.")
    expected = str(provenance.get("content_hash", ""))
    actual = f"sha256:{_customer_constraint_hash(constraints)}"
    if expected != actual or int(provenance.get("customer_count", -1)) != len(constraints):
        raise ValueError("Customer constraint rows do not reconcile with the pinned snapshot.")
    by_id = {str(row.get("customer_id")): row for row in constraints}
    matched: set[str] = set()
    for customer in adjusted.get("dim_network_customers", []):
        customer_id = str(customer.get("customer_id", ""))
        frozen = by_id.get(customer_id)
        if frozen is None:
            continue
        matched.add(customer_id)
        for key in _CUSTOMER_CONSTRAINT_KEYS:
            customer[key] = frozen.get(key)
    if matched != set(by_id):
        raise ValueError("Pinned customer constraint snapshot does not match network customers.")
    return adjusted


def _snapshot_cost_rows(snapshot: object) -> tuple[list[dict[str, object]], str]:
    network_rows = _snapshot_value(snapshot, "network_rows")
    for table_name in ("route_cost_parameters", "cost_parameters"):
        rows = [dict(row) for row in network_rows.get(table_name, [])]
        if rows:
            return rows, f"snapshot:{table_name}"
    return [], "snapshot:none"


def _route_cost_parameters(
    rows: Sequence[Mapping[str, object]],
    depot_id: str,
    service_date: str,
    *,
    strict: bool,
    source: str = "pinned",
) -> tuple[CostParameters, str]:
    candidates: list[Mapping[str, object]] = []
    for row in rows:
        row_depot = row.get("depot_id")
        if row_depot not in (None, "", depot_id):
            continue
        start = row.get("effective_start", row.get("effective_from"))
        end = row.get("effective_end", row.get("effective_to"))
        if start and _date_text(start) > service_date:
            continue
        if end and _date_text(end) < service_date:
            continue
        candidates.append(row)
    if len(candidates) > 1:
        raise ValueError(
            f"Multiple pinned route cost parameter rows apply to {depot_id} on {service_date}."
        )
    if candidates:
        row = candidates[0]
        if strict:
            missing = [
                key for key in CostParameters().as_dict()
                if row.get(key) in (None, "")
            ]
            if missing:
                raise ValueError(
                    "Strict route cost parameters are incomplete; missing "
                    f"{', '.join(missing)}."
                )
        return CostParameters.from_row(dict(row)), source
    if strict:
        raise ValueError(
            f"Strict route execution requires pinned route cost parameters for "
            f"{depot_id} on {service_date}."
        )
    return CostParameters(), "development_defaults"


def _snapshot_horizon(snapshot: object) -> tuple[str, str]:
    scenario = _snapshot_value(snapshot, "scenario")
    start = _object_value(scenario, "horizon_start")
    end = _object_value(scenario, "horizon_end")
    return _date_text(start), _date_text(end)


def _snapshot_value(snapshot: object, field: str) -> Any:
    return _object_value(snapshot, field)


def _object_value(value: object, field: str) -> Any:
    if isinstance(value, Mapping):
        return value[field]
    return getattr(value, field)


def _date_range(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    finish = date.fromisoformat(end)
    if finish < current:
        raise ValueError("Parent run horizon_end precedes horizon_start.")
    dates = []
    while current <= finish:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _date_text(value: object) -> str:
    if isinstance(value, datetime):
        raise ValueError("A date without a time component is required.")
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()


def _optional_date_text(value: object | None) -> str | None:
    return None if value is None else _date_text(value)


def _is_transient_route_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return any(
        marker in name or marker in message
        for marker in (
            "timeout", "connection", "operationalerror", "unavailable", "temporar",
            "rate limit", "429", "502", "503",
            "valhalla matrix request failed", "serving endpoint returned no prediction",
        )
    )


def _heartbeat_loop(
    stop: threading.Event,
    heartbeat: Callable[..., bool],
    plan_set_id: str,
    job_id: str,
    worker_id: str,
) -> None:
    while not stop.wait(30):
        try:
            if not heartbeat(plan_set_id, job_id, worker_id):
                return
        except Exception:
            # The main attempt still owns its original lease. A later recovery pass
            # can reclaim it if the database remains unavailable beyond that lease.
            continue


def _request_payload(request: object) -> dict[str, object]:
    if isinstance(request, Mapping):
        return {str(key): value for key, value in request.items()}
    if hasattr(request, "model_dump"):
        return request.model_dump(mode="json", exclude_none=True)
    if hasattr(request, "__dict__"):
        return {
            key: value
            for key, value in vars(request).items()
            if value is not None and not key.startswith("_")
        }
    raise TypeError("Request must be a mapping or model-like object.")


def _require_scenario(
    record: Mapping[str, object], scenario_id: str, *, named: bool = False
) -> None:
    if scenario_id not in record["scenarios"]:
        raise KeyError(f"Unknown route_scenario_id {scenario_id!r}.")
    if named and scenario_id == DEFAULT_SCENARIO_ID:
        raise ValueError("A named route scenario is required.")


def _require_day(record: Mapping[str, object], service_date: str) -> dict[str, object]:
    day = record["days"].get(service_date)
    if day is None:
        raise KeyError(f"Service date {service_date} is outside the plan horizon.")
    return day


depot_plan_service = DepotPlanService(
    repository=depot_plan_repository,
    snapshot_provider=network_scenario_service.get_run_snapshot,
)
