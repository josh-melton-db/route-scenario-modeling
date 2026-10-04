from __future__ import annotations

import time
import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.main import app
from backend.models import (
    NetworkDemandChange, NetworkRunRecord, NetworkScenario,
    NetworkScenarioAssumptions,
)
from backend.services.network_run_jobs import (
    NetworkRunJobRepository,
    network_run_idempotency_key,
)


client = TestClient(app)


def _scenario() -> dict[str, object]:
    options = client.get("/api/network/options").json()
    start = options["default_horizon_start"]
    response = client.post(
        "/api/network/scenarios",
        json={
            "scenario_name": "Durable network run",
            "demand_plan_version_id": options["default_demand_plan_version_id"],
            "capacity_plan_version_id": options["default_capacity_plan_version_id"],
            "horizon_start": start,
            "horizon_end": (date.fromisoformat(start) + timedelta(days=1)).isoformat(),
            "region_id": "REGION_TOLA",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_update_requires_matching_revision() -> None:
    scenario = _scenario()
    scenario_id = str(scenario["scenario_id"])
    first = client.patch(
        f"/api/network/scenarios/{scenario_id}",
        json={"expected_revision": 1, "scenario_name": "revision two"},
    )
    assert first.status_code == 200
    assert first.json()["revision"] == 2
    stale = client.patch(
        f"/api/network/scenarios/{scenario_id}",
        json={"expected_revision": 1, "scenario_name": "lost update"},
    )
    assert stale.status_code == 409
    assert client.get(f"/api/network/scenarios/{scenario_id}").json()["scenario_name"] == "revision two"


def test_async_launch_is_idempotent_and_produces_immutable_result() -> None:
    scenario = _scenario()
    scenario_id = str(scenario["scenario_id"])
    payload = {"expected_revision": scenario["revision"]}
    first = client.post(f"/api/network/scenarios/{scenario_id}/run", json=payload)
    second = client.post(f"/api/network/scenarios/{scenario_id}/run", json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    run_id = first.json()["run_id"]
    deadline = time.monotonic() + 20
    status = first.json()
    while status["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.05)
        status = client.get(f"/api/network/run-requests/{run_id}").json()
    assert status["status"] == "succeeded", status
    result = client.get(f"/api/network/runs/{run_id}")
    assert result.status_code == 200
    assert result.json()["run_id"] == run_id
    assert result.json()["optimization_objective_cost"] >= 0
    assert "objective_to_rated_cost_gap" in result.json()

    # A completed old revision remains historical but cannot become current.
    from backend.services.network_scenarios import network_scenario_service
    snapshot = network_scenario_service.get_run_snapshot(run_id)
    edited = client.patch(
        f"/api/network/scenarios/{scenario_id}",
        json={"expected_revision": 1, "scenario_name": "edited during solve"},
    )
    assert edited.status_code == 200
    stale_result = snapshot.result.model_copy(
        update={"run_id": f"network-run-{uuid.uuid4()}"}
    )
    became_current = network_scenario_service.repository.save_result(
        snapshot.scenario,
        stale_result,
        network_rows=snapshot.network_rows,
        flow_rows=snapshot.flow_rows,
        cost_rows=snapshot.cost_rows,
        expected_revision=1,
    )
    assert became_current is False
    assert network_scenario_service.get(scenario_id).revision == 2
    assert network_scenario_service.get_run_snapshot(stale_result.run_id).result.run_id == stale_result.run_id
    assert network_scenario_service.repository.prune_history(scenario_id, retain=1) == 1
    retained = [
        row for row in network_scenario_service.repository._run_snapshots.values()
        if row.scenario.scenario_id == scenario_id
    ]
    assert len(retained) == 1


def test_idempotency_key_changes_with_frozen_revision() -> None:
    scenario = NetworkScenario(
        scenario_id="NSC_TEST", scenario_name="test",
        demand_plan_version_id="demand", capacity_plan_version_id="capacity",
        horizon_start="2026-01-01", horizon_end="2026-01-02", region_id="ALL",
        assumptions=NetworkScenarioAssumptions(),
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    assert network_run_idempotency_key(scenario) == network_run_idempotency_key(
        scenario.model_copy(deep=True)
    )
    assert network_run_idempotency_key(scenario) != network_run_idempotency_key(
        scenario.model_copy(update={"revision": 2})
    )


def test_queue_admission_is_bounded() -> None:
    repository = NetworkRunJobRepository()
    scenario = NetworkScenario(
        scenario_id="NSC_QUEUE", scenario_name="queue",
        demand_plan_version_id="demand", capacity_plan_version_id="capacity",
        horizon_start="2026-01-01", horizon_end="2026-01-02", region_id="ALL",
        assumptions=NetworkScenarioAssumptions(),
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    record, created = repository.create(scenario, max_queued=1)
    assert created and record.status == "queued"
    duplicate, created = repository.create(scenario, max_queued=1)
    assert not created and duplicate.run_id == record.run_id
    cancelled = repository.cancel(record.run_id)
    assert cancelled.status == "cancelled"
    assert not repository.claim(record.run_id, lease_seconds=60)


def test_reassignment_completion_resolves_only_frozen_requests(monkeypatch) -> None:
    from backend.services.demand_changes import DemandChangeRepository, demand_change_service
    from backend.services.network_run_jobs import NetworkRunManager

    repository = DemandChangeRepository()
    monkeypatch.setattr(demand_change_service, "repository", repository)
    first = NetworkDemandChange(
        change_id="NDC_FROZEN", parent_run_id="parent-run",
        depot_plan_id="plan", route_scenario_id="route", depot_id="DPT",
        service_date="2026-10-02", customer_id="C1", cases=1,
        created_at="2026-10-02T00:00:00+00:00",
    )
    second = first.model_copy(update={"change_id": "NDC_LATER", "customer_id": "C2"})
    repository.create(first)
    repository.claim("parent-run")
    # A later request is not part of the frozen completion metadata.
    repository.release_claim("parent-run")
    repository.create(second)
    repository.claim("parent-run")
    record = NetworkRunRecord(
        run_id="child-run", scenario_id="child", revision=1,
        idempotency_key="reassign", status="completion_pending",
        status_url="/status", queued_at="2026-10-02T00:00:00+00:00",
        run_kind="reassignment", parent_run_id="parent-run",
        demand_change_ids=["NDC_FROZEN"],
    )
    NetworkRunManager._apply_completion(record)
    rows = {row.change_id: row for row in repository.list("parent-run")}
    assert rows["NDC_FROZEN"].status == "resolved"
    assert rows["NDC_FROZEN"].resolved_run_id == "child-run"
    assert rows["NDC_LATER"].status == "pending"
