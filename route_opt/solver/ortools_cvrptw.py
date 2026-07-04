from __future__ import annotations

import time
from typing import Iterable

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .diagnostics import solver_diagnostic
from .problem import SolverProblem, build_solver_problem
from ..baseline import build_route_from_ordered_stops
from ..cost import CostParameters
from ..schemas import stable_id

DROP_PENALTY = 10_000_000
LATE_MINUTE_PENALTY = 25_000


def solve_scenario_partition(
    *,
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    planning_depots: list[dict[str, object]],
    planning_customers: list[dict[str, object]],
    planning_fleet: list[dict[str, object]],
    planning_stops: list[dict[str, object]],
    travel_matrix: Iterable[dict[str, object]] | None = None,
    params: CostParameters | None = None,
    time_limit_seconds: int = 5,
) -> dict[str, list[dict[str, object]] | dict[str, object]]:
    """Solve a scenario/depot/day partition with OR-Tools CVRPTW."""

    params = params or CostParameters()
    problem = build_solver_problem(
        scenario_id=scenario_id,
        depot_id=depot_id,
        delivery_day=delivery_day,
        planning_depots=planning_depots,
        planning_customers=planning_customers,
        planning_fleet=planning_fleet,
        planning_stops=planning_stops,
        travel_matrix=travel_matrix,
        params=params,
    )
    if problem.customer_count == 0:
        return _empty_solution(problem, status="succeeded", message="No customer stops in partition.")
    if problem.vehicle_count == 0:
        return _empty_solution(
            problem,
            status="infeasible",
            message="No vehicles available for partition.",
            unassigned_reason="no_vehicle_available",
        )

    manager = pywrapcp.RoutingIndexManager(
        len(problem.node_ids),
        problem.vehicle_count,
        0,
    )
    routing = pywrapcp.RoutingModel(manager)

    cost_callback_index = routing.RegisterTransitCallback(
        lambda from_index, to_index: _arc_cost_cents(
            problem,
            params,
            manager.IndexToNode(from_index),
            manager.IndexToNode(to_index),
        )
    )
    routing.SetArcCostEvaluatorOfAllVehicles(cost_callback_index)
    for vehicle_index, fixed_cost in enumerate(problem.vehicle_fixed_costs):
        routing.SetFixedCostOfVehicle(int(round(fixed_cost * 100)), vehicle_index)

    demand_callback_index = routing.RegisterUnaryTransitCallback(
        lambda from_index: problem.demands[manager.IndexToNode(from_index)]
    )
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,
        problem.vehicle_capacities,
        True,
        "Cases",
    )

    time_callback_index = routing.RegisterTransitCallback(
        lambda from_index, to_index: _transit_minutes(
            problem,
            manager.IndexToNode(from_index),
            manager.IndexToNode(to_index),
        )
    )
    horizon = problem.route_start_minutes + max(problem.vehicle_max_route_minutes) + 1_440
    routing.AddDimension(
        time_callback_index,
        max(problem.vehicle_max_route_minutes),
        horizon,
        False,
        "Time",
    )
    time_dimension = routing.GetDimensionOrDie("Time")
    for vehicle_index, max_minutes in enumerate(problem.vehicle_max_route_minutes):
        start_index = routing.Start(vehicle_index)
        end_index = routing.End(vehicle_index)
        time_dimension.CumulVar(start_index).SetRange(
            problem.route_start_minutes,
            problem.route_start_minutes,
        )
        time_dimension.CumulVar(end_index).SetRange(
            problem.route_start_minutes,
            problem.route_start_minutes + max_minutes,
        )

    for node_index in range(1, len(problem.node_ids)):
        routing_index = manager.NodeToIndex(node_index)
        if problem.hard_windows[node_index]:
            time_dimension.CumulVar(routing_index).SetRange(
                problem.window_starts[node_index],
                problem.window_ends[node_index],
            )
        else:
            time_dimension.CumulVar(routing_index).SetMin(problem.window_starts[node_index])
            time_dimension.SetCumulVarSoftUpperBound(
                routing_index,
                problem.window_ends[node_index],
                LATE_MINUTE_PENALTY,
            )
        routing.AddDisjunction([routing_index], DROP_PENALTY)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_parameters.time_limit.FromSeconds(time_limit_seconds)

    started_at = time.perf_counter()
    assignment = routing.SolveWithParameters(search_parameters)
    elapsed_seconds = time.perf_counter() - started_at
    status_code = routing.status()
    if assignment is None:
        return _empty_solution(
            problem,
            status="infeasible",
            message="OR-Tools returned no solution.",
            unassigned_reason="solver_no_solution",
            status_code=status_code,
            solve_seconds=elapsed_seconds,
            time_limit_seconds=time_limit_seconds,
        )

    routes, route_stops = _extract_routes(problem, routing, manager, assignment, params)
    unassigned = _extract_unassigned(problem, routing, manager, assignment)
    status = "infeasible" if unassigned else "succeeded"
    message = (
        f"Solved {len(routes)} routes and dropped {len(unassigned)} stops."
        if unassigned
        else f"Solved {len(routes)} routes with all {problem.customer_count} stops assigned."
    )
    return {
        "routes": routes,
        "route_stops": route_stops,
        "unassigned_stops": unassigned,
        "diagnostics": [
            solver_diagnostic(
                scenario_id=problem.scenario_id,
                depot_id=problem.depot_id,
                delivery_day=problem.delivery_day,
                status=status,
                objective_value=float(assignment.ObjectiveValue()),
                message=message,
                solver_status_code=status_code,
                solve_seconds=round(elapsed_seconds, 3),
                vehicle_count=problem.vehicle_count,
                route_count=len(routes),
                stop_count=problem.customer_count,
                dropped_stop_count=len(unassigned),
                time_limit_seconds=time_limit_seconds,
            )
        ],
    }


