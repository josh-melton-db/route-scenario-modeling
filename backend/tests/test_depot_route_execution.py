from __future__ import annotations

import pytest

from backend.services.depot_route_execution import (
    DatedRouteExecutor,
    RouteExecutionError,
    _merge_road_unreachable,
    _preprocess_road_reachability,
    _validate_directed_matrix,
)
from route_opt.cost import CostParameters
from route_opt.depot_planning import materialize_depot_targets


DATE = "2026-10-01"
DEPOT = "DPT_TEST"


def _reachability_matrix() -> list[dict[str, object]]:
    ids = [f"{DEPOT}:DEPOT", "C1", "C2"]
    rows = []
    for origin in range(3):
        for destination in range(3):
            rows.append({
                "origin_index": origin, "destination_index": destination,
                "origin_id": ids[origin], "destination_id": ids[destination],
                "distance_miles": 0 if origin == destination else 1,
                "duration_minutes": 0 if origin == destination else 1,
                "road_reachable": not (origin == 0 and destination == 2),
            })
    return rows


def test_directed_asymmetric_depot_unreachable_stop_is_removed_and_reindexed() -> None:
    stops = [{"customer_id": "C1"}, {"customer_id": "C2"}]
    orders = [
        {"customer_id": "C1", "demand_cases": 4},
        {"customer_id": "C2", "demand_cases": 6},
    ]
    matrix, reachable, unreachable = _preprocess_road_reachability(
        _reachability_matrix(), stops, orders
    )
    assert [row["customer_id"] for row in reachable] == ["C1"]
    assert unreachable == [{"customer_id": "C2", "demand_cases": 6, "reason": "road_unreachable"}]
    assert len(matrix) == 4
    assert {(row["origin_index"], row["destination_index"]) for row in matrix} == {
        (0, 0), (0, 1), (1, 0), (1, 1)
    }


def test_all_unreachable_stops_finish_with_exact_reconciliation() -> None:
    matrix = _reachability_matrix()
    for row in matrix:
        if row["origin_index"] == 0 and row["destination_index"] != 0:
            row["road_reachable"] = False
    _, reachable, unreachable = _preprocess_road_reachability(
        matrix,
        [{"customer_id": "C1"}, {"customer_id": "C2"}],
        [{"customer_id": "C1", "demand_cases": 4}, {"customer_id": "C2", "demand_cases": 6}],
    )
    assert reachable == []
    solved: dict[str, object] = {
        "assigned_cases": 0, "routed_cases": 0, "unserved_cases": 0,
        "unserved_orders": [], "diagnostics": [], "targets": {"assigned_cases": 0},
    }
    _merge_road_unreachable(solved, unreachable, 10)
    assert solved["assigned_cases"] == 10
    assert solved["routed_cases"] == 0
    assert solved["unserved_cases"] == 10
    assert {row["customer_id"] for row in solved["unserved_orders"]} == {"C1", "C2"}
    assert solved["diagnostics"][0]["reason"] == "road_unreachable"


def _inputs(cases: int = 10):
    rows = {
        "demand_plan_versions": [{"horizon_start": DATE, "horizon_end": DATE}],
        "dim_facilities": [{
            "facility_id": DEPOT, "facility_name": "Depot", "facility_type": "depot",
            "region_id": "R", "lat": 30.0, "lng": -97.0,
        }],
        "dim_network_customers": [{
            "customer_id": "C1", "customer_name": "One", "depot_id": DEPOT,
            "lat": 30.1, "lng": -97.1, "receiving_window_start": "08:00",
            "receiving_window_end": "16:00", "service_minutes": 20,
        }],
        "dim_network_lanes": [{
            "lane_id": "L1", "lane_type": "DELIVERY",
            "origin_endpoint_id": DEPOT, "destination_endpoint_id": "C1",
        }],
    }
    flows = [{
        "service_date": DATE, "lane_id": "L1", "lane_type": "DELIVERY",
        "assigned_units": cases,
    }]
    fleet = [{
        "vehicle_id": "V1", "depot_id": DEPOT, "capacity_cases": 20,
        "max_route_minutes": 600, "max_stops_per_route": 10,
        "fixed_truck_daily_cost": 100.0,
    }]
    return rows, flows, fleet


