from __future__ import annotations

from fastapi.testclient import TestClient
from datetime import date, timedelta

from backend.main import app
from backend.models import NetworkScenarioResult
from backend.services.network_scenarios import network_scenario_service
from backend.tests.network_run_helpers import run_network_scenario


client = TestClient(app)


def _create_scenario(name: str) -> dict[str, object]:
    options = client.get("/api/network/options").json()
    start = options["default_horizon_start"]
    response = client.post(
        "/api/network/scenarios",
        json={
            "scenario_name": name,
            "demand_plan_version_id": options["default_demand_plan_version_id"],
            "capacity_plan_version_id": options["default_capacity_plan_version_id"],
            "horizon_start": start,
            "horizon_end": (date.fromisoformat(start) + timedelta(days=2)).isoformat(),
            "region_id": "REGION_TOLA",
        },
    )
    assert response.status_code == 201
    return response.json()


def _run(scenario_id: str) -> dict[str, object]:
    return run_network_scenario(client, scenario_id).json()


def test_same_frozen_revision_is_idempotent_and_legacy_results_still_parse() -> None:
    scenario = _create_scenario("Run ID history")
    scenario_id = str(scenario["scenario_id"])

    first = _run(scenario_id)["result"]
    second = _run(scenario_id)["result"]

    assert first["run_id"]
    assert second["run_id"]
    assert first["run_id"] == second["run_id"]

    legacy_payload = dict(first)
    legacy_payload.pop("run_id")
    assert NetworkScenarioResult.model_validate(legacy_payload).run_id is None


def test_snapshot_is_immutable_after_edit_and_rerun() -> None:
    scenario = _create_scenario("Original snapshot name")
    scenario_id = str(scenario["scenario_id"])
    first_run = _run(scenario_id)
    first_result = first_run["result"]
    first_run_id = str(first_result["run_id"])
    first_snapshot = network_scenario_service.get_run_snapshot(first_run_id)

    updated = client.patch(
        f"/api/network/scenarios/{scenario_id}",
        json={
            "expected_revision": scenario["revision"],
            "scenario_name": "Edited scenario name",
            "assumptions": {"unmet_penalty_per_case": 999},
        },
    )
    assert updated.status_code == 200
    second_result = _run(scenario_id)["result"]

    historical = client.get(f"/api/network/runs/{first_run_id}")
    assert historical.status_code == 200
    compact_first = dict(first_result)
    compact_first.pop("charge_details", None)
    compact_first.pop("baseline_charge_details", None)
    assert historical.json() == compact_first
    assert second_result["run_id"] != first_run_id
    latest = client.get(f"/api/network/scenarios/{scenario_id}/result")
    assert latest.status_code == 200
    compact_second = dict(second_result)
    compact_second.pop("charge_details", None)
    compact_second.pop("baseline_charge_details", None)
    assert latest.json() == compact_second
    assert latest.json() != historical.json()

    retained = network_scenario_service.get_run_snapshot(first_run_id)
    assert retained.scenario.scenario_name == "Original snapshot name"
    assert retained.scenario.assumptions.unmet_penalty_per_case == 250
    assert retained.result == first_snapshot.result
    assert retained.network_rows == first_snapshot.network_rows
    assert retained.flow_rows == first_snapshot.flow_rows
    assert retained.cost_rows == first_snapshot.cost_rows

    retained.network_rows["dim_facilities"].clear()
    assert network_scenario_service.get_run_snapshot(first_run_id).network_rows[
        "dim_facilities"
    ]


def test_historical_lookup_survives_scenario_deletion_and_missing_run_is_404() -> None:
    scenario = _create_scenario("Deleted scenario history")
    scenario_id = str(scenario["scenario_id"])
    result = _run(scenario_id)["result"]
    run_id = str(result["run_id"])

    deleted = client.delete(f"/api/network/scenarios/{scenario_id}")
    assert deleted.status_code == 204

    historical = client.get(f"/api/network/runs/{run_id}")
    assert historical.status_code == 200
    compact_result = dict(result)
    compact_result.pop("charge_details", None)
    compact_result.pop("baseline_charge_details", None)
    assert historical.json() == compact_result
    assert client.get(f"/api/network/scenarios/{scenario_id}/result").status_code == 404
    assert client.get("/api/network/runs/does-not-exist").status_code == 404


def test_name_only_update_preserves_solved_revision_and_result() -> None:
    scenario = _create_scenario("Name does not change the plan")
    scenario_id = str(scenario["scenario_id"])
    result = _run(scenario_id)["result"]
    response = client.patch(f"/api/network/scenarios/{scenario_id}", json={
        "expected_revision": scenario["revision"],
        "scenario_name": "Renamed solved plan",
    })
    assert response.status_code == 200
    assert response.json()["revision"] == result["revision"]
    assert response.json()["status"] == "solved"
    assert client.get(f"/api/network/scenarios/{scenario_id}/result").json()["run_id"] == result["run_id"]


def test_parameter_edit_keeps_last_solved_result_until_recalculated() -> None:
    scenario = _create_scenario("Keep last result on parameter edit")
    scenario_id = str(scenario["scenario_id"])
    result = _run(scenario_id)["result"]
    response = client.patch(f"/api/network/scenarios/{scenario_id}", json={
        "expected_revision": scenario["revision"],
        "assumptions": {"unmet_penalty_per_case": 999},
    })
    assert response.status_code == 200
    assert response.json()["revision"] == result["revision"] + 1
    assert response.json()["status"] == "draft"
    previous = client.get(f"/api/network/scenarios/{scenario_id}/result")
    assert previous.status_code == 200
    assert previous.json()["run_id"] == result["run_id"]
    assert previous.json()["revision"] == result["revision"]