def _arc_cost_cents(
    problem: SolverProblem,
    params: CostParameters,
    from_node: int,
    to_node: int,
) -> int:
    mileage_cost = problem.distance_matrix[from_node][to_node] * params.cost_per_mile
    labor_cost = (problem.duration_matrix[from_node][to_node] / 60.0) * params.labor_regular_hour
    return int(round((mileage_cost + labor_cost) * 100))


def _transit_minutes(problem: SolverProblem, from_node: int, to_node: int) -> int:
    return problem.duration_matrix[from_node][to_node] + problem.service_minutes[from_node]


def _extract_routes(
    problem: SolverProblem,
    routing: pywrapcp.RoutingModel,
    manager: pywrapcp.RoutingIndexManager,
    assignment,
    params: CostParameters,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    routes: list[dict[str, object]] = []
    route_stops: list[dict[str, object]] = []
    route_number = 1
    for vehicle_index in range(problem.vehicle_count):
        index = routing.Start(vehicle_index)
        ordered_node_indexes: list[int] = []
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            if node_index != 0:
                ordered_node_indexes.append(node_index)
            index = assignment.Value(routing.NextVar(index))
        if not ordered_node_indexes:
            continue
        ordered_stops = [problem.stops[node_index - 1] for node_index in ordered_node_indexes]
        route, sequence_rows = build_route_from_ordered_stops(
            scenario_id=problem.scenario_id,
            route_number=route_number,
            depot=problem.depot,
            ordered_stops=ordered_stops,
            delivery_day=problem.delivery_day,
            params=params,
            vehicle_id=problem.vehicle_ids[vehicle_index],
            driver_id=stable_id("DRV", route_number),
        )
        routes.append(route)
        route_stops.extend(sequence_rows)
        route_number += 1
    return routes, route_stops


def _extract_unassigned(
    problem: SolverProblem,
    routing: pywrapcp.RoutingModel,
    manager: pywrapcp.RoutingIndexManager,
    assignment,
) -> list[dict[str, object]]:
    unassigned: list[dict[str, object]] = []
    for node_index in range(1, len(problem.node_ids)):
        routing_index = manager.NodeToIndex(node_index)
        if assignment.Value(routing.NextVar(routing_index)) == routing_index:
            stop = problem.stops[node_index - 1]
            unassigned.append(
                {
                    "scenario_id": problem.scenario_id,
                    "depot_id": problem.depot_id,
                    "delivery_day": problem.delivery_day,
                    "customer_id": stop["customer_id"],
                    "reason": _drop_reason(problem, node_index),
                }
            )
    return unassigned


def _drop_reason(problem: SolverProblem, node_index: int) -> str:
    if problem.demands[node_index] > max(problem.vehicle_capacities):
        return "capacity_infeasible"
    single_stop_minutes = (
        problem.duration_matrix[0][node_index]
        + problem.service_minutes[node_index]
        + problem.duration_matrix[node_index][0]
    )
    if single_stop_minutes > max(problem.vehicle_max_route_minutes):
        return "route_duration_infeasible"
    return "dropped_by_solver_penalty"


def _empty_solution(
    problem: SolverProblem,
    *,
    status: str,
    message: str,
    unassigned_reason: str | None = None,
    status_code: int | None = None,
    solve_seconds: float | None = None,
    time_limit_seconds: int | None = None,
) -> dict[str, list[dict[str, object]] | dict[str, object]]:
    unassigned = []
    if unassigned_reason:
        unassigned = [
            {
                "scenario_id": problem.scenario_id,
                "depot_id": problem.depot_id,
                "delivery_day": problem.delivery_day,
                "customer_id": stop["customer_id"],
                "reason": unassigned_reason,
            }
            for stop in problem.stops
        ]
    return {
        "routes": [],
        "route_stops": [],
        "unassigned_stops": unassigned,
        "diagnostics": [
            solver_diagnostic(
                scenario_id=problem.scenario_id,
                depot_id=problem.depot_id,
                delivery_day=problem.delivery_day,
                status=status,
                message=message,
                solver_status_code=status_code,
                solve_seconds=round(solve_seconds, 3) if solve_seconds is not None else None,
                vehicle_count=problem.vehicle_count,
                route_count=0,
                stop_count=problem.customer_count,
                dropped_stop_count=len(unassigned),
                time_limit_seconds=time_limit_seconds,
            )
        ],
    }
