from __future__ import annotations

from copy import deepcopy
from threading import RLock

import pytest

from backend.models import Kpis, Route
from backend.services.depot_plan_jobs import DepotPlanJobManager
from backend.services.depot_plans import DepotPlanService, _route_cost_parameters
from route_opt.cost import CostParameters
from route_opt.depot_planning import solve_depot_plan


DATE_ONE = "2026-10-01"
DATE_TWO = "2026-10-02"
DEPOT_ID = "DPT_TEST"


class FakeRepository:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}
        self.lock = RLock()
        self.inside_mutate = False

    def find(self, parent_run_id: str, depot_id: str):
        with self.lock:
            for record in self.records.values():
                if (
                    record["parent_run_id"] == parent_run_id
                    and record["depot"]["depot_id"] == depot_id
                ):
                    return deepcopy(record)
        return None

    def create(self, record: dict[str, object]):
        with self.lock:
            existing = self.find(
                str(record["parent_run_id"]), str(record["depot"]["depot_id"])
            )
            if existing is not None:
                return existing
            self.records[str(record["plan_set_id"])] = deepcopy(record)
            return deepcopy(record)

    def get(self, plan_set_id: str):
        with self.lock:
            return deepcopy(self.records[plan_set_id])

    def mutate(self, plan_set_id: str, callback):
        with self.lock:
            self.inside_mutate = True
            try:
                callback(self.records[plan_set_id])
            finally:
                self.inside_mutate = False
            return deepcopy(self.records[plan_set_id])

    def list_pending(self):
        with self.lock:
            pending = []
            for record in self.records.values():
                statuses = {
                    job["status"]
                    for day in record["days"].values()
                    for job in day["jobs"].values()
                }
                if statuses & {"queued", "running"}:
                    pending.append(deepcopy(record))
            return pending


def _snapshot() -> dict[str, object]:
    return {
        "scenario": {"horizon_start": DATE_ONE, "horizon_end": DATE_TWO},
        "network_rows": {
            "demand_plan_versions": [
                {"horizon_start": DATE_ONE, "horizon_end": DATE_TWO}
            ],
            "capacity_plan_versions": [
                {"horizon_start": DATE_ONE, "horizon_end": DATE_TWO}
            ],
            "dim_facilities": [
                {
                    "facility_id": DEPOT_ID,
                    "facility_name": "Test Depot",
                    "facility_type": "depot",
                    "region_id": "REGION_TEST",
                    "lat": 39.75,
                    "lng": -86.15,
                }
            ],
            "dim_network_customers": [
                {
                    "customer_id": "CUST_A",
                    "customer_name": "Customer A",
                    "customer_tier": "strategic",
                    "depot_id": DEPOT_ID,
                    "lat": 39.78,
                    "lng": -86.12,
                    "receiving_window_start": "07:00",
                    "receiving_window_end": "12:00",
                    "service_minutes": 15,
                }
            ],
            "dim_network_lanes": [
                {
                    "lane_id": "LNE_DELIVERY_A",
                    "lane_type": "DELIVERY",
                    "origin_endpoint_id": DEPOT_ID,
                    "destination_endpoint_id": "CUST_A",
                }
            ],
        },
        "flow_rows": [
            {
                "service_date": DATE_ONE,
                "lane_id": "LNE_DELIVERY_A",
                "lane_type": "DELIVERY",
                "assigned_units": 100,
            }
        ],
        "cost_rows": [],
    }


def _fleet_provider(snapshot: object, depot_id: str):
    return (
        [
            {
                "vehicle_id": "VEH-1",
                "depot_id": depot_id,
                "capacity_cases": 150,
                "max_route_minutes": 600,
                "max_stops_per_route": 5,
            }
        ],
        "test_fixed_fleet",
    )


def _payload(value: object) -> dict[str, object]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _service():
    repository = FakeRepository()
    jobs = DepotPlanJobManager(max_workers=1, start_workers=False)
    solve_calls: list[tuple[str, int]] = []
    solve_inputs: list[dict[str, object]] = []

    def solver(*args, **kwargs):
        assert not repository.inside_mutate
        service_date = str(kwargs["service_date"])
        solve_calls.append((service_date, len(kwargs["fleet"])))
        solve_inputs.append(
            {
                "network_rows": deepcopy(kwargs["network_rows"]),
                "fleet": deepcopy(kwargs["fleet"]),
                "cost_parameters": kwargs["cost_parameters"],
            }
        )
        return solve_depot_plan(**kwargs, time_limit_seconds=1)

    service = DepotPlanService(
        repository=repository,
        snapshot_provider=lambda run_id: deepcopy(_snapshot()),
        fleet_provider=_fleet_provider,
        solver=solver,
        job_manager=jobs,
    )
    return service, repository, jobs, solve_calls, solve_inputs


