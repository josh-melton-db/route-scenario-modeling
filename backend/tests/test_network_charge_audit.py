from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.main import app
from backend.tests.network_run_helpers import run_network_scenario


client = TestClient(app)


def _solve() -> dict:
    options = client.get("/api/network/options").json()
    start = options["default_horizon_start"]
    created = client.post(
        "/api/network/scenarios",
        json={
            "scenario_name": "Paginated rate audit",
            "demand_plan_version_id": options["default_demand_plan_version_id"],
            "capacity_plan_version_id": options["default_capacity_plan_version_id"],
            "horizon_start": start,
            "horizon_end": (date.fromisoformat(start) + timedelta(days=1)).isoformat(),
            "region_id": "ALL",
        },
    )
    assert created.status_code == 201
    response = run_network_scenario(client, created.json()["scenario_id"])
    result = response.json()["result"]
    result.pop("charge_details", None)
    result.pop("baseline_charge_details", None)
    return result


def test_run_summary_omits_ledgers_and_exposes_diagnostics_and_audit_pages() -> None:
    result = _solve()
    assert "charge_details" not in result
    assert "baseline_charge_details" not in result
    diagnostics = result["diagnostics"]
    assert diagnostics["scenario_charge_count"] > 0
    assert diagnostics["baseline_charge_count"] > 0
    assert diagnostics["summary_json_bytes"] > 0
    assert all(value >= 0 for value in diagnostics["stage_seconds"].values())
    assert {
        "input_loading_and_copying",
        "contract_and_tariff_resolution",
        "objective_cost_preparation",
        "network_solve",
        "scenario_rating",
        "baseline_rating",
        "overview_construction",
        "result_assembly",
        "persistence",
        "api_serialization",
    } <= diagnostics["stage_seconds"].keys()

    request = client.get(f"/api/network/run-requests/{result['run_id']}")
    assert request.status_code == 200
    transport = request.json()["diagnostics"]
    assert transport["api_response_bytes"] > 0
    assert transport["stage_seconds"]["api_response_encoding"] >= 0

    first = client.get(
        f"/api/network/runs/{result['run_id']}/charges",
        params={"side": "scenario", "offset": 0, "limit": 5},
    )
    assert first.status_code == 200
    page = first.json()
    assert len(page["items"]) == 5
    assert page["total"] == diagnostics["scenario_charge_count"]
    assert page["coverage"] == result["scenario_rate_coverage"]
    assert page["items"] == sorted(
        page["items"],
        key=lambda row: (-row["total_cost"], row["service_date"], row["lane_id"]),
    )

    lane = page["items"][0]["lane_id"]
    filtered = client.get(
        f"/api/network/runs/{result['run_id']}/charges",
        params={"side": "scenario", "query": lane, "limit": 250},
    )
    assert filtered.status_code == 200
    assert filtered.json()["items"]
    assert all(lane.lower() in row["lane_id"].lower() for row in filtered.json()["items"])


def test_charge_audit_validates_parameters_and_missing_runs() -> None:
    assert client.get("/api/network/runs/missing/charges").status_code == 404
    assert client.get("/api/network/runs/missing/charges?side=other").status_code == 422
    assert client.get("/api/network/runs/missing/charges?offset=-1").status_code == 422
    assert client.get("/api/network/runs/missing/charges?limit=251").status_code == 422
