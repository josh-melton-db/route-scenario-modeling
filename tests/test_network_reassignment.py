from copy import deepcopy

from route_opt.network_flow import solve_fixed_capacity_network
from fastapi import HTTPException
from backend.models import NetworkDemandChange
from backend.services.demand_changes import DemandChangeRepository


DAY = "2026-09-30"


def _rows(*, depot_b_capacity: int = 7, include_alternative: bool = True):
    facilities = [
        {"facility_id": "DC", "facility_type": "distribution_center", "region_id": "R", "lat": 0, "lng": 0},
        {"facility_id": "A", "facility_type": "depot", "region_id": "R", "lat": 0, "lng": 1},
        {"facility_id": "B", "facility_type": "depot", "region_id": "R" if include_alternative else "OTHER", "lat": 0, "lng": 2},
    ]
    customers = [
        {"customer_id": "C1", "customer_name": "One", "region_id": "R", "depot_id": "A", "lat": 0, "lng": 1.1},
        {"customer_id": "C2", "customer_name": "Two", "region_id": "R" if include_alternative else "OTHER", "depot_id": "B", "lat": 0, "lng": 2.1},
    ]
    lanes = []
    for depot in ("A", "B"):
        lanes.extend([
            {"lane_id": f"LH-{depot}", "lane_type": "LINEHAUL", "origin_endpoint_id": "DC", "destination_endpoint_id": depot, "distance_miles": 10, "planning_cost_per_case": 1},
            {"lane_id": f"M-{depot}", "lane_type": "MARKET", "origin_endpoint_id": depot, "destination_endpoint_id": f"MKT-{depot}", "distance_miles": 1},
        ])
    for customer, depot in (("C1", "A"), ("C2", "B")):
        lanes.append({"lane_id": f"D-{customer}", "lane_type": "DELIVERY", "origin_endpoint_id": depot, "destination_endpoint_id": customer, "distance_miles": 1})
    flow = [{"demand_plan_version_id": "D", "capacity_plan_version_id": "P", "service_date": DAY, "lane_id": lane["lane_id"], "lane_type": lane["lane_type"], "assigned_units": 5 if lane["lane_type"] != "LINEHAUL" or lane["lane_id"] in {"LH-A", "LH-B"} else 0} for lane in lanes]
    return {
        "dim_facilities": facilities,
        "dim_network_customers": customers,
        "dim_network_lanes": lanes,
        "demand_plan_daily": [
            {"demand_plan_version_id": "D", "service_date": DAY, "region_id": "R", "distribution_center_id": "DC", "depot_id": "A", "customer_id": "C1", "demand_units": 5},
            {"demand_plan_version_id": "D", "service_date": DAY, "region_id": "R", "distribution_center_id": "DC", "depot_id": "B", "customer_id": "C2", "demand_units": 5},
        ],
        "facility_capacity_daily": [{"capacity_plan_version_id": "P", "service_date": DAY, "facility_id": key, "capacity_units": value} for key, value in {"DC": 10, "A": 5, "B": depot_b_capacity}.items()],
        "lane_capacity_daily": [{"capacity_plan_version_id": "P", "service_date": DAY, "lane_id": lane["lane_id"], "capacity_units": 10 if lane["lane_type"] == "LINEHAUL" else 5} for lane in lanes],
        "baseline_network_flow_daily": flow,
    }


def _solve(rows):
    return solve_fixed_capacity_network(rows, demand_plan_version_id="D", capacity_plan_version_id="P", horizon_start=DAY, horizon_end=DAY, region_id="ALL", release_requests=[{"service_date": DAY, "customer_id": "C1", "source_depot_id": "A", "cases": 2}])


