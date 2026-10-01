from __future__ import annotations

import uuid
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

        network_rows = _snapshot_value(snapshot, "network_rows")
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
        if (
            get_route_execution_mode() == "strict_serving_road"
            and str(resource_source).startswith("synthetic_unpinned:")
        ):
            raise ValueError(
                "Strict route execution requires a real pinned fleet source; "
                f"received {resource_source!r}."
            )
        frozen_fleet = [deepcopy(row) for row in fleet]
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
            "route_cost_parameters": deepcopy(frozen_cost_rows),
            "cost_resource_source": cost_resource_source,
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
            record["days"][service_date] = {
                "service_date": service_date,
                "assigned_cases": int(targets["assigned_cases"]),
                "default_status": "queued",
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
                        "status": "queued",
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

    def create_scenario(self, plan_set_id: str, scenario_name: str) -> RouteScenario:
        name = scenario_name.strip()
        if not name:
            raise ValueError("scenario_name is required.")
        route_scenario_id = f"route-scenario-{uuid.uuid4()}"

        def add_scenario(record: dict[str, object]) -> None:
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

        def queue_override(record: dict[str, object]) -> None:
            _require_scenario(record, route_scenario_id, named=True)
            day = _require_day(record, service_date_text)
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
            record["updated_at"] = self._timestamp()

        self.repository.mutate(plan_set_id, queue_override)
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

        def reset(record: dict[str, object]) -> None:
            _require_scenario(record, route_scenario_id, named=True)
            day = _require_day(record, service_date_text)
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
            record["updated_at"] = self._timestamp()

        self.repository.mutate(plan_set_id, reset)
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
        def mark_running(record: dict[str, object]) -> None:
            day = _require_day(record, service_date)
            job = day["jobs"].get(job_id)
            if job is None or str(job["status"]) in FINISHED_STATUSES | {"failed"}:
                return
            job["status"] = "running"
            if route_scenario_id == DEFAULT_SCENARIO_ID:
                day["default_status"] = "running"
            else:
                day["override_statuses"][route_scenario_id] = "running"
            record["updated_at"] = self._timestamp()

        running_record = self.repository.mutate(plan_set_id, mark_running)
        day = _require_day(running_record, service_date)
        job = day["jobs"].get(job_id)
        if job is None or str(job["status"]) != "running":
            return

        try:
            snapshot = self.snapshot_provider(str(running_record["parent_run_id"]))
            network_rows = deepcopy(_snapshot_value(snapshot, "network_rows"))
            flow_rows = list(_snapshot_value(snapshot, "flow_rows"))
            fleet = [deepcopy(row) for row in running_record["fleet"]]
            frozen_cost_rows = running_record.get("route_cost_parameters")
            if frozen_cost_rows is None:
                # Compatibility for records created before route inputs were frozen.
                frozen_cost_rows, legacy_cost_source = _snapshot_cost_rows(snapshot)
            else:
                legacy_cost_source = str(
                    running_record.get("cost_resource_source") or "legacy_snapshot"
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
                execution["cost_parameter_source"] = cost_parameter_source
            result = _day_result(solved, service_date, self._timestamp())
        except Exception as exc:
            self._store_failure(
                plan_set_id,
                service_date,
                route_scenario_id,
                job_id,
                str(exc),
            )
            return

        def store_result(record: dict[str, object]) -> None:
            current_day = _require_day(record, service_date)
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
            record["updated_at"] = self._timestamp()

        self.repository.mutate(plan_set_id, store_result)

    def _store_failure(
        self,
        plan_set_id: str,
        service_date: str,
        route_scenario_id: str,
        job_id: str,
        message: str,
    ) -> None:
        def fail(record: dict[str, object]) -> None:
            day = _require_day(record, service_date)
            job = day["jobs"].get(job_id)
            if job is not None:
                job["status"] = "failed"
                job["error"] = message
            if route_scenario_id == DEFAULT_SCENARIO_ID:
                day["default_status"] = "failed"
                day["error"] = message
            else:
                day.setdefault("latest_override_job_ids", {})
                is_latest = (
                    day["latest_override_job_ids"].get(route_scenario_id) == job_id
                )
                if is_latest and not (job or {}).get("discard_selection"):
                    day["override_statuses"][route_scenario_id] = "failed"
                    day["override_errors"][route_scenario_id] = message
            record["updated_at"] = self._timestamp()

        self.repository.mutate(plan_set_id, fail)

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
        "assigned_cases": day["assigned_cases"],
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
    return {
        "plan_set_id": record["plan_set_id"],
        "service_date": day["service_date"],
        "route_scenario_id": scenario_id,
        "default_status": day["default_status"],
        "override_status": None
        if scenario_id == DEFAULT_SCENARIO_ID
        else day["override_statuses"].get(scenario_id),
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
    new_location = request.get("new_depot_location")
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
    return adjusted_fleet, adjusted_rows, params


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
            return supplied, f"snapshot:{table_name}", snapshot_costs, snapshot_cost_source
    store = get_store()
    loader = getattr(store, "load_solver_base_tables", None)
    if callable(loader):
        base = loader()
        supplied = [
            dict(row) for row in base.get("fleet", [])
            if str(row.get("depot_id")) == depot_id
        ]
        costs = [dict(row) for row in base.get("cost_parameters", [])]
        if supplied:
            fixture = all(
                any(
                    marker in str(row.get("source_system", "")).lower()
                    for marker in ("synthetic", "demo", "fixture")
                )
                for row in supplied
            )
            label = "demo_fixture" if fixture else "master_data"
            return (
                supplied,
                f"configured_store:solver_base:fleet:{label}",
                costs or snapshot_costs,
                "configured_store:solver_base:cost_parameters"
                if costs else snapshot_cost_source,
            )
    return (
        [
            {
                "vehicle_id": f"SYN-{depot_id}-{index + 1:02d}",
                "depot_id": depot_id,
                "capacity_cases": 720,
                "max_route_minutes": 600,
                "max_stops_per_route": 12,
                "fixed_truck_daily_cost": 340.0,
            }
            for index in range(16)
        ],
        "synthetic_unpinned:fixed_16x720_normal_shift",
        snapshot_costs,
        snapshot_cost_source,
    )


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
