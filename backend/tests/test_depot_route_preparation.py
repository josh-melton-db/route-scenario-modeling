from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.depot_route_preparation import DepotRoutePreparationManager, prepare_depot_routes


def test_manager_deduplicates_running_preparation_and_records_failures():
    release = Event()
    finished = Event()
    def prepare(**kwargs):
        release.wait(2)
        finished.set()
        raise ValueError("Outside the planning horizon")
    manager = DepotRoutePreparationManager(prepare)
    started = manager.start("2026-10-06")
    assert manager.start("2026-10-06")["preparation_id"] == started["preparation_id"]
    with pytest.raises(HTTPException) as conflict:
        manager.start("2026-10-07")
    assert conflict.value.status_code == 409
    release.set()
    assert finished.wait(2)
    # Take the lock after the worker's update, rather than racing the event.
    from time import monotonic, sleep
    deadline = monotonic() + 2
    while manager.is_running() and monotonic() < deadline:
        sleep(0.01)
    status = manager.status(started["preparation_id"])
    assert status["state"] == "failed"
    assert status["error"] == "Outside the planning horizon"
    with pytest.raises(HTTPException) as missing:
        manager.status("missing")
    assert missing.value.status_code == 404


def test_failed_depot_does_not_prevent_other_depots_preparing():
    snapshot = SimpleNamespace(
        scenario=SimpleNamespace(horizon_start="2026-10-06", horizon_end="2026-10-06"),
        result=SimpleNamespace(run_id="run"), network_rows={"dim_facilities": [
            {"facility_id": "A", "facility_type": "depot"},
            {"facility_id": "B", "facility_type": "depot"},
            {"facility_id": "DC", "facility_type": "distribution_center"},
        ]},
    )
    def get_plan(run_id, depot_id, **kwargs):
        if depot_id == "A":
            raise ValueError("Fleet unavailable")
        return SimpleNamespace(plan_set_id="plan-B")
    plans = SimpleNamespace(get_or_create_plan=get_plan, solve_day=lambda *args: None,
        get_day=lambda *args: SimpleNamespace(default_status="infeasible",
            default_result=SimpleNamespace(result_id="saved-result"), error=None))
    report = prepare_depot_routes(baseline=SimpleNamespace(get_plan_run=lambda: snapshot), plans=plans)
    assert report["ready"] == 1
    assert report["failed"] == 1
    assert report["depots"][1]["result_id"] == "saved-result"


def test_preparation_api_validates_dates_and_returns_pollable_id(monkeypatch):
    from backend.services import depot_route_preparation as module
    manager = SimpleNamespace(start=lambda service_date: {"preparation_id": "prep", "service_date": service_date, "state": "running"},
        status=lambda preparation_id: {"preparation_id": preparation_id, "state": "completed"})
    monkeypatch.setattr(module, "depot_route_preparation_manager", manager)
    client = TestClient(app)
    response = client.post("/api/network/baseline/depot-routes/prepare", json={"service_date": "2026-10-06"})
    assert response.status_code == 202
    assert response.json()["service_date"] == "2026-10-06"
    assert client.get("/api/network/baseline/depot-routes/preparations/prep").json()["state"] == "completed"
    assert client.post("/api/network/baseline/depot-routes/prepare", json={"service_date": "invalid"}).status_code == 422


def test_daily_preparation_refreshes_before_building_plan(monkeypatch):
    from backend.services import baseline_service as baseline_module
    from backend.services import depot_plans as plans_module
    from backend.services import depot_route_preparation as module
    calls = []
    monkeypatch.setattr(baseline_module, "baseline_service", SimpleNamespace(
        advance_daily_baseline=lambda: calls.append("refresh")))
    monkeypatch.setattr(plans_module, "depot_plan_service", "plans")
    monkeypatch.setattr(module, "prepare_depot_routes", lambda **kwargs: calls.append(kwargs) or {"failed": 0})
    module.prepare_active_depot_routes(service_date="2026-10-08", refresh_daily_baseline=True)
    assert calls[0] == "refresh"
    assert calls[1]["service_date"] == "2026-10-08"