def test_release_is_conserved_and_never_returns_to_source_depot():
    result = _solve(_rows())
    c1 = [r for r in result["assignment_rows"] if r["customer_id"] == "C1"]
    assert {(r["depot_id"], r["assignment_kind"], r["assigned_units"]) for r in c1} == {("A", "locked", 3), ("B", "released", 2)}
    assert sum(r["assigned_units"] for r in result["assignment_rows"]) + sum(r["unmet_units"] for r in result["unmet_rows"]) == 10
    by_layer = {layer: sum(int(r["assigned_units"]) for r in result["flow_rows"] if r["lane_type"] == layer) for layer in ("LINEHAUL", "MARKET", "DELIVERY")}
    assert by_layer == {"LINEHAUL": 10, "MARKET": 10, "DELIVERY": 10}
    demand_by_depot = {depot: sum(int(r["required_units"]) for r in result["assignment_overlay_rows"] if r["depot_id"] == depot) for depot in ("A", "B")}
    assert demand_by_depot == {"A": 3, "B": 7}
    generated = next(r for r in result["network_lanes"] if r["lane_id"] == "LNE_B_TO_C1")
    assert generated["eligibility_source"] == "deterministic_nearby_same_region_release_v1"
    assert next(r["capacity_units"] for r in result["lane_capacity_rows"] if r["lane_id"] == generated["lane_id"]) == 2


def test_released_cases_are_unmet_when_alternative_capacity_is_consumed():
    result = _solve(_rows(depot_b_capacity=5))
    assert not [r for r in result["assignment_rows"] if r["customer_id"] == "C1" and r["assignment_kind"] == "released"]
    assert sum(r["unmet_units"] for r in result["unmet_rows"]) == 2
    assert sum(r["assigned_units"] for r in result["allocation_rows"] if r["depot_id"] == "B") == 5


def test_released_cases_are_unmet_without_an_eligible_destination():
    rows = _rows(include_alternative=False)
    original = deepcopy(rows)
    result = _solve(rows)
    assert sum(r["unmet_units"] for r in result["unmet_rows"]) == 2
    source = next(r for r in result["assignment_overlay_rows"] if r["customer_id"] == "C1" and r["depot_id"] == "A")
    assert source["required_units"] == 5 and source["assigned_units"] == 3 and source["unmet_units"] == 2
    assert rows == original


def test_claim_rejects_new_change_and_resolves_only_claimed_ids():
    repository = DemandChangeRepository()
    def change(change_id: str, customer_id: str) -> NetworkDemandChange:
        return NetworkDemandChange(change_id=change_id, parent_run_id="RUN", depot_plan_id="PLAN", route_scenario_id="NAMED", depot_id="A", service_date=DAY, customer_id=customer_id, cases=1, created_at="2026-09-30T00:00:00+00:00")
    repository.create(change("ONE", "C1"))
    claimed = repository.claim("RUN")
    try:
        repository.create(change("TWO", "C2"))
        raise AssertionError("create should reject a claimed parent run")
    except HTTPException as exc:
        assert exc.status_code == 409
    repository.resolve("RUN", "CHILD", {row.change_id for row in claimed})
    assert [(row.change_id, row.status) for row in repository.list("RUN")] == [("ONE", "resolved")]