def test_plan_creation_is_idempotent_prioritized_and_rolls_up_partial_results() -> None:
    service, repository, jobs, solve_calls, solve_inputs = _service()
    created = _payload(service.get_or_create_plan("RUN-1", DEPOT_ID, DATE_TWO))
    repeated = _payload(service.get_or_create_plan("RUN-1", DEPOT_ID, DATE_TWO))

    assert created["plan_set_id"] == repeated["plan_set_id"]
    assert created["coverage"] == {
        "total_days": 2,
        "solved_days": 0,
        "queued_days": 2,
        "running_days": 0,
        "failed_days": 0,
    }
    assert created["is_partial"] is True
    assert len(repository.records) == 1

    assert jobs.run_next()
    partial = _payload(service.get_plan(created["plan_set_id"]))
    assert solve_calls[0][0] == DATE_TWO
    assert partial["coverage"]["solved_days"] == 1
    assert partial["is_partial"] is True
    assert partial["kpis"]["total_cases"] == 0

    assert jobs.run_next()
    complete = _payload(service.get_plan(created["plan_set_id"]))
    assert complete["coverage"]["solved_days"] == 2
    assert complete["is_partial"] is False
    assert complete["kpis"]["total_cases"] == 100
    assert Kpis.model_validate(complete["kpis"])
    first_day = _payload(service.get_day(created["plan_set_id"], DATE_ONE))
    assert Route.model_validate(first_day["selected_result"]["routes"][0])


def test_named_override_retains_history_updates_on_completion_and_resets() -> None:
    service, repository, jobs, solve_calls, solve_inputs = _service()
    plan = _payload(service.get_or_create_plan("RUN-2", DEPOT_ID))
    while jobs.run_next():
        pass
    scenario = _payload(service.create_scenario(plan["plan_set_id"], "No drivers"))

    pending = _payload(
        service.optimize_day(
            plan["plan_set_id"],
            DATE_ONE,
            {"route_scenario_id": scenario["route_scenario_id"], "driver_delta": -1},
        )
    )
    default_result_id = pending["default_result"]["result_id"]
    assert pending["override_status"] == "queued"
    assert pending["selected_result"]["result_id"] == default_result_id

    assert jobs.run_next()
    overridden = _payload(
        service.get_day(plan["plan_set_id"], DATE_ONE, scenario["route_scenario_id"])
    )
    assert overridden["override_status"] == "infeasible"
    assert overridden["selected_result"]["unserved_cases"] == 100
    assert overridden["selected_result"]["result_id"] != default_result_id
    stored_day = repository.get(plan["plan_set_id"])["days"][DATE_ONE]
    assert len(stored_day["results"]) == 2

    reset = _payload(
        service.reset_day_override(
            plan["plan_set_id"], scenario["route_scenario_id"], DATE_ONE
        )
    )
    assert reset["selected_result"]["result_id"] == default_result_id
    assert len(repository.get(plan["plan_set_id"])["days"][DATE_ONE]["results"]) == 2


def test_recovery_requeues_persisted_running_work_without_duplicate_active_job() -> None:
    service, repository, abandoned_jobs, solve_calls, solve_inputs = _service()
    plan = _payload(service.get_or_create_plan("RUN-3", DEPOT_ID))

    recovery_jobs = DepotPlanJobManager(max_workers=1, start_workers=False)
    recovered = DepotPlanService(
        repository=repository,
        snapshot_provider=lambda run_id: deepcopy(_snapshot()),
        fleet_provider=_fleet_provider,
        solver=service.solver,
        job_manager=recovery_jobs,
    )

    assert recovered.recover_pending_plans() == 2
    assert recovered.recover_pending_plans() == 0
    while recovery_jobs.run_next():
        pass
    assert len(solve_calls) == 2
    assert _payload(recovered.get_plan(plan["plan_set_id"]))["is_partial"] is False


def test_operational_override_changes_only_local_solver_inputs() -> None:
    service, repository, jobs, solve_calls, solve_inputs = _service()
    plan = _payload(service.get_or_create_plan("RUN-4", DEPOT_ID))
    while jobs.run_next():
        pass
    scenario = _payload(service.create_scenario(plan["plan_set_id"], "Local limits"))

    service.optimize_day(
        plan["plan_set_id"],
        DATE_ONE,
        {
            "route_scenario_id": scenario["route_scenario_id"],
            "allow_overtime": False,
            "max_route_minutes": 300,
            "max_stops_per_route": 1,
            "new_depot_location": {"lat": 39.8, "lng": -86.1},
        },
    )
    assert jobs.run_next()

    override_input = solve_inputs[-1]
    vehicle = override_input["fleet"][0]
    assert vehicle["max_route_minutes"] == 300
    assert vehicle["max_stops_per_route"] == 1
    assert vehicle["available_dates"] == [DATE_ONE]
    depot = override_input["network_rows"]["dim_facilities"][0]
    assert (depot["lat"], depot["lng"]) == (39.8, -86.1)
    assert _snapshot()["network_rows"]["dim_facilities"][0]["lat"] == 39.75


