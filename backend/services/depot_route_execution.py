from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import math
from typing import Any

from route_opt.cost import CostParameters
from route_opt.depot_planning import materialize_depot_targets, solve_depot_plan

from ..config import (
    get_route_execution_mode,
    get_route_solver_endpoint,
    get_routing_coverage_manifest,
)
from .solver import solver_service
from .valhalla import ValhallaMatrixClient


class RouteExecutionError(RuntimeError):
    """A configured dated route execution path could not be completed."""


def _resolve_coverage(*args: Any, **kwargs: Any) -> Mapping[str, object]:
    try:
        from .routing_coverage import resolve_coverage
    except ImportError as exc:
        raise RouteExecutionError(
            "Strict road routing requires backend.services.routing_coverage; "
            "configure the shared coverage registry before solving."
        ) from exc
    return resolve_coverage(*args, **kwargs)


class DatedRouteExecutor:
    def __init__(
        self,
        *,
        mode: str | None = None,
        coverage_resolver: Callable[..., Mapping[str, object]] = _resolve_coverage,
        matrix_client_factory: Callable[..., ValhallaMatrixClient] = ValhallaMatrixClient,
        endpoint_invoker: Callable[..., dict[str, list[dict[str, object]]]] | None = None,
        local_solver: Callable[..., dict[str, object]] = solve_depot_plan,
    ) -> None:
        self.mode = mode
        self.coverage_resolver = coverage_resolver
        self.matrix_client_factory = matrix_client_factory
        self.endpoint_invoker = endpoint_invoker or solver_service.invoke_endpoint
        self.local_solver = local_solver

    def __call__(
        self,
        *,
        network_rows: Mapping[str, Sequence[Mapping[str, object]]],
        flow_rows: Sequence[Mapping[str, object]],
        depot_id: str,
        service_date: str,
        fleet: Sequence[Mapping[str, object]],
        scenario_id: str,
        cost_parameters: CostParameters,
    ) -> dict[str, object]:
        mode = self.mode or get_route_execution_mode()
        targets = materialize_depot_targets(
            network_rows, flow_rows, depot_id, service_date
        )
        if int(targets["assigned_cases"]) == 0:
            solved = self.local_solver(
                network_rows, flow_rows, depot_id, service_date, fleet,
                scenario_id=scenario_id, cost_parameters=cost_parameters,
            )
            solved["execution"] = {
                "mode": mode,
                "solver": "none",
                "solver_invoked": False,
                "matrix_source": "not_requested_no_work",
                "matrix_requested": False,
                "matrix_cache": "disabled",
                "resource_source": "pinned_fleet",
                "approximate": mode == "approximate_development",
            }
            return solved

        if mode == "approximate_development":
            solved = self.local_solver(
                network_rows, flow_rows, depot_id, service_date, fleet,
                scenario_id=scenario_id, cost_parameters=cost_parameters,
            )
            solved["execution"] = {
                "mode": mode,
                "solver": "local_ortools",
                "solver_invoked": True,
                "matrix_source": solved["matrix_source"],
                "matrix_requested": False,
                "matrix_cache": "disabled",
                "resource_source": "pinned_fleet",
                "approximate": True,
            }
            return solved
        if mode not in {"strict_serving_road", "local_road"}:
            raise RouteExecutionError(f"Unsupported route execution mode {mode!r}.")
        solver_endpoint = (
            get_route_solver_endpoint(required=True)
            if mode == "strict_serving_road" else None
        )
        _validate_pinned_constraints(targets, fleet, strict=mode == "strict_serving_road")
        carrier_rows = sum(
            len(network_rows.get(name, ()))
            for name in ("carriers", "carrier_contracts", "rate_contract_details")
        )
        if carrier_rows:
            raise RouteExecutionError(
                "Dated depot execution does not yet support carrier fallback inputs; "
                "remove them or use a compatible execution adapter."
            )

        depot = list(targets["planning_depots"])[0]
        stops = list(targets["planning_customers"])
        points = [{"lat": depot["lat"], "lon": depot["lng"]}] + [
            {"lat": stop["lat"], "lon": stop["lng"]} for stop in stops
        ]
        try:
            coverage = self.coverage_resolver(
                depot_id,
                points,
                manifest_path=get_routing_coverage_manifest(),
                strict=True,
            )
        except Exception as exc:
            raise RouteExecutionError(f"Road coverage validation failed: {exc}") from exc
        required = {
            "coverage_id", "artifact_version", "endpoint_url", "costing", "max_points"
        }
        missing = sorted(required - set(coverage))
        if missing:
            raise RouteExecutionError(
                f"Coverage resolution omitted required fields: {', '.join(missing)}."
            )
        if coverage["costing"] != "truck":
            raise RouteExecutionError(
                "Dated delivery road routing requires validated truck costing; "
                f"coverage {coverage['coverage_id']!r} uses {coverage['costing']!r}."
            )
        if len(points) > int(coverage["max_points"]):
            raise RouteExecutionError(
                f"Coverage {coverage['coverage_id']!r} allows {coverage['max_points']} "
                f"matrix points; solve requires {len(points)}."
            )
        client = self.matrix_client_factory(
            str(coverage["endpoint_url"]), costing=str(coverage["costing"])
        )
        _, matrix = client.build_travel_matrix(
            scenario_id=scenario_id,
            depot=depot,
            stops=stops,
            delivery_day=service_date,
        )
        _validate_directed_matrix(matrix, depot, stops)

        partition_solver = None
        if mode == "strict_serving_road":
            def partition_solver(**kwargs: Any) -> Mapping[str, Sequence[Mapping[str, object]]]:
                kwargs.pop("params", None)
                kwargs.pop("time_limit_seconds", None)
                return self.endpoint_invoker(
                    **kwargs, cost_parameters=cost_parameters.as_dict()
                )

        solve_kwargs: dict[str, object] = {
            "scenario_id": scenario_id,
            "travel_matrix": matrix,
            "cost_parameters": cost_parameters,
        }
        if partition_solver is not None:
            solve_kwargs["partition_solver"] = partition_solver
        solved = self.local_solver(
            network_rows, flow_rows, depot_id, service_date, fleet, **solve_kwargs
        )
        solved["execution"] = {
            "mode": mode,
            "solver": "model_serving" if mode == "strict_serving_road" else "local_ortools",
            "solver_invoked": True,
            "solver_endpoint": solver_endpoint,
            "matrix_source": solved["matrix_source"],
            "matrix_requested": True,
            "matrix_cache": "disabled",
            "coverage_id": coverage["coverage_id"],
            "artifact_version": coverage["artifact_version"],
            "costing": coverage["costing"],
            "resource_source": "pinned_fleet",
            "approximate": False,
        }
        return solved


