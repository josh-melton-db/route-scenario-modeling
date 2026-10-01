from __future__ import annotations

import pytest

from backend.services.depot_route_execution import (
    DatedRouteExecutor,
    RouteExecutionError,
    _validate_directed_matrix,
)
from route_opt.cost import CostParameters


DATE = "2026-10-01"
DEPOT = "DPT_TEST"


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
    assert result["execution"]["matrix_cache"] == "disabled"


def test_unreachable_or_misaligned_matrix_is_rejected():
    matrix = _matrix()
    matrix[1]["distance_miles"] = float("inf")
    with pytest.raises(RouteExecutionError, match="unreachable"):
        _validate_directed_matrix(matrix, {"depot_id": DEPOT}, [{"customer_id": "C1"}])
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
    assert approximate["execution"] == {
        "mode": "approximate_development",
        "solver": "local_ortools",
        "solver_invoked": True,
        "matrix_source": "haversine_circuity",
        "matrix_requested": False,
        "matrix_cache": "disabled",
        "resource_source": "pinned_fleet",
        "approximate": True,
    }

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