def test_chained_release_starts_from_parent_assignment_overlay():
    rows = _rows()
    first = _solve(rows)
    child_rows = deepcopy(rows)
    child_rows["dim_facilities"].append({"facility_id": "C", "facility_type": "depot", "region_id": "R", "lat": 0, "lng": 1.11})
    child_rows["dim_network_lanes"] = deepcopy(first["network_lanes"]) + [
        {"lane_id": "LH-C", "lane_type": "LINEHAUL", "origin_endpoint_id": "DC", "destination_endpoint_id": "C", "distance_miles": 10, "planning_cost_per_case": 1},
        {"lane_id": "M-C", "lane_type": "MARKET", "origin_endpoint_id": "C", "destination_endpoint_id": "MKT-C", "distance_miles": 1},
    ]
    child_rows["baseline_network_flow_daily"] = deepcopy(first["flow_rows"]) + [
        {"demand_plan_version_id": "D", "capacity_plan_version_id": "P", "service_date": DAY, "lane_id": "LH-C", "lane_type": "LINEHAUL", "assigned_units": 0},
        {"demand_plan_version_id": "D", "capacity_plan_version_id": "P", "service_date": DAY, "lane_id": "M-C", "lane_type": "MARKET", "assigned_units": 0},
    ]
    child_rows["facility_capacity_daily"].append({"capacity_plan_version_id": "P", "service_date": DAY, "facility_id": "C", "capacity_units": 2})
    child_rows["lane_capacity_daily"] = deepcopy(first["lane_capacity_rows"]) + [
        {"capacity_plan_version_id": "P", "service_date": DAY, "lane_id": "LH-C", "capacity_units": 2},
        {"capacity_plan_version_id": "P", "service_date": DAY, "lane_id": "M-C", "capacity_units": 2},
    ]
    child_rows["network_customer_assignments_daily"] = deepcopy(first["assignment_overlay_rows"])
    second = solve_fixed_capacity_network(child_rows, demand_plan_version_id="D", capacity_plan_version_id="P", horizon_start=DAY, horizon_end=DAY, region_id="ALL", release_requests=[{"service_date": DAY, "customer_id": "C1", "source_depot_id": "B", "cases": 2}])
    c1 = {(r["depot_id"], r["required_units"], r["assigned_units"], r["unmet_units"]) for r in second["assignment_overlay_rows"] if r["customer_id"] == "C1"}
    assert c1 == {("A", 3, 3, 0), ("C", 2, 2, 0)}
    assert sum(r["required_units"] for r in second["assignment_overlay_rows"] if r["customer_id"] == "C1") == 5


def test_parent_assignment_overlay_is_preserved_without_new_releases():
    rows = _rows()
    first = _solve(rows)
    child_rows = deepcopy(rows)
    child_rows["dim_network_lanes"] = deepcopy(first["network_lanes"])
    child_rows["lane_capacity_daily"] = deepcopy(first["lane_capacity_rows"])
    child_rows["baseline_network_flow_daily"] = deepcopy(first["flow_rows"])
    child_rows["network_customer_assignments_daily"] = deepcopy(
        first["assignment_overlay_rows"]
    )

    rerun = solve_fixed_capacity_network(
        child_rows,
        demand_plan_version_id="D",
        capacity_plan_version_id="P",
        horizon_start=DAY,
        horizon_end=DAY,
        region_id="ALL",
        release_requests=[],
    )

    expected = {
        (row["customer_id"], row["depot_id"], row["required_units"])
        for row in first["assignment_overlay_rows"]
    }
    actual = {
        (row["customer_id"], row["depot_id"], row["required_units"])
        for row in rerun["assignment_overlay_rows"]
    }
    assert actual == expected


def test_aggregate_demand_ignores_customer_assignment_overlay_without_release():
    rows = _rows()
    rows["demand_plan_daily"] = [
        {
            key: value
            for key, value in row.items()
            if key != "customer_id"
        }
        for row in rows["demand_plan_daily"]
    ]
    rows["network_customer_assignments_daily"] = [
        {
            "demand_plan_version_id": "D",
            "capacity_plan_version_id": "P",
            "service_date": DAY,
            "customer_id": "C1",
            "depot_id": "A",
            "required_units": 5,
            "assigned_units": 5,
            "unmet_units": 0,
            "source_depot_id": "A",
        }
    ]

    result = solve_fixed_capacity_network(
        rows,
        demand_plan_version_id="D",
        capacity_plan_version_id="P",
        horizon_start=DAY,
        horizon_end=DAY,
        region_id="ALL",
        release_requests=[],
    )

    assert sum(row["assigned_units"] for row in result["allocation_rows"]) == 10
    assert "assignment_overlay_rows" not in result


def test_aggregate_demand_rejects_explicit_customer_release():
    rows = _rows()
    for row in rows["demand_plan_daily"]:
        row.pop("customer_id")

    try:
        _solve(rows)
        raise AssertionError("aggregate demand must not enter customer reassignment")
    except ValueError as exc:
        assert str(exc) == "Customer release requests require customer-level demand rows."
