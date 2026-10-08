from __future__ import annotations

from copy import deepcopy

from backend.models import NetworkTariffRule
from backend.services.network_scenarios import NetworkScenarioService
from route_opt.network_flow import materialize_express_air_transfers, solve_fixed_capacity_network


DAYS = ["2026-10-01", "2026-10-02", "2026-10-03"]


def test_unused_air_request_preserves_regional_unmet_demand() -> None:
    rows = _rows({DAYS[0]: 5, DAYS[1]: 5})
    rows["dim_facilities"].append({
        "facility_id": "DC_OTHER", "facility_type": "distribution_center",
        "region_id": "OTHER", "country_code": "US", "lat": 41, "lng": -82,
    })
    rows["dim_network_lanes"].append({
        "lane_id": "OTHER_LH", "lane_type": "LINEHAUL",
        "origin_endpoint_id": "DC_OTHER", "destination_endpoint_id": "DPT",
        "distance_miles": 1, "planning_cost_per_case": 0.1,
    })
    for day in DAYS:
        rows["facility_capacity_daily"].append({
            "capacity_plan_version_id": "P", "service_date": day,
            "facility_id": "DC_OTHER", "capacity_units": 100,
        })
        rows["lane_capacity_daily"].append({
            "capacity_plan_version_id": "P", "service_date": day,
            "lane_id": "OTHER_LH", "capacity_units": 100,
        })
    kwargs = dict(demand_plan_version_id="D", capacity_plan_version_id="P",
                  horizon_start=DAYS[0], horizon_end=DAYS[1], region_id="R")
    control = solve_fixed_capacity_network(rows, **kwargs)
    transfer = solve_fixed_capacity_network(rows, **kwargs, dc_transfer_requests=[{
        "transfer_id": "UNUSED", "origin_dc_id": "DC_DONOR",
        "destination_dc_id": "DC_SHORT", "departure_date": DAYS[0],
        "capacity_units": 5,
    }])
    assert transfer["transfer_movements"][0]["assigned_units"] == 0
    assert transfer["unmet_rows"] == control["unmet_rows"]


def _rows(demand_by_day: dict[str, int]) -> dict[str, list[dict[str, object]]]:
    facilities = [
        {"facility_id": "DC_DONOR", "facility_type": "distribution_center", "region_id": "R", "country_code": "CA", "lat": 43.0, "lng": -79.0},
        {"facility_id": "DC_SHORT", "facility_type": "distribution_center", "region_id": "R", "country_code": "US", "lat": 42.0, "lng": -83.0},
        {"facility_id": "DPT", "facility_type": "depot", "region_id": "R", "country_code": "US", "lat": 42.1, "lng": -83.1},
    ]
    lanes = [
        {"lane_id": "LH", "lane_type": "LINEHAUL", "origin_endpoint_id": "DC_SHORT", "destination_endpoint_id": "DPT", "distance_miles": 10, "planning_cost_per_case": 1},
        {"lane_id": "MKT", "lane_type": "MARKET", "origin_endpoint_id": "DPT", "destination_endpoint_id": "M", "distance_miles": 1},
        {"lane_id": "DEL", "lane_type": "DELIVERY", "origin_endpoint_id": "DPT", "destination_endpoint_id": "C", "distance_miles": 1},
    ]
    return {
        "dim_facilities": facilities,
        "dim_network_lanes": lanes,
        "dim_network_customers": [{"customer_id": "C", "region_id": "R", "lat": 42.1, "lng": -83.1}],
        "demand_plan_daily": [
            {"demand_plan_version_id": "D", "service_date": day, "distribution_center_id": "DC_SHORT", "depot_id": "DPT", "customer_id": "C", "demand_units": units}
            for day, units in demand_by_day.items()
        ],
        "facility_capacity_daily": [
            {"capacity_plan_version_id": "P", "service_date": day, "facility_id": facility_id, "capacity_units": capacity}
            for day in DAYS
            for facility_id, capacity in (("DC_DONOR", 10), ("DC_SHORT", 0), ("DPT", 10))
        ],
        "lane_capacity_daily": [
            {"capacity_plan_version_id": "P", "service_date": day, "lane_id": lane["lane_id"], "capacity_units": 10}
            for day in DAYS for lane in lanes
        ],
        "baseline_network_flow_daily": [
            {"demand_plan_version_id": "D", "capacity_plan_version_id": "P", "service_date": day, "lane_id": lane["lane_id"], "lane_type": lane["lane_type"], "assigned_units": 0}
            for day in DAYS for lane in lanes
        ],
    }


