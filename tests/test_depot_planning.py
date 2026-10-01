from __future__ import annotations

from backend.models import Kpis, Route
from route_opt.depot_planning import materialize_depot_targets, solve_depot_plan


DATE_ONE = "2026-09-28"
DATE_TWO = "2026-09-29"
DATE_ZERO = "2026-09-30"
DEPOT_ID = "DPT_TEST"


def _network_rows() -> dict[str, list[dict[str, object]]]:
    return {
        "demand_plan_versions": [
            {"horizon_start": DATE_ONE, "horizon_end": DATE_ZERO}
        ],
        "capacity_plan_versions": [
            {"horizon_start": DATE_ONE, "horizon_end": DATE_ZERO}
        ],
        "dim_facilities": [
            {
                "facility_id": DEPOT_ID,
                "facility_name": "Test Depot",
                "facility_type": "depot",
                "region_id": "REGION_TEST",
                "lat": 39.75,
                "lng": -86.15,
            }
        ],
        "dim_network_customers": [
            {
                "customer_id": "CUST_A",
                "customer_name": "Customer A",
                "customer_tier": "strategic",
                "depot_id": DEPOT_ID,
                "lat": 39.78,
                "lng": -86.12,
                "receiving_window_start": "07:00",
                "receiving_window_end": "12:00",
                "service_minutes": 15,
                "hard_time_window_flag": True,
            },
            {
                "customer_id": "CUST_B",
                "customer_name": "Customer B",
                "customer_tier": "standard",
                "depot_id": DEPOT_ID,
                "lat": 39.70,
                "lng": -86.20,
                "receiving_window_start": "08:00",
                "receiving_window_end": "16:00",
                "service_minutes": 20,
            },
        ],
        "dim_network_lanes": [
            {
                "lane_id": "LNE_INBOUND_DC1",
                "lane_type": "LINEHAUL",
                "origin_endpoint_id": "DC_1",
                "destination_endpoint_id": DEPOT_ID,
            },
            {
                "lane_id": "LNE_INBOUND_DC2",
                "lane_type": "LINEHAUL",
                "origin_endpoint_id": "DC_2",
                "destination_endpoint_id": DEPOT_ID,
            },
            {
                "lane_id": "LNE_DELIVERY_A",
                "lane_type": "DELIVERY",
                "origin_endpoint_id": DEPOT_ID,
                "destination_endpoint_id": "CUST_A",
            },
            {
                "lane_id": "LNE_DELIVERY_B",
                "lane_type": "DELIVERY",
                "origin_endpoint_id": DEPOT_ID,
                "destination_endpoint_id": "CUST_B",
            },
        ],
    }


def _flow_rows() -> list[dict[str, object]]:
    return [
        {"service_date": DATE_ONE, "lane_id": "LNE_INBOUND_DC1", "lane_type": "LINEHAUL", "assigned_units": 70},
        {"service_date": DATE_ONE, "lane_id": "LNE_INBOUND_DC2", "lane_type": "LINEHAUL", "assigned_units": 50},
        {"service_date": DATE_ONE, "lane_id": "LNE_DELIVERY_A", "lane_type": "DELIVERY", "assigned_units": 120},
        {"service_date": DATE_ONE, "lane_id": "LNE_DELIVERY_B", "lane_type": "DELIVERY", "assigned_units": 0},
        {"service_date": DATE_TWO, "lane_id": "LNE_DELIVERY_A", "lane_type": "DELIVERY", "assigned_units": 20},
        {"service_date": DATE_TWO, "lane_id": "LNE_DELIVERY_B", "lane_type": "DELIVERY", "assigned_units": 80},
    ]


def _fleet(capacity_cases: int = 200) -> list[dict[str, object]]:
    return [
        {
            "vehicle_id": "VEH_TEST_1",
            "depot_id": DEPOT_ID,
            "capacity_cases": capacity_cases,
            "available_dates": [DATE_ONE, DATE_TWO, DATE_ZERO],
            "max_route_minutes": 600,
            "max_stops_per_route": 10,
            "fixed_truck_daily_cost": 100,
        }
    ]


def test_materializes_exact_dates_and_omits_zero_assigned_customers() -> None:
    first = materialize_depot_targets(_network_rows(), _flow_rows(), DEPOT_ID, DATE_ONE)
    second = materialize_depot_targets(_network_rows(), _flow_rows(), DEPOT_ID, DATE_TWO)

    assert first["assigned_cases"] == 120
    assert [row["customer_id"] for row in first["orders"]] == ["CUST_A"]
    assert second["assigned_cases"] == 100
    assert [row["demand_cases"] for row in second["orders"]] == [20, 80]
    assert first["orders"][0]["order_id"] != second["orders"][0]["order_id"]
    assert DATE_ONE.replace("-", "") in first["orders"][0]["order_id"]


def test_zero_demand_day_returns_empty_compatible_result() -> None:
    result = solve_depot_plan(_network_rows(), _flow_rows(), DEPOT_ID, DATE_ZERO, _fleet())

    assert result["service_date"] == DATE_ZERO
    assert result["routes"] == []
    assert result["assigned_cases"] == result["routed_cases"] == result["unserved_cases"] == 0
    assert Kpis.model_validate(result["kpis"])
    assert result["diagnostics"][0]["status"] == "succeeded"


def test_real_solver_returns_route_and_preserves_date_windows_and_ids() -> None:
    result = solve_depot_plan(_network_rows(), _flow_rows(), DEPOT_ID, DATE_TWO, _fleet())

    assert result["assigned_cases"] == result["routed_cases"] == 100
    assert result["unserved_cases"] == 0
    assert result["diagnostics"][0]["solver"] == "ortools_cvrptw"
    assert result["matrix_source"] == "haversine_circuity"
    routes = [Route.model_validate(route) for route in result["routes"]]
    assert routes[0].rated_service_date == DATE_TWO
    assert {stop.customer_id for route in routes for stop in route.stops} == {"CUST_A", "CUST_B"}
    assert {stop.time_window_start for route in routes for stop in route.stops} == {"07:00", "08:00"}
    assert all(stop.stop_id.startswith("STOP-ORD-") for route in routes for stop in route.stops)


def test_constrained_supplied_fleet_leaves_cases_unserved_without_expansion() -> None:
    result = solve_depot_plan(_network_rows(), _flow_rows(), DEPOT_ID, DATE_ONE, _fleet(100))

    assert result["assigned_cases"] == 120
    assert result["routed_cases"] == 0
    assert result["unserved_cases"] == 120
    assert result["unserved_orders"][0]["reason"] == "capacity_infeasible"
    assert result["diagnostics"][0]["vehicle_count"] == 1


def test_duplicate_inbound_sources_do_not_duplicate_delivery_targets() -> None:
    targets = materialize_depot_targets(_network_rows(), _flow_rows(), DEPOT_ID, DATE_ONE)

    assert targets["assigned_cases"] == 120
    assert len(targets["orders"]) == 1


def test_missing_hard_window_flag_preserves_priority_fallback_semantics() -> None:
    rows = _network_rows()
    rows["dim_network_customers"][0].pop("hard_time_window_flag")
    targets = materialize_depot_targets(
        rows, _flow_rows(), DEPOT_ID, DATE_ONE
    )

    customer = targets["planning_customers"][0]
    assert customer["customer_priority"] == "strategic"
    assert "hard_time_window_flag" not in customer
