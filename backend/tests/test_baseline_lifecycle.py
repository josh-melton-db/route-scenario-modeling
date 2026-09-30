from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.services.baseline_repository import (
    BaselineProposalRecord,
    BaselineRepository,
    BaselineRevision,
)
from backend.services.baseline_service import BaselineService


def _rows() -> dict[str, list[dict[str, object]]]:
    return {
        "demand_plan_versions": [{"plan_version_id": "D1"}],
        "capacity_plan_versions": [{"plan_version_id": "C1"}],
        "dim_facilities": [
            {"facility_id": "DC", "region_id": "R0"},
            {"facility_id": "A", "region_id": "R1"},
            {"facility_id": "B", "region_id": "R2"},
        ],
        "dim_network_lanes": [
            {"lane_id": "LA", "lane_type": "LINEHAUL", "origin_endpoint_id": "DC", "destination_endpoint_id": "A"},
            {"lane_id": "LB", "lane_type": "LINEHAUL", "origin_endpoint_id": "DC", "destination_endpoint_id": "B"},
        ],
        "demand_plan_daily": [
            {"demand_plan_version_id": "D1", "service_date": "2026-01-01", "region_id": "R1", "distribution_center_id": "DC", "depot_id": "A", "market_id": "M", "customer_id": "U1", "demand_units": 5},
            {"demand_plan_version_id": "D1", "service_date": "2026-01-01", "region_id": "R1", "distribution_center_id": "DC", "depot_id": "A", "market_id": "M", "customer_id": "U2", "demand_units": 5},
            {"demand_plan_version_id": "D1", "service_date": "2026-01-01", "region_id": "R2", "distribution_center_id": "DC", "depot_id": "B", "market_id": "N", "customer_id": "U3", "demand_units": 8},
        ],
        "facility_capacity_daily": [
            {"capacity_plan_version_id": capacity, "service_date": "2026-01-01", "facility_id": facility, "capacity_units": 40}
            for capacity in ("C1", "C2") for facility in ("DC", "A", "B")
        ],
        "lane_capacity_daily": [
            {"capacity_plan_version_id": "C1", "service_date": "2026-01-01", "lane_id": "LA", "capacity_units": 20},
            {"capacity_plan_version_id": "C1", "service_date": "2026-01-01", "lane_id": "LB", "capacity_units": 20},
            {"capacity_plan_version_id": "C2", "service_date": "2026-01-01", "lane_id": "LA", "capacity_units": 20},
        ],
        "baseline_network_flow_daily": [
            {"demand_plan_version_id": "D1", "capacity_plan_version_id": "C1", "service_date": "2026-01-01", "lane_id": "LA", "lane_type": "LINEHAUL", "assigned_units": 10},
            {"demand_plan_version_id": "D1", "capacity_plan_version_id": "C1", "service_date": "2026-01-01", "lane_id": "LB", "lane_type": "LINEHAUL", "assigned_units": 8},
            {"demand_plan_version_id": "D1", "capacity_plan_version_id": "C2", "service_date": "2026-01-01", "lane_id": "LA", "lane_type": "LINEHAUL", "assigned_units": 7},
            {"demand_plan_version_id": "D1", "capacity_plan_version_id": "C2", "service_date": "2026-01-01", "lane_id": "LB", "lane_type": "LINEHAUL", "assigned_units": 0},
        ],
    }


def test_fully_assigned_network_without_route_plans_is_not_route_ready() -> None:
    coverage = BaselineService._coverage(_rows())
    assert coverage.ready is False
    assert coverage.covered_depots == 0
    assert coverage.expected_depots == 2
    assert coverage.expected_dates == 1


def test_regional_overlay_clears_old_positive_and_preserves_versions_and_shared_dc() -> None:
    source = _rows()
    run_rows = _rows()
    run_rows["demand_plan_daily"] = [
        {"demand_plan_version_id": "D1", "service_date": "2026-01-01", "region_id": "R1", "distribution_center_id": "DC", "depot_id": "A", "market_id": "M", "customer_id": "U2", "demand_units": 6},
    ]
    snapshot = SimpleNamespace(
        scenario=SimpleNamespace(horizon_start="2026-01-01", horizon_end="2026-01-01", region_id="R1", demand_plan_version_id="D1", capacity_plan_version_id="C1"),
        network_rows=run_rows,
        flow_rows=[{"demand_plan_version_id": "D1", "capacity_plan_version_id": "C1", "service_date": "2026-01-01", "lane_id": "LA", "lane_type": "LINEHAUL", "assigned_units": 0}],
        cost_rows=[],
    )
    merged = BaselineService._merge_rows(source, snapshot)
    flows = {(row["capacity_plan_version_id"], row["lane_id"]): row["assigned_units"] for row in merged["baseline_network_flow_daily"]}
    assert flows[("C1", "LA")] == 0
    assert flows[("C1", "LB")] == 8
    assert flows[("C2", "LA")] == 7
    r1_demand = [row for row in merged["demand_plan_daily"] if row["region_id"] == "R1"]
    assert [(row["customer_id"], row["demand_units"]) for row in r1_demand] == [("U2", 6)]