def test_advance_daily_baseline_keeps_prior_revisions_and_proposals(monkeypatch):
    from backend.services import baseline_repository as module
    monkeypatch.setattr(module, "get_data_backend", lambda: "stub")
    repository = module.BaselineRepository()
    old = module.BaselineRevision("old", None, None, None, {"dim_facilities": []})
    new = module.BaselineRevision("today", None, None, None, {"dim_facilities": []})
    repository.seed(old)
    proposal = module.BaselineProposalRecord("proposal", "run", "old", old)
    repository._proposals["proposal"] = proposal
    repository.advance_original(new)
    assert repository.ids() == ("today", "today")
    assert repository.revision("old").revision_id == "old"
    assert repository._proposals["proposal"] == proposal


def test_daily_canonical_pins_route_policy_and_changes_identity_without_mutating_history(monkeypatch):
    from copy import deepcopy
    from backend.services import baseline_service as module
    from backend.services import rates, store_provider
    from backend.baseline_models import BaselineRouteCoverage

    plans = {
        "demand_plan_versions": [{"plan_version_id": "D", "horizon_start": "2026-10-08", "horizon_end": "2026-11-04"}],
        "capacity_plan_versions": [{"plan_version_id": "C", "horizon_start": "2026-10-08", "horizon_end": "2026-11-04"}],
        "dim_network_lanes": [{"lane_id": "L"}],
        "demand_plan_daily": [{"service_date": "2026-10-08", "depot_id": "DEPOT"}],
        "baseline_network_flow_daily": [{"lane_id": "L"}],
    }
    resources = {
        "fleet": [{"vehicle_id": "V", "depot_id": "DEPOT", "capacity_cases": 700}],
        "operating_parameters": [{"parameter_set_id": "default", "max_stops_per_route": 12}],
        "cost_parameters": [{"parameter_set_id": "default", "cost_per_mile": 2}],
    }
    monkeypatch.setattr(module.network_overview_service, "_load_option_rows", lambda: deepcopy(plans))
    monkeypatch.setattr(module.network_overview_service, "_load_rows", lambda **kwargs: deepcopy(plans))
    monkeypatch.setattr(store_provider, "get_store", lambda: SimpleNamespace(load_solver_base_tables=lambda: resources))
    monkeypatch.setattr(rates, "list_rate_contract_details", lambda store: rates.canonical_rate_contract_details())
    monkeypatch.setattr(module.BaselineService, "_coverage", lambda self, rows: BaselineRouteCoverage(ready=False, covered_dates=0, expected_dates=1, covered_depots=0, expected_depots=1, message="pending"))
    service = module.BaselineService()
    legacy = service._canonical_revision()
    first = service._canonical_revision(include_route_resources=True)
    repeat = service._canonical_revision(include_route_resources=True)
    assert first.revision_id == repeat.revision_id
    assert first.revision_id != legacy.revision_id
    assert "dim_fleet_assets" not in legacy.rows
    assert first.rows["dim_fleet_assets"][0]["max_stops_per_route"] == 12
    assert "max_stops_per_route" not in resources["fleet"][0]
    resources["operating_parameters"][0]["max_stops_per_route"] = 15
    second = service._canonical_revision(include_route_resources=True)
    assert second.revision_id != first.revision_id
    assert first.rows["operating_parameters"][0]["max_stops_per_route"] == 12
    assert second.rows["dim_fleet_assets"][0]["max_stops_per_route"] == 15
    assert first.rows["route_cost_parameters"] == resources["cost_parameters"]
    assert first.rows["baseline_revision_metadata"][0]["route_resource_policy"]["resource_sha256"] != second.rows["baseline_revision_metadata"][0]["route_resource_policy"]["resource_sha256"]