def test_retained_percentage_scales_normal_daily_capacity() -> None:
    rows = _rows({DAYS[0]: 10})
    for row in rows["facility_capacity_daily"]:
        if row["facility_id"] == "DC_SHORT":
            row["capacity_units"] = 10

    result = solve_fixed_capacity_network(
        rows, demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start=DAYS[0], horizon_end=DAYS[0], region_id="ALL",
        facility_capacity_retained_pct={"DC_SHORT": 50},
    )

    assert sum(row["assigned_units"] for row in result["allocation_rows"]) == 5
    assert result["unmet_rows"][0]["unmet_units"] == 5


def test_supply_and_handling_percentages_scale_independently() -> None:
    rows = _rows({DAYS[0]: 10})
    rows["facility_supply_daily"] = [{
        "capacity_plan_version_id": "P", "service_date": DAYS[0],
        "facility_id": "DC_SHORT", "supply_units": 8,
    }]
    for row in rows["facility_capacity_daily"]:
        if row["facility_id"] == "DC_SHORT":
            row["capacity_units"] = 10

    result = solve_fixed_capacity_network(
        rows, demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start=DAYS[0], horizon_end=DAYS[0], region_id="ALL",
        facility_capacity_retained_pct={"DC_SHORT": 200},
        facility_supply_retained_pct={"DC_SHORT": 50},
    )

    assert sum(row["assigned_units"] for row in result["allocation_rows"]) == 4
    assert result["unmet_rows"][0]["unmet_units"] == 6


def test_air_transfer_relieves_supply_shortage_after_arrival() -> None:
    rows = _rows({DAYS[2]: 5})
    rows["facility_supply_daily"] = [
        {"capacity_plan_version_id": "P", "service_date": day,
         "facility_id": facility_id, "supply_units": supply}
        for day in DAYS
        for facility_id, supply in (("DC_DONOR", 5), ("DC_SHORT", 0))
    ]
    for row in rows["facility_capacity_daily"]:
        if row["facility_id"] == "DC_SHORT":
            row["capacity_units"] = 5

    result = solve_fixed_capacity_network(
        rows, demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start=DAYS[0], horizon_end=DAYS[2], region_id="ALL",
        dc_transfer_requests=[{
            "transfer_id": "RELIEF", "origin_dc_id": "DC_DONOR",
            "destination_dc_id": "DC_SHORT", "departure_date": DAYS[0],
            "capacity_units": 5,
        }],
    )

    assert result["transfer_movements"][0]["assigned_units"] == 5
    assert next(row for row in result["unmet_rows"] if row["service_date"] == DAYS[2])["unmet_units"] == 0


def test_air_transfer_conserves_donor_supply_and_waits_for_arrival() -> None:
    rows = _rows({DAYS[0]: 5, DAYS[2]: 5})
    rows["facility_supply_daily"] = [
        {"capacity_plan_version_id": "P", "service_date": day,
         "facility_id": facility_id, "supply_units": supply}
        for day in DAYS
        for facility_id, supply in (("DC_DONOR", 3 if day == DAYS[0] else 0), ("DC_SHORT", 0))
    ]
    for row in rows["facility_capacity_daily"]:
        if row["facility_id"] == "DC_SHORT":
            row["capacity_units"] = 5

    result = solve_fixed_capacity_network(
        rows, demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start=DAYS[0], horizon_end=DAYS[2], region_id="ALL",
        dc_transfer_requests=[{
            "transfer_id": "LIMITED", "origin_dc_id": "DC_DONOR",
            "destination_dc_id": "DC_SHORT", "departure_date": DAYS[0],
            "capacity_units": 5,
        }],
    )

    assert result["transfer_movements"][0]["assigned_units"] == 3
    assert next(row for row in result["unmet_rows"] if row["service_date"] == DAYS[0])["unmet_units"] == 5
    assert next(row for row in result["unmet_rows"] if row["service_date"] == DAYS[2])["unmet_units"] == 2


def test_zero_handling_blocks_air_even_when_destination_has_supply() -> None:
    rows = _rows({DAYS[2]: 5})
    rows["facility_supply_daily"] = [{
        "capacity_plan_version_id": "P", "service_date": DAYS[2],
        "facility_id": "DC_SHORT", "supply_units": 5,
    }]
    result = solve_fixed_capacity_network(
        rows, demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start=DAYS[0], horizon_end=DAYS[2], region_id="ALL",
        dc_transfer_requests=[{
            "transfer_id": "BLOCKED", "origin_dc_id": "DC_DONOR",
            "destination_dc_id": "DC_SHORT", "departure_date": DAYS[0],
            "capacity_units": 5,
        }],
    )

    assert result["transfer_movements"][0]["assigned_units"] == 0
    assert next(row for row in result["unmet_rows"] if row["service_date"] == DAYS[2])["unmet_units"] == 5


