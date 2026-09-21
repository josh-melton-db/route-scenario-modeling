from __future__ import annotations

from collections import defaultdict

import pytest
from pydantic import ValidationError

from route_opt.network_schemas import NetworkLane
from route_opt.network_synthetic import (
    generate_network_dataset,
    validate_network_dataset,
)
from route_opt.synthetic import generate_all, generate_depots


def _network():
    return generate_network_dataset(
        generate_depots(),
        seed=42,
        customers_per_depot=12,
    )


def test_canonical_network_shape_and_existing_depot_mapping() -> None:
    data = _network()
    facilities = {row["facility_id"]: row for row in data["dim_facilities"]}
    existing = {row["depot_id"]: row for row in generate_depots()}

    assert len(data["dim_regions"]) == 1
    assert len(
        [
            row
            for row in facilities.values()
            if row["facility_type"] == "distribution_center"
        ]
    ) == 2
    assert len([row for row in facilities.values() if row["facility_type"] == "depot"]) == 6
    assert len(data["dim_markets"]) == 6
    assert len(data["dim_network_customers"]) == 72

    for depot_id, depot in existing.items():
        facility = facilities[depot_id]
        assert facility["facility_name"] == depot["depot_name"]
        assert facility["lat"] == depot["lat"]
        assert facility["lng"] == depot["lng"]
        assert facility["parent_facility_id"]


def test_every_lane_endpoint_exists_and_schema_rejects_wrong_lane_grain() -> None:
    data = _network()
    assert validate_network_dataset(data) == []

    with pytest.raises(ValidationError):
        NetworkLane(
            lane_id="BAD",
            lane_name="Invalid delivery lane",
            lane_type="DELIVERY",
            origin_endpoint_id="DPT_NORTH",
            origin_endpoint_type="facility",
            destination_endpoint_id="MKT_NORTH",
            destination_endpoint_type="market",
            distance_miles=10,
            transit_minutes=20,
        )


def test_baseline_flow_reconciles_across_all_three_lane_grains() -> None:
    data = _network()
    demand_by_date: defaultdict[str, int] = defaultdict(int)
    flow_by_date_and_type: defaultdict[tuple[str, str], int] = defaultdict(int)

    for row in data["demand_plan_daily"]:
        demand_by_date[str(row["service_date"])] += int(row["demand_units"])
    for row in data["baseline_network_flow_daily"]:
        flow_by_date_and_type[(str(row["service_date"]), str(row["lane_type"]))] += int(
            row["assigned_units"]
        )

    assert len(demand_by_date) == 7
    for service_date, total_demand in demand_by_date.items():
        assert flow_by_date_and_type[(service_date, "LINEHAUL")] == total_demand
        assert flow_by_date_and_type[(service_date, "MARKET")] == total_demand
        assert flow_by_date_and_type[(service_date, "DELIVERY")] == total_demand


def test_baseline_flow_respects_supplied_lane_and_facility_capacity() -> None:
    data = _network()
    lane_capacity = {
        (str(row["service_date"]), str(row["lane_id"])): int(row["capacity_units"])
        for row in data["lane_capacity_daily"]
    }
    for row in data["baseline_network_flow_daily"]:
        key = (str(row["service_date"]), str(row["lane_id"]))
        assert int(row["assigned_units"]) <= lane_capacity[key]

    assert validate_network_dataset(data) == []


def test_network_generation_is_deterministic_and_changes_with_seed() -> None:
    first = _network()
    second = _network()
    changed = generate_network_dataset(
        generate_depots(),
        seed=43,
        customers_per_depot=12,
    )

    assert first == second
    assert first["demand_plan_daily"] != changed["demand_plan_daily"]
    assert first["dim_network_customers"] != changed["dim_network_customers"]


def test_existing_generate_all_exposes_canonical_network_tables() -> None:
    data = generate_all(seed=42, customer_count=250)

    assert "dim_facilities" in data
    assert "demand_plan_daily" in data
    assert "facility_capacity_daily" in data
    assert validate_network_dataset(data) == []
