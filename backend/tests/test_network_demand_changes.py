from fastapi.testclient import TestClient

from backend.main import app
from backend.services.baseline_service import baseline_service
from backend.services.demand_changes import demand_change_service
from backend.services.network_scenarios import network_scenario_service
from backend.models import NetworkScenarioCreateRequest
from types import SimpleNamespace


client = TestClient(app)


def test_new_scenario_inherits_source_tariffs_only_when_omitted(monkeypatch) -> None:
    options = client.get("/api/network/options").json()
    demand = options["demand_plans"][0]
    capacity = options["capacity_plans"][0]
    tariff = {
        "rule_id": "T-INHERITED",
        "origin_country": "MX",
        "destination_country": "US",
        "effective_start": demand["horizon_start"],
        "effective_end": demand["horizon_end"],
        "amount_per_case": 1.25,
    }
    monkeypatch.setattr(
        baseline_service,
        "get_state",
        lambda: SimpleNamespace(active_revision_id="REV-TARIFF"),
    )
    monkeypatch.setattr(
        baseline_service,
        "get_revision",
        lambda _revision_id: SimpleNamespace(
            rows={"baseline_revision_metadata": [{"tariffs": [tariff]}]}
        ),
    )
    common = {
        "scenario_name": "Tariff inheritance",
        "demand_plan_version_id": demand["plan_version_id"],
        "capacity_plan_version_id": capacity["plan_version_id"],
        "horizon_start": demand["horizon_start"],
        "horizon_end": demand["horizon_start"],
        "region_id": "ALL",
    }

    inherited = network_scenario_service.create(
        NetworkScenarioCreateRequest.model_validate(common)
    )
    cleared = network_scenario_service.create(
        NetworkScenarioCreateRequest.model_validate(
            {**common, "scenario_name": "Tariff cleared", "assumptions": {"tariffs": []}}
        )
    )

    assert [rule.rule_id for rule in inherited.assumptions.tariffs] == ["T-INHERITED"]
    assert cleared.assumptions.tariffs == []


def test_active_baseline_plan_ids_resolve_without_repository_scenarios() -> None:
    state = baseline_service.get_state()
    snapshot = network_scenario_service.get_run_snapshot(state.active_plan_run_id)
    assert snapshot.scenario.scenario_id == state.active_plan_scenario_id
    assert network_scenario_service.get(state.active_plan_scenario_id) == snapshot.scenario
    assert network_scenario_service.run_result(state.active_plan_run_id) == snapshot.result
    assert all(row.scenario_id != state.active_plan_scenario_id for row in network_scenario_service.list())
    assert client.post(f"/api/network/scenarios/{state.active_plan_scenario_id}/run").status_code == 409
    assert client.patch(f"/api/network/scenarios/{state.active_plan_scenario_id}", json={"scenario_name": "No"}).status_code == 409
    assert client.delete(f"/api/network/scenarios/{state.active_plan_scenario_id}").status_code == 409