def test_direct_donor_linehaul_relief_bypasses_constrained_dc() -> None:
    rows = _rows({DAYS[0]: 5})
    rows["dim_network_lanes"].append({
        "lane_id": "DONOR_DIRECT", "lane_type": "LINEHAUL",
        "origin_endpoint_id": "DC_DONOR", "destination_endpoint_id": "DPT",
        "distance_miles": 20, "planning_cost_per_case": 2,
    })
    rows["lane_capacity_daily"].append({
        "capacity_plan_version_id": "P", "service_date": DAYS[0],
        "lane_id": "DONOR_DIRECT", "capacity_units": 5,
    })
    rows["baseline_network_flow_daily"].append({
        "demand_plan_version_id": "D", "capacity_plan_version_id": "P",
        "service_date": DAYS[0], "lane_id": "DONOR_DIRECT",
        "lane_type": "LINEHAUL", "assigned_units": 0,
    })

    result = solve_fixed_capacity_network(
        rows, demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start=DAYS[0], horizon_end=DAYS[0], region_id="ALL",
    )

    direct = next(row for row in result["allocation_rows"] if row["lane_id"] == "DONOR_DIRECT")
    assert direct["assigned_units"] == 5
    assert result["unmet_rows"][0]["unmet_units"] == 0


def test_air_transfer_cannot_bypass_destination_handling_shortage() -> None:
    rows = _rows({DAYS[0]: 5, DAYS[2]: 5})
    for row in rows["facility_capacity_daily"]:
        if row["facility_id"] == "DC_SHORT":
            row["capacity_units"] = 1
    original = deepcopy(rows)
    result = solve_fixed_capacity_network(
        rows, demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start=DAYS[0], horizon_end=DAYS[2], region_id="ALL",
        dc_transfer_requests=[{
            "transfer_id": "RELIEF", "origin_dc_id": "DC_DONOR",
            "destination_dc_id": "DC_SHORT", "departure_date": DAYS[0],
            "capacity_units": 4,
        }],
        tariff_per_case_by_date_lane={(DAYS[0], "XFER_RELIEF"): 3},
    )

    movement = result["transfer_movements"][0]
    assert movement["departure_date"] == DAYS[0]
    assert movement["arrival_date"] == DAYS[1]
    assert movement["assigned_units"] == 0
    assert movement["assigned_units"] <= movement["capacity_units"]
    allocation = next(row for row in result["allocation_rows"] if row["lane_id"] == "XFER_RELIEF")
    assert allocation == {
        "service_date": DAYS[0], "lane_id": "XFER_RELIEF",
        "depot_id": "DC_SHORT", "assigned_units": 0, "capacity_units": 4,
        "transfer_id": "RELIEF", "origin_dc_id": "DC_DONOR",
        "destination_dc_id": "DC_SHORT", "mode": "AIR",
        "departure_date": DAYS[0], "arrival_date": DAYS[1],
    }
    assert next(row for row in result["unmet_rows"] if row["service_date"] == DAYS[0])["unmet_units"] == 4
    assert next(row for row in result["unmet_rows"] if row["service_date"] == DAYS[2])["unmet_units"] == 4
    direct_from_destination = sum(
        row["assigned_units"]
        for row in result["allocation_rows"]
        if row["service_date"] == DAYS[2] and row["lane_id"] == "LH"
    )
    assert direct_from_destination == 1
    assert direct_from_destination <= 1  # Canonical daily DC handling capacity.
    lane = next(row for row in result["network_lanes"] if row["lane_id"] == "XFER_RELIEF")
    assert lane["mode"] == "AIR"
    assert lane["eligibility_source"] == "scenario_express_air_transfer_v1"
    assert lane["synthetic_provenance"]["distance_basis"] == "great_circle_miles"
    assert rows == original


def test_transfer_arriving_beyond_horizon_cannot_serve_shortage() -> None:
    result = solve_fixed_capacity_network(
        _rows({DAYS[0]: 5}), demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start=DAYS[0], horizon_end=DAYS[0], region_id="ALL",
        dc_transfer_requests=[{
            "transfer_id": "TOO_LATE", "origin_dc_id": "DC_DONOR",
            "destination_dc_id": "DC_SHORT", "departure_date": DAYS[0],
            "capacity_units": 5,
        }],
    )

    assert result["transfer_movements"][0]["assigned_units"] == 0
    assert result["unmet_rows"][0]["unmet_units"] == 5


