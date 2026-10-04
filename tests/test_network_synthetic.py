from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from route_opt.network_schemas import NetworkLane
from route_opt.network_synthetic import (
    NATIONAL_CAPACITY_PLAN_VERSION_ID,
    SOUTHEAST_CONSTRAINED_CAPACITY_PLAN_VERSION_ID,
    generate_national_network_dataset,
    generate_network_dataset,
    _resolve_road_reachable_coordinate,
    repair_generated_customer_reachability,
    validate_network_dataset,
)
from route_opt.land_mask import is_on_water, pull_to_land
from route_opt.matrix import haversine_miles
from route_opt.synthetic import generate_all, generate_depots


def _network():
    return generate_network_dataset(
        generate_depots(),
        seed=42,
        customers_per_depot=12,
    )


@pytest.fixture(scope="module")
def national_network():
    return generate_national_network_dataset(generate_depots(), seed=42)


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


@pytest.mark.parametrize(
    ("depot", "customer"),
    [
        ({"lat": 32.85, "lng": -96.85}, {"lat": 32.703639, "lng": -96.924945}),
        ({"lat": 29.4241, "lng": -98.4936}, {"lat": 29.673251, "lng": -98.361473}),
    ],
)
def test_known_dallas_sa_unreachable_points_get_bounded_deterministic_candidates(
    depot, customer,
) -> None:
    original_distance = haversine_miles(
        depot["lat"], depot["lng"], customer["lat"], customer["lng"]
    )

    def validator(anchor, point):
        remaining = haversine_miles(
            anchor["lat"], anchor["lng"], point["lat"], point["lng"]
        )
        return original_distance - remaining >= 2.0

    kwargs = dict(
        depot=depot, original_lat=customer["lat"], original_lng=customer["lng"],
        validator=validator,
        provenance={"costing": "truck", "coverage_id": "texas", "artifact_version": "v1"},
    )
    first = _resolve_road_reachable_coordinate(**kwargs)
    second = _resolve_road_reachable_coordinate(**kwargs)
    assert first == second
    assert first[2]["road_reachability_status"] == "validated"
    assert 2.0 <= first[2]["road_adjustment_miles"] <= 3.0
    assert first[2]["road_adjustment_miles"] <= 5.0
    assert first[2]["road_reachability_costing"] == "truck"
    assert first[2]["road_coverage_id"] == "texas"
    assert first[2]["road_artifact_version"] == "v1"


def test_no_validator_preserves_generated_coordinates_and_unresolved_retains_original() -> None:
    plain = generate_network_dataset(generate_depots(), seed=42, customers_per_depot=2)
    again = generate_network_dataset(generate_depots(), seed=42, customers_per_depot=2)
    assert plain["dim_network_customers"] == again["dim_network_customers"]
    depot = {"lat": 32.85, "lng": -96.85}
    original = {"lat": 32.703639, "lng": -96.924945}
    lat, lng, metadata = _resolve_road_reachable_coordinate(
        depot=depot, original_lat=original["lat"], original_lng=original["lng"],
        validator=lambda *_: False, provenance={"costing": "truck"},
    )
    assert (lat, lng) == (original["lat"], original["lng"])
    assert metadata["road_reachability_status"] == "unresolved"
    assert metadata["road_adjustment_miles"] == 0


def test_fresh_national_generation_adjusts_known_dallas_sa_regression_points() -> None:
    blocked = {(32.703639, -96.924945), (29.673251, -98.361473)}

    def validator(_depot, point):
        rounded = (round(float(point["lat"]), 6), round(float(point["lng"]), 6))
        return rounded not in blocked

    generated = generate_national_network_dataset(
        generate_depots(), seed=42,
        road_reachability_validator=validator,
        road_reachability_provenance={
            "costing": "truck", "coverage_id": "texas-dev",
            "artifact_version": "texas-v1",
        },
    )
    by_id = {row["customer_id"]: row for row in generated["dim_network_customers"]}
    for customer_id in ("NET-CUST-TOLA-0055", "NET-CUST-TOLA-0518"):
        row = by_id[customer_id]
        assert row["road_reachability_status"] == "validated"
        assert 0 < row["road_adjustment_miles"] <= 5.0
        assert (row["lat"], row["lng"]) != (
            row["road_original_lat"], row["road_original_lng"]
        )
        assert row["road_coverage_id"] == "texas-dev"
        assert row["road_artifact_version"] == "texas-v1"