def test_release_api_reassigns_conserves_and_preserves_parent_snapshot() -> None:
    options = client.get("/api/network/options").json()
    demand = options["demand_plans"][0]
    capacity = options["capacity_plans"][0]
    day = demand["horizon_start"]
    created = client.post("/api/network/scenarios", json={
        "scenario_name": "Demand release lifecycle",
        "demand_plan_version_id": demand["plan_version_id"],
        "capacity_plan_version_id": capacity["plan_version_id"],
        "horizon_start": day, "horizon_end": day, "region_id": "REGION_TOLA",
    })
    assert created.status_code == 201
    solved = client.post(f"/api/network/scenarios/{created.json()['scenario_id']}/run")
    assert solved.status_code == 200
    run_id = solved.json()["result"]["run_id"]
    parent_before = network_scenario_service.get_run_snapshot(run_id)
    lanes = {str(r["lane_id"]): r for r in parent_before.network_rows["dim_network_lanes"]}
    depot_id = next(str(lanes[str(r["lane_id"])]["destination_endpoint_id"]) for r in parent_before.flow_rows if r["lane_type"] == "LINEHAUL" and int(r["assigned_units"]) > 0 and str(lanes[str(r["lane_id"])]["destination_endpoint_id"]).startswith("DPT_TOLA"))

    targets_response = client.get(f"/api/network/runs/{run_id}/depots/{depot_id}/release-targets", params={"service_date": day})
    assert targets_response.status_code == 200
    target = targets_response.json()[0]
    assert set(target) == {"customer_id", "customer_name", "assigned_cases"}
    plan = client.post(f"/api/network/runs/{run_id}/depots/{depot_id}/plans", params={"priority_date": day}).json()
    route_scenario = client.post(f"/api/depot-plans/{plan['plan_set_id']}/scenarios", json={"scenario_name": "Release candidate"}).json()
    request = {"depot_plan_id": plan["plan_set_id"], "route_scenario_id": route_scenario["route_scenario_id"], "service_date": day, "customer_id": target["customer_id"], "cases": min(2, target["assigned_cases"]), "kind": "release"}
    posted = client.post(f"/api/network/runs/{run_id}/demand-changes", json=request)
    assert posted.status_code == 201
    assert demand_change_service.has_pending(run_id)
    assert client.post(f"/api/network/runs/{run_id}/demand-changes", json=request).status_code == 409

    reassigned = client.post(f"/api/network/runs/{run_id}/reassign")
    assert reassigned.status_code == 200
    new_run_id = reassigned.json()["result"]["run_id"]
    assert new_run_id != run_id
    assert not demand_change_service.has_pending(run_id)
    assert client.post(f"/api/network/runs/{run_id}/reassign").status_code == 409
    assert network_scenario_service.get_run_snapshot(run_id) == parent_before

    child = network_scenario_service.get_run_snapshot(new_run_id)
    assert child.result.baseline_overview.kpis == parent_before.result.overview.kpis
    layer_totals = {layer: sum(int(r["assigned_units"]) for r in child.flow_rows if r["lane_type"] == layer) for layer in ("LINEHAUL", "MARKET", "DELIVERY")}
    assert len(set(layer_totals.values())) == 1
    child_lanes = {str(r["lane_id"]): r for r in child.network_rows["dim_network_lanes"]}
    released_delivery = [r for r in child.flow_rows if r["lane_type"] == "DELIVERY" and int(r["assigned_units"]) > 0 and str(child_lanes[str(r["lane_id"])]["destination_endpoint_id"]) == target["customer_id"] and str(child_lanes[str(r["lane_id"])]["origin_endpoint_id"]) != depot_id]
    assert released_delivery
    generated_lane_id = str(released_delivery[0]["lane_id"])
    generated_capacity = next(r for r in child.network_rows["lane_capacity_daily"] if str(r["lane_id"]) == generated_lane_id and str(r["service_date"])[:10] == day)
    assert int(generated_capacity["capacity_units"]) == request["cases"]
    rerun = client.post(f"/api/network/scenarios/{child.scenario.scenario_id}/run")
    assert rerun.status_code == 200
    replay = network_scenario_service.get_run_snapshot(rerun.json()["result"]["run_id"])
    assert replay.scenario.assumptions.parent_run_id == run_id
    assert replay.scenario.assumptions.release_overlays
    replay_lanes = {str(r["lane_id"]): r for r in replay.network_rows["dim_network_lanes"]}
    assert any(r["lane_type"] == "DELIVERY" and int(r["assigned_units"]) > 0 and str(replay_lanes[str(r["lane_id"])]["destination_endpoint_id"]) == target["customer_id"] and str(replay_lanes[str(r["lane_id"])]["origin_endpoint_id"]) != depot_id for r in replay.flow_rows)
    alternate = next((row for row in options["capacity_plans"] if row["plan_version_id"] != capacity["plan_version_id"]), None)
    alternate_before = None
    if alternate:
        params = {"demand_plan_version_id": demand["plan_version_id"], "capacity_plan_version_id": alternate["plan_version_id"], "horizon_start": day, "horizon_end": day, "region_id": "REGION_TOLA"}
        alternate_before = client.get("/api/network/overview", params=params).json()["kpis"]
    proposal = baseline_service.propose(new_run_id)
    assert proposal.run_id == new_run_id
    accepted = baseline_service.accept(proposal.proposal_id)
    assert accepted.active_run_id == new_run_id
    if alternate:
        alternate_after = client.get("/api/network/overview", params=params).json()["kpis"]
        assert alternate_after == alternate_before
    baseline_service.reset()
