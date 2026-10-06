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
