from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

from backend.models import NetworkScenario, NetworkScenarioAssumptions
from backend.services.baseline_service import baseline_service
from backend.services.network_overview import network_overview_service
from backend.services.network_scenarios import (
    NetworkScenarioRepository,
    _decode_snapshot_envelope,
    _encode_snapshot_envelope,
    _filter_revision_rows,
    _snapshot_manifest_with_deltas,
)
import pytest
from route_opt.depot_planning import materialize_depot_targets


def _scenario(start: str, end: str, revision_id: str) -> NetworkScenario:
    options = network_overview_service.get_options()
    return NetworkScenario(
        scenario_id="NSC_DEDUP_TEST",
        scenario_name="Snapshot dedup test",
        source_baseline_revision_id=revision_id,
        demand_plan_version_id=options.default_demand_plan_version_id,
        capacity_plan_version_id=options.default_capacity_plan_version_id,
        horizon_start=start,
        horizon_end=end,
        region_id="ALL",
        assumptions=NetworkScenarioAssumptions(
            source_baseline_revision_id=revision_id
        ),
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_28_day_reference_manifest_is_tiny_and_reconstructs_exact_rows(monkeypatch) -> None:
    options = network_overview_service.get_options()
    start = options.default_horizon_start
    end = (date.fromisoformat(start) + timedelta(days=27)).isoformat()
    scenario = _scenario(start, end, "REV-IMMUTABLE")
    full = network_overview_service.load_rows(
        demand_plan_version_id=scenario.demand_plan_version_id,
        capacity_plan_version_id=scenario.capacity_plan_version_id,
        horizon_start=date.fromisoformat(start),
        horizon_end=date.fromisoformat(end),
    )
    # The immutable revision is the unfiltered source; reconstruction applies
    # the same plan/horizon predicate as the canonical loader.
    monkeypatch.setattr(
        baseline_service,
        "get_revision",
        lambda _revision_id: SimpleNamespace(rows=full),
    )
    manifest = _snapshot_manifest_with_deltas({
        "format": "network_rows_reference_v1",
        "base_kind": "baseline_revision",
        "revision_id": "REV-IMMUTABLE",
        "filter_plan_horizon": True,
    }, full, full)
    reconstructed = NetworkScenarioRepository()._reconstruct_network_rows(
        scenario, manifest
    )
    assert reconstructed == _filter_revision_rows(full, scenario)
    full_bytes = len(json.dumps(full, separators=(",", ":"), default=str).encode())
    stored_bytes = len(json.dumps({"network_rows_payload": {}, "network_rows_manifest": manifest}, separators=(",", ":")).encode())
    assert full_bytes > 100_000_000
    assert stored_bytes < full_bytes * 0.001

    depots = [
        str(row["facility_id"]) for row in full["dim_facilities"]
        if str(row.get("facility_type", "")).upper() == "DEPOT"
    ]
    for depot_id in depots:
        expected = materialize_depot_targets(
            full, full["baseline_network_flow_daily"], depot_id, start
        )
        if expected:
            assert materialize_depot_targets(
                reconstructed,
                reconstructed["baseline_network_flow_daily"],
                depot_id,
                start,
            ) == expected
            break
    else:
        raise AssertionError("Fixture did not contain a depot/day with delivery targets")


def test_parent_manifest_replays_outputs_and_solver_table_replacements(monkeypatch) -> None:
    options = network_overview_service.get_options()
    scenario = _scenario(
        options.default_horizon_start,
        options.default_horizon_start,
        "REV-PARENT",
    )
    parent_rows = {
        "dim_network_lanes": [{"lane_id": "old"}],
        "lane_capacity_daily": [{"lane_id": "old", "capacity_units": 1}],
        "network_customer_assignments_daily": [],
        "baseline_network_flow_daily": [{"lane_id": "stale"}],
    }
    parent = SimpleNamespace(
        network_rows=parent_rows,
        flow_rows=[{"lane_id": "parent-flow"}],
        cost_rows=[{"lane_id": "parent-cost"}],
    )
    repository = NetworkScenarioRepository()
    monkeypatch.setattr(repository, "run_snapshot", lambda _run_id: parent)
    manifest = {
        "base_kind": "parent_run",
        "parent_run_id": "parent-run",
        "table_replacements": {
            "dim_network_lanes": [{"lane_id": "generated"}],
            "lane_capacity_daily": [{"lane_id": "generated", "capacity_units": 5}],
        },
    }
    rows = repository._reconstruct_network_rows(scenario, manifest)
    assert rows["baseline_network_flow_daily"] == parent.flow_rows
    assert rows["network_flow_cost_daily"] == parent.cost_rows
    assert rows["dim_network_lanes"] == [{"lane_id": "generated"}]
    assert rows["lane_capacity_daily"][0]["capacity_units"] == 5


def test_compressed_envelope_round_trips_and_rejects_corruption() -> None:
    flow = [{"service_date": "2026-10-02", "lane_id": "L1", "assigned_units": 42}]
    cost = [{"service_date": "2026-10-02", "lane_id": "L1", "total_cost": 12.5}]
    payload, raw_size, digest = _encode_snapshot_envelope(flow, cost)
    assert _decode_snapshot_envelope(
        payload,
        codec="zlib-json-v1",
        uncompressed_bytes=raw_size,
        expected_sha256=digest,
    ) == (flow, cost)
    with pytest.raises(RuntimeError, match="corrupt|integrity|length"):
        _decode_snapshot_envelope(
            payload[:-1] + bytes([payload[-1] ^ 1]),
            codec="zlib-json-v1",
            uncompressed_bytes=raw_size,
            expected_sha256=digest,
        )
