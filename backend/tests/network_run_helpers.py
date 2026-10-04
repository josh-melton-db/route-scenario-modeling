from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CompletedNetworkRun:
    payload: dict[str, Any]
    status_code: int = 200

    def json(self) -> dict[str, Any]:
        return self.payload


def run_network_scenario(client: Any, scenario_id: str) -> CompletedNetworkRun:
    scenario = client.get(f"/api/network/scenarios/{scenario_id}").json()
    launched = client.post(
        f"/api/network/scenarios/{scenario_id}/run",
        json={"expected_revision": scenario["revision"]},
    )
    assert launched.status_code == 202, launched.text
    record = launched.json()
    deadline = time.monotonic() + 30
    while record["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.05)
        record = client.get(record["status_url"]).json()
    assert record["status"] == "succeeded", record
    result = client.get(f"/api/network/runs/{record['run_id']}")
    assert result.status_code == 200
    from backend.services.network_scenarios import network_scenario_service
    full_result = network_scenario_service.get_run_snapshot(record["run_id"]).result
    current = client.get(f"/api/network/scenarios/{scenario_id}")
    assert current.status_code == 200
    return CompletedNetworkRun({
        "scenario": current.json(),
        "result": full_result.model_dump(mode="json"),
    })


def reassign_network_demand(client: Any, parent_run_id: str) -> CompletedNetworkRun:
    launched = client.post(f"/api/network/runs/{parent_run_id}/reassign")
    assert launched.status_code == 202, launched.text
    record = launched.json()
    deadline = time.monotonic() + 30
    while record["status"] in {"queued", "running", "completion_pending"} and time.monotonic() < deadline:
        time.sleep(0.05)
        record = client.get(record["status_url"]).json()
    assert record["status"] == "succeeded", record
    from backend.services.network_scenarios import network_scenario_service
    snapshot = network_scenario_service.get_run_snapshot(record["run_id"])
    return CompletedNetworkRun({
        "scenario": snapshot.scenario.model_dump(mode="json"),
        "result": snapshot.result.model_dump(mode="json"),
    })