def _matrix():
    ids = [f"{DEPOT}:DEPOT", "C1"]
    distances = [[0.0, 7.0], [11.0, 0.0]]
    return [
        {
            "origin_id": ids[i], "destination_id": ids[j],
            "origin_index": i, "destination_index": j,
            "distance_miles": distances[i][j],
            "duration_minutes": 0 if i == j else distances[i][j] * 2,
            "matrix_source": "valhalla",
        }
        for i in range(2) for j in range(2)
    ]


def test_strict_path_preserves_ordered_points_asymmetric_arcs_and_date(monkeypatch):
    monkeypatch.setenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", "dated-route-solver")
    rows, flows, fleet = _inputs()
    observed = {}

    def coverage(depot_id, points, **kwargs):
        observed["coverage"] = (depot_id, points, kwargs)
        return {
            "coverage_id": "texas", "artifact_version": "v7",
            "endpoint_url": "https://road.example", "costing": "truck",
            "max_points": 10, "bounds": {},
        }

    class MatrixClient:
        def __init__(self, url, **kwargs):
            observed["matrix_config"] = (url, kwargs)

        def build_travel_matrix(self, **kwargs):
            observed["matrix_request"] = kwargs
            return [], _matrix()

    def endpoint(**kwargs):
        observed["endpoint"] = kwargs
        return {"routes": [], "route_stops": [], "unassigned_stops": [], "diagnostics": []}

    def local_solver(*args, **kwargs):
        observed["solver_matrix"] = kwargs["travel_matrix"]
        kwargs["partition_solver"](
            scenario_id=kwargs["scenario_id"], depot_id=DEPOT, delivery_day=DATE,
            planning_depots=[], planning_customers=[], planning_fleet=[],
            planning_stops=[], travel_matrix=kwargs["travel_matrix"],
            params=kwargs["cost_parameters"], time_limit_seconds=2,
        )
        return {"matrix_source": "valhalla"}

    result = DatedRouteExecutor(
        mode="strict_serving_road", coverage_resolver=coverage,
        matrix_client_factory=MatrixClient, endpoint_invoker=endpoint,
        local_solver=local_solver,
    )(
        network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
        fleet=fleet, scenario_id="S", cost_parameters=CostParameters(),
    )

    assert observed["coverage"][1] == [
        {"lat": 30.0, "lon": -97.0}, {"lat": 30.1, "lon": -97.1}
    ]
    assert observed["matrix_request"]["delivery_day"] == DATE
    assert observed["solver_matrix"][1]["distance_miles"] == 7.0
    assert observed["solver_matrix"][2]["distance_miles"] == 11.0
    assert observed["endpoint"]["delivery_day"] == DATE
    assert result["execution"]["coverage_id"] == "texas"
    assert result["execution"]["approximate"] is False
    assert result["execution"]["solver"] == "model_serving"
    assert result["execution"]["matrix_cache"] in {"miss", "hit"}
    assert result["execution"]["solver_contract_version"] == 2
    assert len(result["execution"]["matrix_hash"]) == 64


def test_unreachable_or_misaligned_matrix_is_rejected():
    matrix = _matrix()
    matrix[1]["distance_miles"] = float("inf")
    with pytest.raises(RouteExecutionError, match="unreachable"):
        _validate_directed_matrix(matrix, {"depot_id": DEPOT}, [{"customer_id": "C1"}])


def test_road_matrix_cache_reuses_exact_artifact_and_ordered_points():
    rows, flows, fleet = _inputs()
    calls = 0

    class MatrixClient:
        def __init__(self, *args, **kwargs):
            pass

        def build_travel_matrix(self, **kwargs):
            nonlocal calls
            calls += 1
            return [], _matrix()

    executor = DatedRouteExecutor(
        mode="local_road",
        coverage_resolver=lambda *args, **kwargs: {
            "coverage_id": "cache-test-only", "artifact_version": "v99",
            "endpoint_url": "https://road.example", "costing": "truck",
            "max_points": 10, "bounds": {},
        },
        matrix_client_factory=MatrixClient,
        local_solver=lambda *args, **kwargs: {"matrix_source": "valhalla"},
    )
    first = executor(
        network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
        fleet=fleet, scenario_id="one", cost_parameters=CostParameters(),
    )
    second = executor(
        network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
        fleet=fleet, scenario_id="two", cost_parameters=CostParameters(),
    )

    assert calls == 1
    assert first["execution"]["matrix_cache"] == "miss"
    assert second["execution"]["matrix_cache"] == "hit"


