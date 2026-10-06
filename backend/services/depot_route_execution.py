from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
import math
import time
from typing import Any

import ortools

from route_opt.cost import CostParameters
from route_opt.depot_planning import materialize_depot_targets, solve_depot_plan
from route_opt.matrix import build_travel_matrix

from ..config import (
    allow_haversine_fallback,
    get_route_execution_mode,
    get_route_solver_endpoint,
    get_routing_coverage_manifest,
    get_valhalla_max_snap_distance_miles,
)
from .solver import solver_service
from .valhalla import ValhallaMatrixClient
from .route_matrix_cache import route_matrix_cache
from route_opt.solver.payload import MAX_SOLVER_POINTS, compact_travel_matrix


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
        coverage_resolver: Callable[..., Mapping[str, object] | None] = _resolve_coverage,
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
        started_at = time.perf_counter()
        targets = materialize_depot_targets(
            network_rows, flow_rows, depot_id, service_date
        )
        if len(list(targets["planning_customers"])) + 1 > MAX_SOLVER_POINTS:
            return self._solve_partitioned(
                mode=mode,
                network_rows=network_rows,
                flow_rows=flow_rows,
                depot_id=depot_id,
                service_date=service_date,
                fleet=fleet,
                scenario_id=scenario_id,
                cost_parameters=cost_parameters,
                targets=targets,
                started_at=started_at,
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
                "solver_contract_version": 2,
                "ortools_version": getattr(ortools, "__version__", "unknown"),
                "input_hash": _stable_hash({"depot_id": depot_id, "service_date": service_date, "fleet": fleet}),
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
                "solver_contract_version": 2,
                "ortools_version": getattr(ortools, "__version__", "unknown"),
                "time_limit_seconds": 2,
                "input_hash": _stable_hash({"depot_id": depot_id, "service_date": service_date, "fleet": fleet}),
            }
            return solved
        if mode not in {"strict_serving_road", "serving_regional", "local_road"}:
            raise RouteExecutionError(f"Unsupported route execution mode {mode!r}.")
        serving_mode = mode in {"strict_serving_road", "serving_regional"}
        solver_endpoint = (
            get_route_solver_endpoint(required=True)
            if serving_mode else None
        )
        _validate_pinned_constraints(targets, fleet, strict=serving_mode)
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
            coverage_kwargs: dict[str, object] = {
                "manifest_path": get_routing_coverage_manifest(),
                "strict": True,
            }
            if mode == "serving_regional":
                coverage_kwargs["allow_uncovered"] = True
            coverage = self.coverage_resolver(
                depot_id,
                points,
                **coverage_kwargs,
            )
        except Exception as exc:
            raise RouteExecutionError(f"Road coverage validation failed: {exc}") from exc
        if coverage is None:
            if mode != "serving_regional":
                raise RouteExecutionError("Strict road routing did not resolve validated coverage.")
            if not allow_haversine_fallback():
                raise RouteExecutionError(
                    "No validated road coverage matches this depot solve and regional "
                    "approximation is disabled; set VALHALLA_ALLOW_HAVERSINE_FALLBACK=true "
                    "to allow an explicitly approximate matrix outside validated coverage."
                )
            matrix_started_at = time.perf_counter()
            _, matrix = build_travel_matrix(
                scenario_id=scenario_id,
                depot=depot,
                stops=stops,
                delivery_day=service_date,
            )
            matrix_cache = "disabled"
            matrix_seconds = time.perf_counter() - matrix_started_at
            coverage_metadata: dict[str, object] = {
                "coverage_id": None,
                "artifact_version": None,
                "costing": "haversine_circuity",
            }
            approximate_matrix = True
        else:
            matrix, matrix_cache, matrix_seconds = self._road_matrix(
                coverage=coverage,
                points=points,
                scenario_id=scenario_id,
                depot=depot,
                depot_id=depot_id,
                stops=stops,
                service_date=service_date,
            )
            coverage_metadata = {
                "coverage_id": coverage["coverage_id"],
                "artifact_version": coverage["artifact_version"],
                "costing": coverage["costing"],
            }
            approximate_matrix = False

        _validate_directed_matrix(matrix, depot, stops)
        matrix, stops, unreachable_orders = _preprocess_road_reachability(
            matrix, stops, list(targets["orders"])
        )
        solve_network_rows, solve_flow_rows = _filter_delivery_inputs(
            network_rows, flow_rows, depot_id,
            {str(stop["customer_id"]) for stop in stops},
        )

        partition_solver = None
        serving_metadata: dict[str, object] = {}
        if serving_mode:
            def partition_solver(**kwargs: Any) -> Mapping[str, Sequence[Mapping[str, object]]]:
                nonlocal serving_metadata
                kwargs.pop("params", None)
                kwargs.pop("time_limit_seconds", None)
                response = self.endpoint_invoker(
                    **kwargs, cost_parameters=cost_parameters.as_dict()
                )
                raw_metadata = response.pop("_metadata", None)
                if isinstance(raw_metadata, Mapping):
                    serving_metadata = dict(raw_metadata)
                return response

        solve_kwargs: dict[str, object] = {
            "scenario_id": scenario_id,
            "travel_matrix": matrix,
            "cost_parameters": cost_parameters,
        }
        if partition_solver is not None and stops:
            solve_kwargs["partition_solver"] = partition_solver
        solve_started_at = time.perf_counter()
        solved = self.local_solver(
            solve_network_rows, solve_flow_rows, depot_id, service_date, fleet, **solve_kwargs
        )
        _merge_road_unreachable(solved, unreachable_orders, int(targets["assigned_cases"]))
        solve_seconds = time.perf_counter() - solve_started_at
        compact_matrix = compact_travel_matrix(matrix)
        matrix_payload = json.dumps(compact_matrix, separators=(",", ":"), sort_keys=True)
        solved["execution"] = {
            "mode": mode,
            "solver": (
                "none_road_unreachable" if not stops else
                "model_serving" if serving_mode else "local_ortools"
            ),
            "solver_invoked": bool(stops),
            "solver_endpoint": solver_endpoint,
            "matrix_source": solved["matrix_source"],
            "matrix_requested": not approximate_matrix,
            "matrix_cache": matrix_cache,
            **coverage_metadata,
            "resource_source": "pinned_fleet",
            "approximate": approximate_matrix,
            "approximation_reason": "outside_validated_coverage" if approximate_matrix else None,
            "solver_contract_version": 2,
            "ortools_version": getattr(ortools, "__version__", "unknown"),
            "time_limit_seconds": 2,
            "input_hash": _stable_hash({"points": points, "fleet": fleet, "costs": cost_parameters.as_dict()}),
            "matrix_hash": hashlib.sha256(matrix_payload.encode("utf-8")).hexdigest(),
            "matrix_payload_bytes": len(matrix_payload.encode("utf-8")),
            "stage_seconds": {
                "matrix": round(matrix_seconds, 3),
                "solve": round(solve_seconds, 3),
                "total": round(time.perf_counter() - started_at, 3),
            },
            "serving_model": serving_metadata or None,
            "road_unreachable_customers": [order["customer_id"] for order in unreachable_orders],
        }
        return solved

    def _road_matrix(
        self, *, coverage: Mapping[str, object], points: Sequence[Mapping[str, object]],
        scenario_id: str, depot: Mapping[str, object], depot_id: str,
        stops: Sequence[Mapping[str, object]], service_date: str,
    ) -> tuple[list[dict[str, object]], str, float]:
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
        if len(points) > MAX_SOLVER_POINTS:
            raise RouteExecutionError(
                f"Route solve requires {len(points)} matrix points; the supported solver "
                f"limit is {MAX_SOLVER_POINTS}. Partition the problem before solving."
            )
        client = self.matrix_client_factory(
            str(coverage["endpoint_url"]), costing=str(coverage["costing"]),
            max_snap_distance_miles=get_valhalla_max_snap_distance_miles(),
        )
        matrix_key = _matrix_cache_key(
            coverage, points,
            max_snap_distance_miles=get_valhalla_max_snap_distance_miles(),
        )
        matrix_started_at = time.perf_counter()
        matrix = _cached_matrix(matrix_key)
        matrix_cache = "hit" if matrix is not None else "miss"
        if matrix is None:
            _, matrix = client.build_travel_matrix(
                scenario_id=scenario_id,
                depot=depot,
                stops=stops,
                delivery_day=service_date,
            )
            _store_cached_matrix(matrix_key, matrix)
        else:
            for row in matrix:
                row["scenario_id"] = scenario_id
                row["depot_id"] = depot_id
                row["delivery_day"] = service_date
        matrix_seconds = time.perf_counter() - matrix_started_at
        return matrix, matrix_cache, matrix_seconds

    def _solve_partitioned(
        self,
        *,
        mode: str,
        network_rows: Mapping[str, Sequence[Mapping[str, object]]],
        flow_rows: Sequence[Mapping[str, object]],
        depot_id: str,
        service_date: str,
        fleet: Sequence[Mapping[str, object]],
        scenario_id: str,
        cost_parameters: CostParameters,
        targets: Mapping[str, object],
        started_at: float,
    ) -> dict[str, object]:
        """Solve deterministic geographic partitions without dropping or reusing resources."""
        depot = list(targets["planning_depots"])[0]  # type: ignore[arg-type]
        customer_rows = list(targets["planning_customers"])  # type: ignore[arg-type]
        ordered = sorted(
            customer_rows,
            key=lambda row: (
                math.atan2(
                    float(row["lat"]) - float(depot["lat"]),
                    float(row["lng"]) - float(depot["lng"]),
                ),
                str(row["customer_id"]),
            ),
        )
        chunks = [
            ordered[index:index + MAX_SOLVER_POINTS - 1]
            for index in range(0, len(ordered), MAX_SOLVER_POINTS - 1)
        ]
        remaining_fleet = [dict(vehicle) for vehicle in fleet]
        child_results: list[dict[str, object]] = []
        all_customer_ids: set[str] = set()
        lanes = list(network_rows.get("dim_network_lanes", ()))
        for partition_index, chunk in enumerate(chunks, start=1):
            customer_ids = {str(row["customer_id"]) for row in chunk}
            all_customer_ids.update(customer_ids)
            delivery_lane_ids = {
                str(lane["lane_id"])
                for lane in lanes
                if str(lane.get("lane_type")) == "DELIVERY"
                and str(lane.get("origin_endpoint_id")) == depot_id
                and str(lane.get("destination_endpoint_id")) in customer_ids
            }
            partition_rows = {
                name: [dict(row) for row in rows]
                for name, rows in network_rows.items()
            }
            partition_rows["dim_network_lanes"] = [
                dict(lane) for lane in lanes
                if str(lane.get("lane_type")) != "DELIVERY"
                or str(lane.get("lane_id")) in delivery_lane_ids
            ]
            partition_flows = [
                dict(flow) for flow in flow_rows
                if str(flow.get("lane_type")) != "DELIVERY"
                or str(flow.get("lane_id")) in delivery_lane_ids
            ]
            child = self(
                network_rows=partition_rows,
                flow_rows=partition_flows,
                depot_id=depot_id,
                service_date=service_date,
                fleet=remaining_fleet,
                scenario_id=f"{scenario_id}:partition-{partition_index}",
                cost_parameters=cost_parameters,
            )
            used = {str(route["vehicle_id"]) for route in child.get("routes", [])}
            remaining_fleet = [
                vehicle for vehicle in remaining_fleet
                if str(vehicle.get("vehicle_id")) not in used
            ]
            for route in child.get("routes", []):
                route["scenario_id"] = scenario_id
            for diagnostic in child.get("diagnostics", []):
                diagnostic["partition_index"] = partition_index
                diagnostic["partition_count"] = len(chunks)
            child_results.append(child)

        expected_ids = {str(row["customer_id"]) for row in customer_rows}
        if all_customer_ids != expected_ids:
            raise RouteExecutionError("Route partitioning failed to preserve every customer stop.")
        assigned_cases = sum(int(child["assigned_cases"]) for child in child_results)
        routed_cases = sum(int(child["routed_cases"]) for child in child_results)
        unserved_cases = sum(int(child["unserved_cases"]) for child in child_results)
        if assigned_cases != int(targets["assigned_cases"]) or assigned_cases != routed_cases + unserved_cases:
            raise RouteExecutionError("Partitioned route accounting did not reconcile exactly.")
        executions = [child.get("execution", {}) for child in child_results]
        return {
            "service_date": service_date,
            "depot": targets["depot"],
            "targets": {
                "service_date": service_date,
                "depot_id": depot_id,
                "assigned_cases": assigned_cases,
                "orders": [
                    order
                    for child in child_results
                    for order in child.get("targets", {}).get("orders", [])
                ],
            },
            "routes": [route for child in child_results for route in child.get("routes", [])],
            "kpis": _merge_partition_kpis([child["kpis"] for child in child_results]),
            "assigned_cases": assigned_cases,
            "routed_cases": routed_cases,
            "unserved_cases": unserved_cases,
            "unserved_orders": [order for child in child_results for order in child.get("unserved_orders", [])],
            "diagnostics": [row for child in child_results for row in child.get("diagnostics", [])],
            "matrix_source": _common_value([child.get("matrix_source") for child in child_results], "partitioned_mixed"),
            "execution": {
                "mode": mode,
                "solver": "partitioned_model_serving" if mode in {"strict_serving_road", "serving_regional"} else "partitioned_local_ortools",
                "solver_invoked": True,
                "matrix_requested": any(bool(execution.get("matrix_requested")) for execution in executions),
                "matrix_cache": _common_value([execution.get("matrix_cache") for execution in executions], "mixed"),
                "resource_source": "pinned_fleet",
                "approximate": any(bool(execution.get("approximate")) for execution in executions),
                "partitioned": True,
                "partition_count": len(chunks),
                "partition_policy": "geographic_angle_sequential_vehicle_exclusive_v1",
                "solver_contract_version": 2,
                "input_hash": _stable_hash({"customers": customer_rows, "fleet": fleet, "costs": cost_parameters.as_dict()}),
                "matrix_hashes": [execution.get("matrix_hash") for execution in executions if execution.get("matrix_hash")],
                "matrix_payload_bytes": sum(int(execution.get("matrix_payload_bytes", 0)) for execution in executions),
                "serving_models": [execution.get("serving_model") for execution in executions if execution.get("serving_model")],
                "stage_seconds": {"total": round(time.perf_counter() - started_at, 3)},
            },
        }


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


