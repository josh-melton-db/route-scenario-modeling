from copy import deepcopy

import pytest

from route_opt.network_flow import solve_fixed_capacity_network


def _two_day_rows():
    days = ["2026-09-30", "2026-10-01"]
    facilities = [
        {"facility_id": name, "facility_type": role, "region_id": "R", "lat": 30, "lng": -97}
        for name, role in [("DC1", "distribution_center"), ("DC2", "distribution_center"), ("DPT", "depot")]
    ]
    lanes = [
        {"lane_id": name, "lane_type": kind, "origin_endpoint_id": origin,
         "destination_endpoint_id": destination, "distance_miles": 10, "planning_cost_per_case": 1}
        for name, kind, origin, destination in [
            ("LH1", "LINEHAUL", "DC1", "DPT"), ("LH2", "LINEHAUL", "DC2", "DPT"),
            ("M", "MARKET", "DPT", "MKT"), ("DEL", "DELIVERY", "DPT", "CUSTOMER"),
        ]
    ]
    return {
        "dim_facilities": facilities,
        "dim_network_lanes": lanes,
        "dim_network_customers": [{"customer_id": "CUSTOMER", "depot_id": "DPT", "region_id": "R", "lat": 30, "lng": -97}],
        "demand_plan_daily": [{"demand_plan_version_id": "D", "service_date": day,
            "distribution_center_id": "DC1", "depot_id": "DPT", "customer_id": "CUSTOMER", "demand_units": 5} for day in days],
        "facility_capacity_daily": [{"capacity_plan_version_id": "P", "service_date": day,
            "facility_id": row["facility_id"], "capacity_units": 10} for day in days for row in facilities],
        "lane_capacity_daily": [{"capacity_plan_version_id": "P", "service_date": day,
            "lane_id": row["lane_id"], "capacity_units": 10} for day in days for row in lanes],
        "baseline_network_flow_daily": [{"demand_plan_version_id": "D", "capacity_plan_version_id": "P",
            "service_date": day, "lane_id": row["lane_id"], "lane_type": row["lane_type"],
            "assigned_units": 0 if row["lane_id"] == "LH2" else 5} for day in days for row in lanes],
    }


@pytest.mark.parametrize("assignment_overlay", [False, True])
def test_dated_objective_switches_sources_across_rate_boundary(assignment_overlay):
    rows = _two_day_rows()
    original = deepcopy(rows)
    if assignment_overlay:
        rows["network_customer_assignments_daily"] = [
            {"demand_plan_version_id": "D", "capacity_plan_version_id": "P", "service_date": day,
             "customer_id": "CUSTOMER", "depot_id": "DPT", "required_units": 5,
             "assigned_units": 5, "unmet_units": 0, "source_depot_id": "DPT"}
            for day in ["2026-09-30", "2026-10-01"]
        ]
    result = solve_fixed_capacity_network(
        rows, demand_plan_version_id="D", capacity_plan_version_id="P",
        horizon_start="2026-09-30", horizon_end="2026-10-01", region_id="ALL",
        lane_unit_costs={"LH1": 1, "LH2": 2},
        lane_unit_costs_by_date_lane={("2026-10-01", "LH1"): 3, ("2026-10-01", "LH2"): 1},
    )
    allocations = {(row["service_date"], row["lane_id"]): row["assigned_units"]
                   for row in result["allocation_rows"]}
    assert allocations[("2026-09-30", "LH1")] == 5
    assert allocations[("2026-09-30", "LH2")] == 0
    assert allocations[("2026-10-01", "LH1")] == 0
    assert allocations[("2026-10-01", "LH2")] == 5
    assert rows["baseline_network_flow_daily"] == original["baseline_network_flow_daily"]