def test_large_problem_partitions_deterministically_and_reconciles_every_stop():
    customer_count = 151
    rows = {
        "demand_plan_versions": [{"horizon_start": DATE, "horizon_end": DATE}],
        "dim_facilities": [{
            "facility_id": DEPOT, "facility_name": "Depot", "facility_type": "depot",
            "region_id": "R", "lat": 30.0, "lng": -97.0,
        }],
        "dim_network_customers": [],
        "dim_network_lanes": [],
    }
    flows = []
    for index in range(customer_count):
        customer_id = f"C{index:03d}"
        lane_id = f"L{index:03d}"
        rows["dim_network_customers"].append({
            "customer_id": customer_id, "customer_name": customer_id,
            "depot_id": DEPOT, "lat": 30.01 + index / 10000,
            "lng": -97.01 - index / 10000,
            "receiving_window_start": "07:00", "receiving_window_end": "17:00",
            "service_minutes": 1,
        })
        rows["dim_network_lanes"].append({
            "lane_id": lane_id, "lane_type": "DELIVERY",
            "origin_endpoint_id": DEPOT, "destination_endpoint_id": customer_id,
        })
        flows.append({
            "service_date": DATE, "lane_id": lane_id,
            "lane_type": "DELIVERY", "assigned_units": 1,
        })
    fleet = [
        {"vehicle_id": "V1", "depot_id": DEPOT, "capacity_cases": 200},
        {"vehicle_id": "V2", "depot_id": DEPOT, "capacity_cases": 200},
    ]
    partition_sizes: list[int] = []

    def local_solver(network_rows, flow_rows, depot_id, service_date, fleet, **kwargs):
        targets = materialize_depot_targets(
            network_rows, flow_rows, depot_id, service_date
        )
        partition_sizes.append(len(targets["planning_customers"]))
        assigned = int(targets["assigned_cases"])
        vehicle_id = str(fleet[0]["vehicle_id"])
        return {
            "service_date": service_date,
            "depot": targets["depot"],
            "targets": {"orders": targets["orders"]},
            "routes": [{"route_id": f"R-{vehicle_id}", "vehicle_id": vehicle_id, "scenario_id": kwargs["scenario_id"]}],
            "kpis": {
                "route_count": 1, "driver_count": 1, "vehicle_count": 1,
                "total_miles": 0, "drive_minutes": 0, "service_minutes": assigned,
                "waiting_minutes": 0, "total_cases": assigned,
                "avg_stops_per_route": assigned, "avg_capacity_utilization_pct": 0,
                "avg_driver_utilization_pct": 0, "overtime_minutes": 0,
                "missed_windows": 0, "late_minutes": 0, "total_revenue": 0,
                "profit": 0, "cost_breakdown": {"total_cost": 0},
            },
            "assigned_cases": assigned, "routed_cases": assigned, "unserved_cases": 0,
            "unserved_orders": [], "diagnostics": [],
            "matrix_source": "haversine_circuity",
        }

    result = DatedRouteExecutor(
        mode="approximate_development", local_solver=local_solver
    )(
        network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
        fleet=fleet, scenario_id="large", cost_parameters=CostParameters(),
    )

    assert partition_sizes == [149, 2]
    assert result["execution"]["partition_count"] == 2
    assert result["assigned_cases"] == result["routed_cases"] == customer_count
    assert result["unserved_cases"] == 0
    assert len(result["targets"]["orders"]) == customer_count
    assert {route["vehicle_id"] for route in result["routes"]} == {"V1", "V2"}
    matrix = _matrix()
    matrix[1]["destination_id"] = "WRONG"
    with pytest.raises(RouteExecutionError, match="do not align"):
        _validate_directed_matrix(matrix, {"depot_id": DEPOT}, [{"customer_id": "C1"}])