def test_route_cost_parameters_are_pinned_by_depot_and_date() -> None:
    snapshot = _snapshot()
    snapshot["network_rows"]["route_cost_parameters"] = [{
        **CostParameters().as_dict(),
        "depot_id": DEPOT_ID,
        "effective_start": DATE_ONE,
        "effective_end": DATE_ONE,
        "cost_per_mile": 4.75,
        "labor_regular_hour": 91.0,
    }]

    params, source = _route_cost_parameters(
        snapshot["network_rows"]["route_cost_parameters"],
        DEPOT_ID, DATE_ONE, strict=True, source="snapshot:route_cost_parameters"
    )
    assert params.cost_per_mile == 4.75
    assert params.labor_regular_hour == 91.0
    assert source == "snapshot:route_cost_parameters"
    with pytest.raises(ValueError, match="requires pinned route cost parameters"):
        _route_cost_parameters(
            snapshot["network_rows"]["route_cost_parameters"],
            DEPOT_ID, DATE_TWO, strict=True,
        )


def test_strict_plan_creation_rejects_default_synthetic_fleet(monkeypatch) -> None:
    monkeypatch.setenv("ROUTE_EXECUTION_MODE", "strict_serving_road")
    service = DepotPlanService(
        repository=FakeRepository(),
        snapshot_provider=lambda run_id: deepcopy(_snapshot()),
        job_manager=DepotPlanJobManager(max_workers=1, start_workers=False),
    )

    with pytest.raises(ValueError, match="requires a real pinned fleet source"):
        service.get_or_create_plan("RUN-STRICT", DEPOT_ID)


def test_strict_empty_horizon_needs_no_fleet_cost_matrix_or_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("ROUTE_EXECUTION_MODE", "strict_serving_road")
    monkeypatch.delenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", raising=False)
    monkeypatch.delenv("ROUTING_COVERAGE_MANIFEST", raising=False)
    snapshot = _snapshot()
    for flow in snapshot["flow_rows"]:
        flow["assigned_units"] = 0
    jobs = DepotPlanJobManager(max_workers=1, start_workers=False)
    service = DepotPlanService(
        repository=FakeRepository(), snapshot_provider=lambda _: deepcopy(snapshot),
        fleet_provider=lambda *_: pytest.fail("An empty plan does not require fleet lookup"),
        job_manager=jobs,
    )
    plan = service.get_or_create_plan("RUN-EMPTY", DEPOT_ID)
    while jobs.run_next():
        pass
    completed = service.get_plan(plan.plan_set_id)
    assert completed.coverage.solved_days == 2
    assert completed.resource_source == "not_required_no_work"
    day = service.get_day(plan.plan_set_id, DATE_ONE)
    assert day.selected_result.assigned_cases == 0
    assert day.selected_result.execution["solver_invoked"] is False


def test_default_provider_loads_exact_depot_resources_once_and_freezes_them(monkeypatch) -> None:
    import backend.services.depot_plans as depot_plans_module

    monkeypatch.setenv("ROUTE_EXECUTION_MODE", "strict_serving_road")
    calls = 0
    base = {
        "fleet": [
            {
                "vehicle_id": "DALLAS-1", "depot_id": DEPOT_ID,
                "capacity_cases": 150, "max_route_minutes": 540,
                "max_stops_per_route": 7, "fixed_truck_daily_cost": 225.0,
                "source_system": "explicit_demo_fixture",
            },
            {
                "vehicle_id": "LEGACY-NORTH", "depot_id": "DPT_NORTH",
                "capacity_cases": 999, "max_route_minutes": 999,
                "max_stops_per_route": 99, "fixed_truck_daily_cost": 1.0,
            },
        ],
        "cost_parameters": [{**CostParameters().as_dict(), "cost_per_mile": 4.6}],
    }

    class Store:
        def load_solver_base_tables(self):
            nonlocal calls
            calls += 1
            return deepcopy(base)

    monkeypatch.setattr(depot_plans_module, "get_store", lambda: Store())
    repository = FakeRepository()
    jobs = DepotPlanJobManager(max_workers=1, start_workers=False)
    observed_costs = []

    def solver(**kwargs):
        observed_costs.append(kwargs["cost_parameters"].cost_per_mile)
        return solve_depot_plan(**kwargs, time_limit_seconds=1)

    service = DepotPlanService(
        repository=repository,
        snapshot_provider=lambda run_id: deepcopy(_snapshot()),
        solver=solver,
        job_manager=jobs,
    )
    plan = _payload(service.get_or_create_plan("RUN-PINNED", DEPOT_ID))
    stored = repository.get(plan["plan_set_id"])
    assert calls == 1
    assert [row["vehicle_id"] for row in stored["fleet"]] == ["DALLAS-1"]
    assert stored["resource_source"].endswith(":demo_fixture")
    assert stored["route_cost_parameters"][0]["cost_per_mile"] == 4.6

    base["fleet"][0]["capacity_cases"] = 1
    base["cost_parameters"][0]["cost_per_mile"] = 99.0
    while jobs.run_next():
        pass
    assert calls == 1
    assert observed_costs == [4.6, 4.6]
    assert repository.get(plan["plan_set_id"])["fleet"][0]["capacity_cases"] == 150