def test_zero_retained_capacity_closes_transfer_destination() -> None:
    rows = _rows({DAYS[2]: 5})
    for row in rows["facility_capacity_daily"]:
        if row["facility_id"] == "DC_SHORT":
            row["capacity_units"] = 10
    result = solve_fixed_capacity_network(
        rows, demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start=DAYS[0], horizon_end=DAYS[2], region_id="ALL",
        facility_capacity_retained_pct={"DC_SHORT": 0},
        dc_transfer_requests=[{
            "transfer_id": "CLOSED", "origin_dc_id": "DC_DONOR",
            "destination_dc_id": "DC_SHORT", "departure_date": DAYS[0],
            "capacity_units": 5,
        }],
    )

    assert result["transfer_movements"][0]["assigned_units"] == 0
    assert next(row for row in result["unmet_rows"] if row["service_date"] == DAYS[2])["unmet_units"] == 5


def test_cross_border_transfer_uses_normal_dated_tariff_resolution() -> None:
    rows = _rows({DAYS[2]: 5})
    materialized = materialize_express_air_transfers(
        rows,
        [{"transfer_id": "TARIFF", "origin_dc_id": "DC_DONOR", "destination_dc_id": "DC_SHORT", "departure_date": DAYS[0], "capacity_units": 5}],
        capacity_plan_version_id="P",
    )
    rows["dim_network_lanes"] = materialized["network_lanes"]
    resolved = NetworkScenarioService._resolve_tariffs(
        rows,  # type: ignore[arg-type]
        [NetworkTariffRule(rule_id="CA_US", origin_country="CA", destination_country="US", effective_start=DAYS[0], effective_end=DAYS[0], amount_per_case=3)],
        DAYS[0], DAYS[2],
    )

    assert resolved == {(DAYS[0], "XFER_TARIFF"): (3.0, "CA_US")}


def test_linehaul_bypass_serves_depot_without_using_constrained_dc_handling():
    rows = _rows({DAYS[1]: 5})
    rows["dim_facilities"].append({"facility_id": "UNUSED", "facility_type": "depot", "region_id": "R", "parent_facility_id": "DC_SHORT", "lat": 40, "lng": -83})
    next(row for row in rows["dim_facilities"] if row["facility_id"] == "DPT")["parent_facility_id"] = "DC_SHORT"
    request = {"transfer_id": "GROUND", "origin_dc_id": "DC_DONOR", "destination_dc_id": "DC_SHORT", "destination_depot_id": "DPT", "mode": "LINEHAUL", "departure_date": DAYS[0], "capacity_units": 5}
    result = solve_fixed_capacity_network(rows, demand_plan_version_id="D", capacity_plan_version_id="P", horizon_start=DAYS[0], horizon_end=DAYS[2], region_id="ALL", dc_transfer_requests=[request])
    movement = result["transfer_movements"][0]
    assert movement["mode"] == "LINEHAUL"
    assert movement["assigned_units"] == 5
    assert movement["arrival_date"] == DAYS[1]
    assert next(row for row in result["unmet_rows"] if row["service_date"] == DAYS[1] and row["depot_id"] == "DPT")["unmet_units"] == 0
    for row in rows["facility_capacity_daily"]:
        if row["facility_id"] == "DPT": row["capacity_units"] = 2
    capped = solve_fixed_capacity_network(rows, demand_plan_version_id="D", capacity_plan_version_id="P", horizon_start=DAYS[0], horizon_end=DAYS[2], region_id="ALL", dc_transfer_requests=[request])
    assert capped["transfer_movements"][0]["assigned_units"] == 2
    assert next(row for row in capped["unmet_rows"] if row["service_date"] == DAYS[1] and row["depot_id"] == "DPT")["unmet_units"] == 3


def test_linehaul_bypass_cannot_create_donor_stock():
    rows = _rows({DAYS[1]: 5})
    next(row for row in rows["dim_facilities"] if row["facility_id"] == "DPT")["parent_facility_id"] = "DC_SHORT"
    rows["facility_supply_daily"] = [{"capacity_plan_version_id": "P", "service_date": DAYS[0], "facility_id": "DC_DONOR", "supply_units": 2}]
    result = solve_fixed_capacity_network(rows, demand_plan_version_id="D", capacity_plan_version_id="P", horizon_start=DAYS[0], horizon_end=DAYS[2], region_id="ALL", dc_transfer_requests=[{"transfer_id": "LIMITED", "origin_dc_id": "DC_DONOR", "destination_dc_id": "DC_SHORT", "destination_depot_id": "DPT", "mode": "LINEHAUL", "departure_date": DAYS[0], "capacity_units": 5}])
    assert result["transfer_movements"][0]["assigned_units"] == 2
    assert next(row for row in result["unmet_rows"] if row["service_date"] == DAYS[1] and row["depot_id"] == "DPT")["unmet_units"] == 3