def test_road_mode_rejects_non_truck_coverage_before_matrix_or_solver():
    rows, flows, fleet = _inputs()
    executor = DatedRouteExecutor(
        mode="local_road",
        coverage_resolver=lambda *args, **kwargs: {
            "coverage_id": "texas", "artifact_version": "v1",
            "endpoint_url": "https://road.example", "costing": "auto", "max_points": 10,
        },
        matrix_client_factory=lambda *args, **kwargs: pytest.fail("Must reject before matrix request"),
    )
    with pytest.raises(RouteExecutionError, match="requires validated truck costing"):
        executor(network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
                 fleet=fleet, scenario_id="S", cost_parameters=CostParameters())


def test_strict_coverage_failure_never_downgrades_to_local(monkeypatch):
    monkeypatch.setenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", "dated-route-solver")
    rows, flows, fleet = _inputs()
    called = False

    def local_solver(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    executor = DatedRouteExecutor(
        mode="strict_serving_road",
        coverage_resolver=lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("outside bounds")),
        local_solver=local_solver,
    )
    with pytest.raises(RouteExecutionError, match="outside bounds"):
        executor(
            network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
            fleet=fleet, scenario_id="S", cost_parameters=CostParameters(),
        )
    assert called is False


def test_no_work_skips_coverage_and_matrix():
    rows, flows, fleet = _inputs(0)
    executor = DatedRouteExecutor(
        mode="strict_serving_road",
        coverage_resolver=lambda *args, **kwargs: pytest.fail("coverage called"),
        local_solver=lambda *args, **kwargs: {
            "assigned_cases": 0, "matrix_source": "haversine_circuity"
        },
    )
    result = executor(
        network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
        fleet=fleet, scenario_id="S", cost_parameters=CostParameters(),
    )
    assert result["execution"]["matrix_source"] == "not_requested_no_work"
    assert result["execution"]["solver"] == "none"
    assert result["execution"]["solver_invoked"] is False


def test_strict_rejects_defaulted_or_unsupported_constraints(monkeypatch):
    monkeypatch.setenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", "dated-route-solver")
    rows, flows, fleet = _inputs()
    del rows["dim_network_customers"][0]["service_minutes"]
    executor = DatedRouteExecutor(mode="strict_serving_road")
    with pytest.raises(RouteExecutionError, match="service_minutes"):
        executor(
            network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
            fleet=fleet, scenario_id="S", cost_parameters=CostParameters(),
        )
    rows, flows, fleet = _inputs()
    fleet[0]["shift_start"] = "07:00"
    with pytest.raises(RouteExecutionError, match="shift_start"):
        executor(
            network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
            fleet=fleet, scenario_id="S", cost_parameters=CostParameters(),
        )


def test_local_modes_report_truthful_solver_and_matrix_provenance():
    rows, flows, fleet = _inputs()
    approximate = DatedRouteExecutor(
        mode="approximate_development",
        local_solver=lambda *args, **kwargs: {"matrix_source": "haversine_circuity"},
    )(
        network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
        fleet=fleet, scenario_id="S", cost_parameters=CostParameters(),
    )
    expected = {
        "mode": "approximate_development",
        "solver": "local_ortools",
        "solver_invoked": True,
        "matrix_source": "haversine_circuity",
        "matrix_requested": False,
        "matrix_cache": "disabled",
        "resource_source": "pinned_fleet",
        "approximate": True,
    }
    assert {key: approximate["execution"][key] for key in expected} == expected
    assert approximate["execution"]["solver_contract_version"] == 2
    assert len(approximate["execution"]["input_hash"]) == 64

    class MatrixClient:
        def __init__(self, *args, **kwargs):
            pass

        def build_travel_matrix(self, **kwargs):
            return [], _matrix()

    local_road = DatedRouteExecutor(
        mode="local_road",
        coverage_resolver=lambda *args, **kwargs: {
            "coverage_id": "texas", "artifact_version": "v7",
            "endpoint_url": "https://road.example", "costing": "truck",
            "max_points": 10, "bounds": {},
        },
        matrix_client_factory=MatrixClient,
        local_solver=lambda *args, **kwargs: {"matrix_source": "valhalla"},
    )(
        network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
        fleet=fleet, scenario_id="S", cost_parameters=CostParameters(),
    )
    assert local_road["execution"]["solver"] == "local_ortools"
    assert local_road["execution"]["solver_endpoint"] is None
    assert local_road["execution"]["matrix_requested"] is True
    assert local_road["execution"]["matrix_source"] == "valhalla"
    assert local_road["execution"]["approximate"] is False


