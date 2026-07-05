from __future__ import annotations

import time

from fastapi.testclient import TestClient

from backend.main import app
from backend.models import ScenarioCreateRequest, ScenarioDefinition, ValidationResponse
from backend.services.solve_runs import solve_run_manager
from route_opt.overrides import seed_override_tables
from route_opt.solver.ortools_cvrptw import solve_scenario_partition
from route_opt.synthetic import generate_all


class FakeDatabricksStore:
    def __init__(self) -> None:
        self.scenario = ScenarioDefinition(
            scenario_id="scn_driver_minus_one",
            scenario_name="One Fewer Driver Test",
            scenario_type="driver_count_change",
            baseline_scenario_id="baseline",
            depot_id="DPT_NORTH",
            delivery_day="Tuesday",
            parameters={"driver_delta": -1, "allow_overtime": True},
            status="draft",
        )

    def create_scenario(self, payload: ScenarioCreateRequest):
        self.scenario = self.scenario.model_copy(
            update={
                "scenario_name": payload.scenario_name,
                "parameters": payload.parameters,
                "status": "draft",
            }
        )
        return self.scenario, "databricks"

    def get_scenario_definition(self, scenario_id: str) -> ScenarioDefinition:
        assert scenario_id == self.scenario.scenario_id
        return self.scenario

    def set_scenario_status(self, scenario_id: str, status: str) -> None:
        assert scenario_id == self.scenario.scenario_id
        self.scenario = self.scenario.model_copy(update={"status": status})

    def validate_scenario(self, scenario_id: str) -> ValidationResponse:
        self.set_scenario_status(scenario_id, "validated")
        return ValidationResponse(
            scenario_id=scenario_id,
            valid=True,
            hard_constraints=[],
            soft_penalties=[],
            missing_fields=[],
            inferred_fields=[],
            estimated_affected_customers=0,
            estimated_affected_routes=1,
            summary="Scenario parameters are complete and ready to run.",
        )


def test_databricks_serving_run_path(monkeypatch) -> None:
    data = generate_all(seed=42, customer_count=250)
    fake_store = FakeDatabricksStore()

    def databricks_backend() -> str:
        return "databricks"

    import backend.routes.results as results_route
    import backend.routes.runs as runs_route
    import backend.routes.scenarios as scenarios_route
    import backend.services.solve_runs as solve_runs_module
    import backend.services.solver as solver_module

    monkeypatch.setattr(scenarios_route, "get_data_backend", databricks_backend)
    monkeypatch.setattr(runs_route, "get_data_backend", databricks_backend)
    monkeypatch.setattr(results_route, "get_data_backend", databricks_backend)
    monkeypatch.setattr(scenarios_route, "get_store", lambda: fake_store)
    monkeypatch.setattr(runs_route, "get_store", lambda: fake_store)
    monkeypatch.setattr(results_route, "get_store", lambda: fake_store)
    monkeypatch.setattr(
        solve_run_manager,
        "endpoint_url",
        lambda: "https://example.com/ml/endpoints/route-solver-dev",
    )
    monkeypatch.setattr(
        solver_module.solver_service,
        "_load_base_tables",
        lambda: {
            "depots": data["depot_master"],
            "customers": data["location_data"],
            "fleet": data["fleet_assets"],
            "orders": data["fact_delivery_orders"],
        },
    )

    seeded_overrides = seed_override_tables(data["location_data"])
    monkeypatch.setattr(
        solver_module.solver_service,
        "_load_override_tables",
        lambda scenario_id: {
            table_name: [row for row in rows if row["scenario_id"] == scenario_id]
            for table_name, rows in seeded_overrides.items()
        },
    )

    def local_invoke_endpoint(**kwargs):
        return solve_scenario_partition(**kwargs)

    monkeypatch.setattr(solver_module.solver_service, "invoke_endpoint", local_invoke_endpoint)
    monkeypatch.setattr(solve_runs_module.results_writer, "persist", lambda scenario, result: None)

    with solve_run_manager._lock:
        solve_run_manager._runs.clear()
        solve_run_manager._results.clear()

    client = TestClient(app)
    created = client.post(
        "/api/scenarios",
        json={
            "scenario_name": "One Fewer Driver Test",
            "scenario_type": "driver_count_change",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "parameters": {"driver_delta": -1, "allow_overtime": True},
        },
    )
    assert created.status_code == 200
    scenario_id = created.json()["scenario"]["scenario_id"]

    validated = client.post(f"/api/scenarios/{scenario_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True

    started = client.post(f"/api/scenarios/{scenario_id}/run")
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    status = {}
    for _ in range(80):
        response = client.get(f"/api/runs/{run_id}?scenarioId={scenario_id}")
        assert response.status_code == 200
        status = response.json()
        if status["status"] in {"succeeded", "infeasible", "failed"}:
            break
        time.sleep(0.1)

    assert status["status"] == "succeeded"
    result = client.get(f"/api/scenarios/{scenario_id}/results")
    assert result.status_code == 200
    assert result.json()["scenario_id"] == scenario_id
    assert result.json()["scenario_kpis"]["route_count"] > 0
