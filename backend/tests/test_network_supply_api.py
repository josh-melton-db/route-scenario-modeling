from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.models import (
    NetworkOverviewContext,
    NetworkScenario,
    NetworkScenarioAssumptions,
)
from backend.services.network_overview import NetworkOverviewService, _local_network_rows
from backend.services.network_scenarios import (
    _effective_facility_rows,
    _restore_normal_facility_rows,
)
from backend.services.sql import AnalyticsDataMissingError, SqlService


def test_supply_and_handling_retention_allow_explicit_expansion() -> None:
    assumptions = NetworkScenarioAssumptions(
        facility_capacity_retained_pct={"DC": 125},
        facility_supply_retained_pct={"DC": 200},
    )
    assert assumptions.facility_capacity_retained_pct == {"DC": 125}
    assert assumptions.facility_supply_retained_pct == {"DC": 200}

    with pytest.raises(ValidationError, match="between 0 and 200"):
        NetworkScenarioAssumptions(facility_supply_retained_pct={"DC": 201})


def test_facility_aggregate_exposes_separate_supply_and_handling_metrics() -> None:
    rows = deepcopy(_local_network_rows())
    demand_plan = rows["demand_plan_versions"][0]
    capacity_plan = rows["capacity_plan_versions"][0]
    service_date = str(demand_plan["horizon_start"])
    dc_id = next(
        str(row["facility_id"])
        for row in rows["dim_facilities"]
        if row["facility_type"] == "distribution_center"
    )
    scenario = NetworkScenario(
        scenario_id="NSC_AGGREGATE",
        scenario_name="Aggregate",
        demand_plan_version_id=str(demand_plan["plan_version_id"]),
        capacity_plan_version_id=str(capacity_plan["plan_version_id"]),
        horizon_start=service_date,
        horizon_end=service_date,
        region_id="ALL",
        assumptions=NetworkScenarioAssumptions(
            facility_capacity_retained_pct={dc_id: 125},
            facility_supply_retained_pct={dc_id: 80},
        ),
        created_at="2026-10-06T00:00:00Z",
        updated_at="2026-10-06T00:00:00Z",
    )
    capacity_rows, supply_rows, _ = _effective_facility_rows(rows, scenario)
    rows["facility_capacity_daily"] = capacity_rows
    rows["facility_supply_daily"] = supply_rows
    rows["network_transfer_movements"] = [{
        "destination_dc_id": dc_id,
        "arrival_date": service_date,
        "assigned_units": 5_000,
    }]
    overview = NetworkOverviewService().build_overview(
        rows,
        context=NetworkOverviewContext(
            demand_plan_version_id=str(demand_plan["plan_version_id"]),
            capacity_plan_version_id=str(capacity_plan["plan_version_id"]),
            horizon_start=service_date,
            horizon_end=service_date,
            region_id="ALL",
            lane_type="LINEHAUL",
            metric="assigned_flow",
        ),
        facility_capacity_retained_pct={dc_id: 125},
        facility_supply_retained_pct={dc_id: 80},
    )
    dc = next(row for row in overview.facilities if row.facility_id == dc_id)

    assert dc.handling_capacity_units is not None
    assert dc.capacity_units == int(dc.handling_capacity_units * 1.25)
    assert dc.utilization_pct == dc.handling_utilization_pct
    assert dc.handling_retained_pct == 125
    assert dc.supply_retained_pct == 80
    assert dc.supply_units is not None
    assert dc.normal_supply_units is not None
    assert dc.supply_units == int(dc.normal_supply_units * 0.8)
    usable_supply = dc.supply_units + 5_000
    assert dc.supply_available_units == max(0, usable_supply - dc.assigned_units)
    assert dc.supply_utilization_pct == round(dc.assigned_units / usable_supply * 100, 1)
    assert dc.supply_source == "canonical_daily_supply"