def test_repair_path_is_detached_bounded_and_preserves_land_water_guardrails() -> None:
    dataset = generate_network_dataset(generate_depots(), seed=42, customers_per_depot=2)
    source = dataset["dim_network_customers"]
    original = [dict(row) for row in source]
    repaired = repair_generated_customer_reachability(
        source, dataset["dim_facilities"], validator=lambda *_: True,
        provenance={"costing": "truck", "coverage_id": "fixture", "artifact_version": "v1"},
    )
    assert source == original
    assert all(row["road_adjustment_miles"] <= 5.0 for row in repaired)
    assert all(not is_on_water(float(row["lat"]), float(row["lng"])) for row in repaired)
    assert is_on_water(43.5, -87.0)  # Lake Michigan remains water.
    assert is_on_water(30.0, -80.0)  # Atlantic remains water.
    inland = pull_to_land(43.5, -87.0, 41.85, -87.65)
    assert not is_on_water(*inland)


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

    assert len(demand_by_date) == 28
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


def test_national_demo_shape_and_alternate_paths(national_network) -> None:
    data = national_network
    assert len(data["dim_regions"]) == 7
    assert len(data["dim_facilities"]) == 56
    assert len(data["dim_markets"]) == 42
    assert len(data["dim_network_customers"]) == 4200
    assert len(data["demand_plan_daily"]) == 4200 * 28
    assert len(data["capacity_plan_versions"]) == 2
    assert validate_network_dataset(data) == []

    lanes = {row["lane_id"]: row for row in data["dim_network_lanes"]}
    alternate_id = "LNE_DC_SOUTHEAST_CHARLOTTE_TO_DPT_SE_NASHVILLE"
    assert alternate_id in lanes
    alternate_capacity = [
        row
        for row in data["lane_capacity_daily"]
        if row["lane_id"] == alternate_id
        and row["capacity_plan_version_id"] == NATIONAL_CAPACITY_PLAN_VERSION_ID
    ]
    assert alternate_capacity
    assert all(int(row["capacity_units"]) > 0 for row in alternate_capacity)

    assert {row["country_code"] for row in data["dim_facilities"]} == {
        "US",
        "MX",
        "CA",
    }
    monterrey_lane = "LNE_DC_MEXICO_MONTERREY_TO_DPT_TOLA_SAN_ANTONIO"
    domestic_lane = "LNE_DC_TOLA_HOUSTON_TO_DPT_TOLA_SAN_ANTONIO"
    assert monterrey_lane in lanes
    assert all(
        any(
            row["lane_id"] == lane_id
            and row["capacity_plan_version_id"] == NATIONAL_CAPACITY_PLAN_VERSION_ID
            and int(row["assigned_units"]) > 0
            for row in data["baseline_network_flow_daily"]
        )
        for lane_id in (monterrey_lane, domestic_lane)
    )