def _preprocess_road_reachability(
    matrix: Sequence[Mapping[str, object]],
    stops: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    by_pair = {
        (int(row["origin_index"]), int(row["destination_index"])): row
        for row in matrix
    }
    reachable_old = [0]
    unreachable_ids: set[str] = set()
    for index, stop in enumerate(stops, start=1):
        outward = by_pair[(0, index)].get("road_reachable", True) is not False
        inward = by_pair[(index, 0)].get("road_reachable", True) is not False
        if outward and inward:
            reachable_old.append(index)
        else:
            unreachable_ids.add(str(stop["customer_id"]))
    remap = {old: new for new, old in enumerate(reachable_old)}
    reduced: list[dict[str, object]] = []
    for old_origin in reachable_old:
        for old_destination in reachable_old:
            row = dict(by_pair[(old_origin, old_destination)])
            row["origin_index"] = remap[old_origin]
            row["destination_index"] = remap[old_destination]
            reduced.append(row)
    reachable_stops = [
        dict(stop) for stop in stops
        if str(stop["customer_id"]) not in unreachable_ids
    ]
    unreachable_orders = [
        {**dict(order), "reason": "road_unreachable"}
        for order in orders if str(order["customer_id"]) in unreachable_ids
    ]
    return reduced, reachable_stops, unreachable_orders


def _filter_delivery_inputs(
    network_rows: Mapping[str, Sequence[Mapping[str, object]]],
    flow_rows: Sequence[Mapping[str, object]],
    depot_id: str,
    reachable_customer_ids: set[str],
) -> tuple[dict[str, list[dict[str, object]]], list[dict[str, object]]]:
    rows = {name: [dict(row) for row in values] for name, values in network_rows.items()}
    lanes = rows.get("dim_network_lanes", [])
    allowed_lane_ids = {
        str(lane["lane_id"]) for lane in lanes
        if str(lane.get("lane_type")) != "DELIVERY"
        or str(lane.get("origin_endpoint_id")) != depot_id
        or str(lane.get("destination_endpoint_id")) in reachable_customer_ids
    }
    rows["dim_network_lanes"] = [
        lane for lane in lanes if str(lane["lane_id"]) in allowed_lane_ids
    ]
    return rows, [
        dict(flow) for flow in flow_rows
        if str(flow.get("lane_type")) != "DELIVERY"
        or str(flow.get("lane_id")) in allowed_lane_ids
    ]


def _merge_road_unreachable(
    solved: dict[str, object],
    unreachable_orders: Sequence[Mapping[str, object]],
    original_assigned_cases: int,
) -> None:
    if not unreachable_orders:
        return
    extra_cases = sum(int(order["demand_cases"]) for order in unreachable_orders)
    solved["assigned_cases"] = original_assigned_cases
    solved["unserved_cases"] = int(solved.get("unserved_cases", 0)) + extra_cases
    solved.setdefault("unserved_orders", []).extend(dict(order) for order in unreachable_orders)  # type: ignore[union-attr]
    solved.setdefault("diagnostics", []).append({  # type: ignore[union-attr]
        "reason": "road_unreachable",
        "customer_ids": [order["customer_id"] for order in unreachable_orders],
        "unserved_cases": extra_cases,
    })
    if original_assigned_cases != int(solved.get("routed_cases", 0)) + int(solved["unserved_cases"]):
        raise RouteExecutionError("Road reachability reconciliation failed.")
    targets = solved.get("targets")
    if isinstance(targets, dict):
        targets["assigned_cases"] = original_assigned_cases


dated_route_executor = DatedRouteExecutor()


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, default=str, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _matrix_cache_key(
    coverage: Mapping[str, object], points: Sequence[Mapping[str, object]],
    *, max_snap_distance_miles: float | None = None,
) -> str:
    return _stable_hash({
        "coverage_id": coverage["coverage_id"],
        "artifact_version": coverage["artifact_version"],
        "costing": coverage["costing"],
        "points": points,
        "snap_validation": "bounded_sources_v1",
        "max_snap_distance_miles": max_snap_distance_miles,
    })


def _cached_matrix(key: str) -> list[dict[str, object]] | None:
    return route_matrix_cache.get(key)


def _store_cached_matrix(key: str, matrix: Sequence[Mapping[str, object]]) -> None:
    route_matrix_cache.put(key, matrix)


def _common_value(values: Sequence[object], mixed: str) -> object:
    present = [value for value in values if value is not None]
    return present[0] if present and all(value == present[0] for value in present) else mixed


def _merge_partition_kpis(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not rows:
        raise RouteExecutionError("Partitioned solve produced no KPI rows.")
    route_count = sum(int(row["route_count"]) for row in rows)

    def weighted(field: str) -> float:
        if not route_count:
            return 0.0
        return round(
            sum(float(row[field]) * int(row["route_count"]) for row in rows) / route_count,
            1,
        )

    cost_keys = {
        key for row in rows for key in row.get("cost_breakdown", {}).keys()
    }
    total_revenue = round(sum(float(row.get("total_revenue", 0)) for row in rows), 2)
    total_cost = round(sum(float(row.get("cost_breakdown", {}).get("total_cost", 0)) for row in rows), 2)
    return {
        "route_count": route_count,
        "driver_count": sum(int(row["driver_count"]) for row in rows),
        "vehicle_count": sum(int(row["vehicle_count"]) for row in rows),
        "total_miles": round(sum(float(row["total_miles"]) for row in rows), 1),
        "drive_minutes": sum(int(row["drive_minutes"]) for row in rows),
        "service_minutes": sum(int(row["service_minutes"]) for row in rows),
        "waiting_minutes": sum(int(row.get("waiting_minutes", 0)) for row in rows),
        "total_cases": sum(int(row["total_cases"]) for row in rows),
        "avg_stops_per_route": weighted("avg_stops_per_route"),
        "avg_capacity_utilization_pct": weighted("avg_capacity_utilization_pct"),
        "avg_driver_utilization_pct": weighted("avg_driver_utilization_pct"),
        "overtime_minutes": sum(int(row["overtime_minutes"]) for row in rows),
        "missed_windows": sum(int(row["missed_windows"]) for row in rows),
        "late_minutes": sum(int(row["late_minutes"]) for row in rows),
        "total_revenue": total_revenue,
        "profit": round(total_revenue - total_cost, 2),
        "cost_breakdown": {
            key: round(sum(float(row.get("cost_breakdown", {}).get(key, 0)) for row in rows), 2)
            for key in sorted(cost_keys)
        },
    }
