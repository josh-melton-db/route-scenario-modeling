from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_health_and_metadata_endpoints() -> None:
    assert client.get("/api/health").status_code == 200

    depots = client.get("/api/meta/depots")
    assert depots.status_code == 200
    assert [depot["depot_id"] for depot in depots.json()] == ["DPT_NORTH"]

    days = client.get("/api/meta/days")
    assert days.status_code == 200
    assert days.json() == ["Tuesday"]

    carriers = client.get("/api/meta/carriers")
    assert carriers.status_code == 200
    assert carriers.json()[0]["carrier_id"] == "GL_LOGISTICS"

    contracts = client.get("/api/meta/carrier-contracts")
    assert contracts.status_code == 200
    assert {row["carrier_id"] for row in contracts.json()} == {"GL_LOGISTICS", "MIDWEST_EXPRESS"}

    operating = client.get("/api/meta/operating-parameters")
    assert operating.status_code == 200
    assert operating.json()[0]["max_route_minutes"] == 600

    costs = client.get("/api/meta/cost-parameters")
    assert costs.status_code == 200
    assert costs.json()[0]["cost_per_mile"] == 3

    scenario_types = client.get("/api/meta/scenario-types")
    assert scenario_types.status_code == 200
    assert {row["scenario_type"] for row in scenario_types.json()} >= {
        "baseline",
        "driver_count_change",
        "facility_move",
    }


def test_baseline_endpoints() -> None:
    network = client.get("/api/baseline/network?depot_id=DPT_NORTH&delivery_day=Tuesday")
    assert network.status_code == 200
    assert len(network.json()["routes"]) == 4

    kpis = client.get("/api/baseline/kpis?depot_id=DPT_NORTH&delivery_day=Tuesday")
    assert kpis.status_code == 200
    assert kpis.json()["cost_breakdown"]["total_cost"] == 4920


def test_network_overview_endpoints() -> None:
    options = client.get("/api/network/options")
    assert options.status_code == 200
    option_payload = options.json()
    assert option_payload["default_lane_type"] == "LINEHAUL"
    assert option_payload["default_region_id"] == "ALL"
    assert option_payload["default_capacity_plan_version_id"] == (
        "CAPACITY_US_SE_CONSTRAINED_V2"
    )
    assert len(option_payload["regions"]) == 5
    assert len(option_payload["facilities"]) == 32
    assert len(option_payload["capacity_plans"]) == 2
    assert {row["metric_id"] for row in option_payload["metrics"]} == {
        "assigned_flow",
        "utilization",
        "cost",
        "cost_per_unit",
    }

    overview = client.get("/api/network/overview")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["context"]["lane_type"] == "LINEHAUL"
    assert payload["kpis"]["demand_units"] > payload["kpis"]["assigned_units"]
    assert payload["kpis"]["unmet_units"] > 0
    assert payload["kpis"]["total_cost"] > 0
    assert len(payload["facilities"]) == 32
    assert len(payload["lanes"]) == 56
    assert payload["insights"]
    assert all(row["utilization_pct"] <= 100 for row in payload["facilities"])
    atlanta = next(
        row
        for row in payload["facilities"]
        if row["facility_id"] == "DC_SOUTHEAST_ATLANTA"
    )
    assert atlanta["assigned_units"] == atlanta["capacity_units"]
    assert atlanta["utilization_pct"] == 100

    selected_lane = payload["lanes"][0]
    assert selected_lane["origin_location"]["lat"]
    assert selected_lane["destination_location"]["lng"]


def test_network_overview_filters_and_validation() -> None:
    delivery = client.get(
        "/api/network/overview",
        params={
            "lane_type": "DELIVERY",
            "metric": "cost_per_unit",
            "horizon_start": "2026-09-21",
            "horizon_end": "2026-09-21",
        },
    )
    assert delivery.status_code == 200
    payload = delivery.json()
    assert payload["context"]["metric"] == "cost_per_unit"
    assert len(payload["lanes"]) == 2400
    assert all(row["lane_type"] == "DELIVERY" for row in payload["lanes"])

    normal = client.get(
        "/api/network/overview",
        params={
            "capacity_plan_version_id": "CAPACITY_US_BASELINE_V1",
            "region_id": "REGION_SOUTHEAST",
        },
    )
    assert normal.status_code == 200
    assert normal.json()["kpis"]["unmet_units"] == 0

    invalid_range = client.get(
        "/api/network/overview",
        params={"horizon_start": "2026-09-22", "horizon_end": "2026-09-21"},
    )
    assert invalid_range.status_code == 400

    missing_region = client.get(
        "/api/network/overview", params={"region_id": "REGION_UNKNOWN"}
    )
    assert missing_region.status_code == 404


def test_scenario_lifecycle() -> None:
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

    history = client.get("/api/scenarios?limit=10")
    assert history.status_code == 200
    assert history.json()[0]["scenario_id"] == scenario_id
    assert history.json()[0]["parameters"]["driver_delta"] == -1
    assert history.json()[0]["has_results"] is True

    validated = client.post(f"/api/scenarios/{scenario_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True

    started = client.post(f"/api/scenarios/{scenario_id}/run")
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    run = client.get(f"/api/runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["scenario_id"] == scenario_id

    result = client.get(f"/api/scenarios/{scenario_id}/results")
    assert result.status_code == 200
    assert result.json()["scenario_id"] == scenario_id
    assert result.json()["scenario_kpis"]["driver_count"] == 3


def test_delete_scenario() -> None:
    created = client.post(
        "/api/scenarios",
        json={
            "scenario_name": "Delete me",
            "scenario_type": "custom",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "parameters": {"changes": []},
        },
    )
    scenario_id = created.json()["scenario"]["scenario_id"]

    assert client.delete(f"/api/scenarios/{scenario_id}").status_code == 204
    assert client.get(f"/api/scenarios/{scenario_id}").status_code == 404
    assert client.delete("/api/scenarios/baseline").status_code == 400