def test_constrained_southeast_plan_preserves_unmet_demand(national_network) -> None:
    data = national_network
    service_date = data["demand_plan_versions"][0]["horizon_start"]
    southeast_customers = {
        row["customer_id"]
        for row in data["dim_network_customers"]
        if row["region_id"] == "REGION_SOUTHEAST"
    }
    southeast_demand = sum(
        int(row["demand_units"])
        for row in data["demand_plan_daily"]
        if row["service_date"] == service_date
        and row["customer_id"] in southeast_customers
    )
    lanes = {row["lane_id"]: row for row in data["dim_network_lanes"]}
    constrained_delivery = sum(
        int(row["assigned_units"])
        for row in data["baseline_network_flow_daily"]
        if row["service_date"] == service_date
        and row["capacity_plan_version_id"]
        == SOUTHEAST_CONSTRAINED_CAPACITY_PLAN_VERSION_ID
        and lanes[row["lane_id"]]["lane_type"] == "DELIVERY"
        and lanes[row["lane_id"]]["origin_endpoint_id"].startswith("DPT_SE_")
    )
    normal_delivery = sum(
        int(row["assigned_units"])
        for row in data["baseline_network_flow_daily"]
        if row["service_date"] == service_date
        and row["capacity_plan_version_id"] == NATIONAL_CAPACITY_PLAN_VERSION_ID
        and lanes[row["lane_id"]]["lane_type"] == "DELIVERY"
        and lanes[row["lane_id"]]["origin_endpoint_id"].startswith("DPT_SE_")
    )
    assert normal_delivery == southeast_demand
    assert 0 < constrained_delivery < southeast_demand

    lane_capacity = {
        (
            row["capacity_plan_version_id"],
            row["service_date"],
            row["lane_id"],
        ): int(row["capacity_units"])
        for row in data["lane_capacity_daily"]
    }
    assert all(
        int(row["assigned_units"])
        <= lane_capacity[
            (
                row["capacity_plan_version_id"],
                row["service_date"],
                row["lane_id"],
            )
        ]
        for row in data["baseline_network_flow_daily"]
    )


@pytest.mark.parametrize("anchor", ["2026-02-03", "2027-11-19"])
def test_explicit_anchor_freezes_coherent_28_day_snapshot(anchor: str) -> None:
    code = """
import json
from route_opt.network_synthetic import national_dataset_cached
from route_opt.synthetic import generate_all
from backend.services.rates import list_rate_contract_details
from backend.services.stub_store import StubStore
d = national_dataset_cached()
local = generate_all()
rates = list_rate_contract_details(StubStore())
print(json.dumps({
  'version': d['demand_plan_versions'][0],
  'dates': sorted({r['service_date'] for r in d['demand_plan_daily']}),
  'route_dates': sorted({r['route_date'] for r in local['fact_delivery_orders']}),
  'rate_ranges': [[r.version.effective_start, r.version.effective_end] for r in rates],
}))
"""
    env = {**os.environ, "DEMO_DATE_ANCHOR": anchor, "PYTHONPATH": os.getcwd()}
    payload = json.loads(subprocess.check_output([sys.executable, "-c", code], env=env))
    dates = payload["dates"]
    assert len(dates) == 28
    assert dates[0] == anchor
    assert dates[-1] == (date.fromisoformat(anchor) + timedelta(days=27)).isoformat()
    assert payload["version"]["as_of_date"] == anchor
    assert anchor.replace("-", "") in payload["version"]["plan_version_id"]
    assert len(payload["route_dates"]) == 1
    assert dates[0] <= payload["route_dates"][0] <= dates[-1]
    assert payload["rate_ranges"]
    assert all(start <= dates[0] and end >= dates[-1] for start, end in payload["rate_ranges"])


def test_process_anchor_does_not_slide_when_clock_changes() -> None:
    code = """
from datetime import date
from route_opt import demo_dates
demo_dates._local_today = lambda: date(2026, 3, 1)
first = demo_dates.demo_date_anchor()
demo_dates._local_today = lambda: date(2026, 3, 2)
assert first == demo_dates.demo_date_anchor() == date(2026, 3, 1)
"""
    env = {key: value for key, value in os.environ.items() if key != "DEMO_DATE_ANCHOR"}
    env["PYTHONPATH"] = os.getcwd()
    subprocess.check_call([sys.executable, "-c", code], env=env)


def test_invalid_explicit_anchor_is_rejected() -> None:
    code = "from route_opt.demo_dates import demo_date_anchor; demo_date_anchor()"
    env = {**os.environ, "DEMO_DATE_ANCHOR": "09/30/2026", "PYTHONPATH": os.getcwd()}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "ISO date" in result.stderr