def _validate_pinned_constraints(
    targets: Mapping[str, object],
    fleet: Sequence[Mapping[str, object]],
    *,
    strict: bool,
) -> None:
    customers = list(targets["planning_customers"])  # type: ignore[arg-type]
    unsupported_customer = {
        "required_vehicle_type", "required_equipment", "vehicle_type_required"
    }
    unsupported_fleet = {
        "shift_start", "shift_end", "driver_shift_start", "driver_shift_end",
        "route_start_time",
    }
    for customer in customers:
        used = sorted(key for key in unsupported_customer if customer.get(key) not in (None, "", []))
        if used:
            raise RouteExecutionError(
                f"Customer {customer.get('customer_id')!r} uses unsupported route constraints: "
                f"{', '.join(used)}."
            )
        if strict:
            missing = list(customer.get("route_constraint_defaults", []))
            if missing:
                raise RouteExecutionError(
                    f"Customer {customer.get('customer_id')!r} is missing strict route constraints: "
                    f"{', '.join(missing)}."
                )
    for vehicle in fleet:
        used = sorted(key for key in unsupported_fleet if vehicle.get(key) not in (None, "", []))
        if used:
            raise RouteExecutionError(
                f"Vehicle {vehicle.get('vehicle_id')!r} uses unsupported route constraints: "
                f"{', '.join(used)}."
            )
        if strict:
            missing = [
                key for key in (
                    "capacity_cases", "max_route_minutes", "max_stops_per_route",
                    "fixed_truck_daily_cost",
                ) if vehicle.get(key) in (None, "")
            ]
            if missing:
                raise RouteExecutionError(
                    f"Vehicle {vehicle.get('vehicle_id')!r} is missing strict route constraints: "
                    f"{', '.join(missing)}."
                )


def _validate_directed_matrix(
    matrix: Sequence[Mapping[str, object]],
    depot: Mapping[str, object],
    stops: Sequence[Mapping[str, object]],
) -> None:
    expected_ids = [f"{depot['depot_id']}:DEPOT"] + [
        str(stop["customer_id"]) for stop in stops
    ]
    size = len(expected_ids)
    if len(matrix) != size * size:
        raise RouteExecutionError(
            f"Directed road matrix has {len(matrix)} arcs; expected {size * size}."
        )
    seen: set[tuple[int, int]] = set()
    for row in matrix:
        try:
            origin = int(row["origin_index"])
            destination = int(row["destination_index"])
            distance = float(row["distance_miles"])
            duration = float(row["duration_minutes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RouteExecutionError("Directed road matrix contains a malformed arc.") from exc
        if not (0 <= origin < size and 0 <= destination < size):
            raise RouteExecutionError("Directed road matrix contains an out-of-range node index.")
        pair = (origin, destination)
        if pair in seen:
            raise RouteExecutionError(f"Directed road matrix repeats arc {origin},{destination}.")
        seen.add(pair)
        if str(row.get("origin_id")) != expected_ids[origin] or str(
            row.get("destination_id")
        ) != expected_ids[destination]:
            raise RouteExecutionError(
                f"Directed road matrix node IDs do not align at arc {origin},{destination}."
            )
        if not all(math.isfinite(value) and value >= 0 for value in (distance, duration)):
            raise RouteExecutionError(
                f"Directed road matrix arc {origin},{destination} is unreachable."
            )
    if len(seen) != size * size:
        raise RouteExecutionError("Directed road matrix is incomplete.")


dated_route_executor = DatedRouteExecutor()