def test_acceptance_is_allowed_when_frozen_route_coverage_is_incomplete() -> None:
    repository = BaselineRepository()
    rows = _rows()
    rows["baseline_revision_metadata"] = [{
        "route_coverage": {"ready": False, "covered_dates": 0, "expected_dates": 1,
                           "covered_depots": 0, "expected_depots": 2, "message": "0 of 2 frozen."},
        "selected_child_result_ids": [],
    }]
    repository.seed(BaselineRevision("original", None, None, None, rows))
    proposed = BaselineRevision("revision", "original", "run", None, rows)
    repository.save_proposal(BaselineProposalRecord("proposal", "run", "original", proposed))
    service = BaselineService(repository)
    service._ensure_seeded = lambda: None  # type: ignore[method-assign]
    state = service.accept("proposal")
    assert state.active_revision_id == "revision"
    assert state.route_coverage.ready is False


def test_proposal_rejects_historical_and_legacy_sources_instead_of_rebasing(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.network_scenarios import network_scenario_service

    repository = BaselineRepository()
    rows = _rows()
    repository.seed(BaselineRevision("original", None, None, None, rows))
    active = BaselineRevision("active", "original", "prior-run", "now", rows)
    repository.save_proposal(BaselineProposalRecord("prior", "prior-run", "original", active))
    repository.accept("prior", "now")
    service = BaselineService(repository)
    service._ensure_seeded = lambda: None  # type: ignore[method-assign]
    monkeypatch.setattr(service, "_has_pending_demand", lambda _run_id: False)

    for scenario in (
        SimpleNamespace(source_baseline_revision_id="original"),
        SimpleNamespace(),
    ):
        monkeypatch.setattr(
            network_scenario_service,
            "get_run_snapshot",
            lambda _run_id, scenario=scenario: SimpleNamespace(scenario=scenario),
        )
        with pytest.raises(HTTPException) as error:
            service.propose("historical-run")
        assert error.value.status_code == 409
        assert "historical baseline" in str(error.value.detail)


def test_real_regional_national_snapshot_merges_and_validates() -> None:
    from backend.models import NetworkScenarioCreateRequest
    from backend.services.network_overview import network_overview_service
    from backend.services.network_scenarios import NetworkScenarioRepository, NetworkScenarioService

    options = network_overview_service.get_options()
    day = options.default_horizon_start
    service = NetworkScenarioService(NetworkScenarioRepository())
    scenario = service.create(NetworkScenarioCreateRequest(
        scenario_name="Regional baseline integration",
        demand_plan_version_id=options.default_demand_plan_version_id,
        capacity_plan_version_id=options.default_capacity_plan_version_id,
        horizon_start=day,
        horizon_end=day,
        region_id=next(row.region_id for row in options.regions if row.region_id != "ALL"),
    ))
    solved = service.run(scenario.scenario_id)
    snapshot = service.get_run_snapshot(solved.result.run_id or "")
    source = BaselineService().get_revision(scenario.source_baseline_revision_id).rows
    merged = BaselineService._merge_rows(source, snapshot)

    BaselineService._validate(merged)

    delivery = next(row for row in merged["baseline_network_flow_daily"] if row["lane_type"] == "DELIVERY")
    original_units = delivery["assigned_units"]
    delivery["assigned_units"] = -1
    with pytest.raises(HTTPException, match="negative"):
        BaselineService._validate(merged)
    delivery["assigned_units"] = int(original_units) + 1
    with pytest.raises(HTTPException, match="conserve flow|customer demand"):
        BaselineService._validate(merged)
    delivery["assigned_units"] = original_units
    delivery["lane_id"] = "UNKNOWN_LANE"
    with pytest.raises(HTTPException, match="unknown lane"):
        BaselineService._validate(merged)


def test_frozen_route_coverage_is_not_ready_with_unserved_results(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.services.depot_plan_repository as depot_repository_module
    from backend.services.depot_plan_repository import DepotPlanRepository

    repository = DepotPlanRepository()
    repository._records["plan"] = {
        "plan_set_id": "plan", "parent_run_id": "run", "depot_id": "A",
        "days": {"2026-01-01": {"default_result_id": "result", "selected_result_ids": {},
                                  "results": {"result": {"unserved_cases": 1}}}},
    }
    monkeypatch.setattr(depot_repository_module, "depot_plan_repository", repository)
    snapshot = SimpleNamespace(
        scenario=SimpleNamespace(horizon_start="2026-01-01", horizon_end="2026-01-01"),
        network_rows=_rows(),
        flow_rows=[{"service_date": "2026-01-01", "lane_id": "LA"}],
    )
    metadata = BaselineService._freeze_route_coverage("run", snapshot)
    assert metadata["route_coverage"]["ready"] is False
    assert "unserved" in metadata["route_coverage"]["message"].lower()