def test_missing_supply_table_uses_labeled_legacy_fallback(monkeypatch) -> None:
    service = NetworkOverviewService()
    monkeypatch.setattr(service, "_run_sql_queries", lambda sql, statements: {})
    monkeypatch.setattr(
        SqlService,
        "query",
        lambda self, statement: (_ for _ in ()).throw(
            AnalyticsDataMissingError("TABLE_OR_VIEW_NOT_FOUND")
        ),
    )

    rows = service._load_sql_rows(
        demand_plan_version_id=None,
        capacity_plan_version_id=None,
        horizon_start=None,
        horizon_end=None,
    )
    assert rows["facility_supply_daily"] == []
    assert rows["facility_supply_provenance"] == [{
        "source": "legacy_handling_capacity_fallback",
        "reason": "facility_supply_daily_table_missing",
    }]


def test_supply_query_does_not_mask_unrelated_sql_failures(monkeypatch) -> None:
    service = NetworkOverviewService()
    monkeypatch.setattr(service, "_run_sql_queries", lambda sql, statements: {})
    monkeypatch.setattr(
        SqlService,
        "query",
        lambda self, statement: (_ for _ in ()).throw(
            HTTPException(status_code=502, detail="warehouse failed")
        ),
    )

    with pytest.raises(HTTPException, match="warehouse failed"):
        service._load_sql_rows(
            demand_plan_version_id=None,
            capacity_plan_version_id=None,
            horizon_start=None,
            horizon_end=None,
        )


@pytest.mark.parametrize("retained_pct", [0, 50, 150])
def test_effective_bounds_are_not_double_scaled_on_child_run(retained_pct: int) -> None:
    rows = deepcopy(_local_network_rows())
    demand_plan = rows["demand_plan_versions"][0]
    capacity_plan = rows["capacity_plan_versions"][0]
    dc_id = next(
        str(row["facility_id"])
        for row in rows["dim_facilities"]
        if row["facility_type"] == "distribution_center"
    )
    scenario = NetworkScenario(
        scenario_id="NSC_REPEAT",
        scenario_name="Repeat",
        demand_plan_version_id=str(demand_plan["plan_version_id"]),
        capacity_plan_version_id=str(capacity_plan["plan_version_id"]),
        horizon_start=str(demand_plan["horizon_start"]),
        horizon_end=str(demand_plan["horizon_start"]),
        region_id="ALL",
        assumptions=NetworkScenarioAssumptions(
            facility_capacity_retained_pct={dc_id: retained_pct},
            facility_supply_retained_pct={dc_id: retained_pct},
        ),
        created_at="2026-10-06T00:00:00Z",
        updated_at="2026-10-06T00:00:00Z",
    )
    first_capacity, first_supply, _ = _effective_facility_rows(rows, scenario)
    inherited = deepcopy(rows)
    inherited["facility_capacity_daily"] = deepcopy(first_capacity)
    inherited["facility_supply_daily"] = deepcopy(first_supply)

    _restore_normal_facility_rows(inherited)
    second_capacity, second_supply, _ = _effective_facility_rows(inherited, scenario)

    assert second_capacity == first_capacity
    assert second_supply == first_supply
    outside_horizon = [
        row for row in second_capacity
        if str(row["service_date"])[:10] != scenario.horizon_start
        and str(row["facility_id"]) == dc_id
    ]
    assert all("normal_capacity_units" not in row for row in outside_horizon)