def test_strict_serving_payload_retains_pinned_customer_fleet_and_cost_constraints(monkeypatch):
    monkeypatch.setenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", "dated-route-solver")
    rows, flows, fleet = _inputs()
    rows["dim_network_customers"][0].update({
        "customer_priority": "strategic", "hard_time_window_flag": True,
        "special_handling": "none",
    })
    observed = {}

    class MatrixClient:
        def __init__(self, *args, **kwargs):
            pass

        def build_travel_matrix(self, **kwargs):
            return [], _matrix()

    def endpoint(**kwargs):
        observed.update(kwargs)
        return {
            "routes": [], "route_stops": [],
            "unassigned_stops": [{"customer_id": "C1", "reason": "capacity_infeasible"}],
            "diagnostics": [],
        }

    params = CostParameters(cost_per_mile=4.2, labor_regular_hour=93.0)
    result = DatedRouteExecutor(
        mode="strict_serving_road",
        coverage_resolver=lambda *args, **kwargs: {
            "coverage_id": "texas", "artifact_version": "v7",
            "endpoint_url": "https://road.example", "costing": "truck",
            "max_points": 10, "bounds": {},
        },
        matrix_client_factory=MatrixClient,
        endpoint_invoker=endpoint,
    )(
        network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
        fleet=fleet, scenario_id="S", cost_parameters=params,
    )

    customer = observed["planning_customers"][0]
    vehicle = observed["planning_fleet"][0]
    assert customer["receiving_window_start"] == "08:00"
    assert customer["receiving_window_end"] == "16:00"
    assert customer["service_minutes"] == 20
    assert customer["hard_time_window_flag"] is True
    assert vehicle["capacity_cases"] == 20
    assert vehicle["max_route_minutes"] == 600
    assert vehicle["max_stops_per_route"] == 10
    assert vehicle["fixed_truck_daily_cost"] == 100.0
    assert vehicle["available_days"] == DATE
    assert observed["cost_parameters"]["cost_per_mile"] == 4.2
    assert observed["cost_parameters"]["labor_regular_hour"] == 93.0
    assert result["assigned_cases"] == result["unserved_cases"] == 10

@pytest.mark.parametrize("failure", [RuntimeError("serving unavailable"), ValueError("malformed predictions")])
def test_serving_failures_propagate_without_local_retry(monkeypatch, failure):
    monkeypatch.setenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", "dated-route-solver")
    rows, flows, fleet = _inputs()
    calls = 0

    class MatrixClient:
        def __init__(self, *args, **kwargs):
            pass

        def build_travel_matrix(self, **kwargs):
            return [], _matrix()

    def endpoint(**kwargs):
        raise failure

    def local_solver(*args, **kwargs):
        nonlocal calls
        calls += 1
        kwargs["partition_solver"](
            scenario_id="S", depot_id=DEPOT, delivery_day=DATE,
            planning_depots=[], planning_customers=[], planning_fleet=[],
            planning_stops=[], travel_matrix=kwargs["travel_matrix"],
            params=kwargs["cost_parameters"], time_limit_seconds=2,
        )
        pytest.fail("serving failure was swallowed")

    executor = DatedRouteExecutor(
        mode="strict_serving_road",
        coverage_resolver=lambda *args, **kwargs: {
            "coverage_id": "texas", "artifact_version": "v7",
            "endpoint_url": "https://road.example", "costing": "truck",
            "max_points": 10, "bounds": {},
        },
        matrix_client_factory=MatrixClient,
        endpoint_invoker=endpoint,
        local_solver=local_solver,
    )
    with pytest.raises(type(failure), match=str(failure)):
        executor(
            network_rows=rows, flow_rows=flows, depot_id=DEPOT, service_date=DATE,
            fleet=fleet, scenario_id="S", cost_parameters=CostParameters(),
        )
    assert calls == 1