def test_positive_stock_relief_can_be_applied_and_inherited(monkeypatch) -> None:
    from datetime import date, timedelta
    from backend.models import NetworkScenarioCreateRequest
    from backend.services import baseline_service as baseline_module
    from backend.services import network_scenarios as scenario_module
    from backend.services.network_overview import network_overview_service

    baseline = baseline_module.BaselineService()
    service = scenario_module.NetworkScenarioService(scenario_module.NetworkScenarioRepository())
    monkeypatch.setattr(baseline_module, "baseline_service", baseline)
    monkeypatch.setattr(scenario_module, "network_scenario_service", service)
    options = network_overview_service.get_options()
    start = options.default_horizon_start
    end = (date.fromisoformat(start) + timedelta(days=2)).isoformat()
    rows = deepcopy(_local_network_rows())
    disabled = [str(lane["lane_id"]) for lane in rows["dim_network_lanes"]
                if lane["lane_type"] == "LINEHAUL"
                and lane["destination_endpoint_id"] == "DPT_TOLA_DALLAS"
                and lane["origin_endpoint_id"] != "DC_TOLA_DALLAS"]
    payload = dict(
        scenario_name="Apply positive stock relief",
        demand_plan_version_id=options.default_demand_plan_version_id,
        capacity_plan_version_id=options.default_capacity_plan_version_id,
        horizon_start=start, horizon_end=end, region_id="REGION_TOLA",
    )
    scenario = service.create(NetworkScenarioCreateRequest(**payload, assumptions={
        "facility_supply_retained_pct": {"DC_TOLA_DALLAS": 0, "DC_TOLA_HOUSTON": 150},
        "facility_capacity_retained_pct": {"DC_TOLA_HOUSTON": 150},
        "disabled_lane_ids": disabled,
        "dc_transfer_requests": [{"transfer_id": "APPLY_STOCK", "origin_dc_id": "DC_TOLA_HOUSTON",
                                  "destination_dc_id": "DC_TOLA_DALLAS", "departure_date": start,
                                  "capacity_units": 5000}],
    }))
    solved = service.run(scenario.scenario_id)
    assert solved.result.transfer_movements[0].assigned_units > 0
    control = service.create(NetworkScenarioCreateRequest(**{
        **payload, "scenario_name": "Stock shortage KPI control",
        "assumptions": {**scenario.assumptions.model_dump(mode="json"), "dc_transfer_requests": []},
    }))
    control_result = service.run(control.scenario_id).result
    assigned_gain = solved.result.overview.kpis.assigned_units - control_result.overview.kpis.assigned_units
    unmet_reduction = control_result.overview.kpis.unmet_units - solved.result.overview.kpis.unmet_units
    assert 0 < assigned_gain == unmet_reduction <= solved.result.transfer_movements[0].assigned_units
    assert any(lane.mode == "AIR" and lane.assigned_units > 0 for lane in solved.result.overview.lanes)
    original_map = solved.result.overview.model_dump(mode="json")
    proposal = baseline.propose(solved.result.run_id)
    accepted = baseline.accept(proposal.proposal_id)
    assert accepted.active_run_id == solved.result.run_id
    active = baseline.get_plan_run(horizon_start=start, horizon_end=end).result
    facilities = {row.facility_id: row for row in active.overview.facilities}
    assert facilities["DC_TOLA_DALLAS"].supply_retained_pct == 0
    assert facilities["DC_TOLA_HOUSTON"].handling_retained_pct == 150
    map_overview = network_overview_service.get_overview(
        demand_plan_version_id=options.default_demand_plan_version_id,
        capacity_plan_version_id=options.default_capacity_plan_version_id,
        horizon_start=date.fromisoformat(start), horizon_end=date.fromisoformat(end),
        region_id="REGION_TOLA", lane_type="LINEHAUL", metric="assigned_flow",
    )
    map_facilities = {row.facility_id: row for row in map_overview.facilities}
    assert map_facilities["DC_TOLA_DALLAS"].supply_retained_pct == 0
    assert map_facilities["DC_TOLA_HOUSTON"].handling_retained_pct == 150
    assert service.get_run_snapshot(solved.result.run_id).result.overview.model_dump(mode="json") == original_map
    child = service.create(NetworkScenarioCreateRequest(**{**payload, "scenario_name": "Inherited stock relief"}))
    assert child.assumptions.facility_supply_retained_pct == scenario.assumptions.facility_supply_retained_pct
    assert child.assumptions.dc_transfer_requests == scenario.assumptions.dc_transfer_requests
