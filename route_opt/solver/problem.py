from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..baseline import _hhmm_to_minutes, _join_delivery_stops
from ..cost import CostParameters
from ..matrix import build_travel_matrix, drive_minutes, haversine_miles, road_miles

DEFAULT_ROUTE_START_MINUTES = 6 * 60 + 30
DEFAULT_CAPACITY_CASES = 1000


@dataclass(frozen=True)
class SolverProblem:
    scenario_id: str
    depot_id: str
    delivery_day: str
    depot: dict[str, object]
    stops: list[dict[str, object]]
    fleet: list[dict[str, object]]
    node_ids: list[str]
    distance_matrix: list[list[float]]
    duration_matrix: list[list[int]]
    demands: list[int]
    service_minutes: list[int]
    window_starts: list[int]
    window_ends: list[int]
    hard_windows: list[bool]
    vehicle_ids: list[str]
    vehicle_capacities: list[int]
    vehicle_max_route_minutes: list[int]
    vehicle_fixed_costs: list[float]
    route_start_minutes: int = DEFAULT_ROUTE_START_MINUTES

    @property
    def customer_count(self) -> int:
        return len(self.stops)

    @property
    def vehicle_count(self) -> int:
        return len(self.vehicle_ids)


def build_solver_problem(
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
) -> SolverProblem:
    params = params or CostParameters()
    depot = next(row for row in planning_depots if row["depot_id"] == depot_id)
    stops = _join_delivery_stops(planning_customers, planning_stops, depot_id, delivery_day)
    fleet = [
        row
        for row in planning_fleet
        if row["depot_id"] == depot_id and delivery_day in str(row.get("available_days", delivery_day)).split(",")
    ]
    if not fleet:
        fleet = list(planning_fleet)

    node_ids = [f"{depot_id}:DEPOT", *[str(stop["customer_id"]) for stop in stops]]
    distance_matrix, duration_matrix = _build_matrices(
        scenario_id=scenario_id,
        depot_id=depot_id,
        delivery_day=delivery_day,
        depot=depot,
        stops=stops,
        node_ids=node_ids,
        travel_matrix=travel_matrix,
        params=params,
    )

    return SolverProblem(
        scenario_id=scenario_id,
        depot_id=depot_id,
        delivery_day=delivery_day,
        depot=depot,
        stops=stops,
        fleet=fleet,
        node_ids=node_ids,
        distance_matrix=distance_matrix,
        duration_matrix=duration_matrix,
        demands=[0, *[int(stop["demand_cases"]) for stop in stops]],
        service_minutes=[0, *[int(stop["service_minutes"]) for stop in stops]],
        window_starts=[DEFAULT_ROUTE_START_MINUTES, *[_hhmm_to_minutes(str(stop["receiving_window_start"])) for stop in stops]],
        window_ends=[
            DEFAULT_ROUTE_START_MINUTES + max(_vehicle_max_route_minutes(vehicle, params) for vehicle in fleet),
            *[_hhmm_to_minutes(str(stop["receiving_window_end"])) for stop in stops],
        ],
        hard_windows=[True, *[_has_hard_window(stop) for stop in stops]],
        vehicle_ids=[str(row["vehicle_id"]) for row in fleet],
        vehicle_capacities=[int(row.get("capacity_cases", DEFAULT_CAPACITY_CASES)) for row in fleet],
        vehicle_max_route_minutes=[_vehicle_max_route_minutes(row, params) for row in fleet],
        vehicle_fixed_costs=[float(row.get("fixed_truck_daily_cost", params.fixed_truck_daily_cost)) for row in fleet],
    )


def _vehicle_max_route_minutes(vehicle: dict[str, object], params: CostParameters) -> int:
    return int(vehicle.get("max_route_minutes", params.max_route_minutes))


def _has_hard_window(stop: dict[str, object]) -> bool:
    value = stop.get("hard_time_window_flag")
    if isinstance(value, bool):
        return value
    return str(stop.get("customer_priority", "")).lower() in {"strategic", "key"}


def _build_matrices(
    *,
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    depot: dict[str, object],
    stops: list[dict[str, object]],
    node_ids: list[str],
    travel_matrix: Iterable[dict[str, object]] | None,
    params: CostParameters,
) -> tuple[list[list[float]], list[list[int]]]:
    rows = _matrix_rows_for_partition(
        scenario_id=scenario_id,
        depot_id=depot_id,
        delivery_day=delivery_day,
        depot=depot,
        stops=stops,
        travel_matrix=travel_matrix,
        params=params,
    )
    by_arc = {
        (str(row["origin_id"]), str(row["destination_id"])): row
        for row in rows
    }
    distance_matrix: list[list[float]] = []
    duration_matrix: list[list[int]] = []
    coordinates = [
        {"lat": float(depot["lat"]), "lng": float(depot["lng"])},
        *[{"lat": float(stop["lat"]), "lng": float(stop["lng"])} for stop in stops],
    ]
    for origin_idx, origin_id in enumerate(node_ids):
        distance_row: list[float] = []
        duration_row: list[int] = []
        for destination_idx, destination_id in enumerate(node_ids):
            row = by_arc.get((origin_id, destination_id))
            if row is None:
                miles = _road_miles_between(coordinates[origin_idx], coordinates[destination_idx], params)
                minutes = 0 if origin_id == destination_id else drive_minutes(miles, params)
            else:
                miles = float(row["distance_miles"])
                minutes = int(row["duration_minutes"])
            distance_row.append(miles)
            duration_row.append(minutes)
        distance_matrix.append(distance_row)
        duration_matrix.append(duration_row)
    return distance_matrix, duration_matrix


def _matrix_rows_for_partition(
    *,
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    depot: dict[str, object],
    stops: list[dict[str, object]],
    travel_matrix: Iterable[dict[str, object]] | None,
    params: CostParameters,
) -> list[dict[str, object]]:
    if travel_matrix is None:
        _, rows = build_travel_matrix(
            scenario_id=scenario_id,
            depot=depot,
            stops=stops,
            delivery_day=delivery_day,
            params=params,
        )
        return rows
    return [
        row
        for row in travel_matrix
        if row["scenario_id"] == scenario_id
        and row["depot_id"] == depot_id
        and row["delivery_day"] == delivery_day
    ]


def _road_miles_between(
    origin: dict[str, float],
    destination: dict[str, float],
    params: CostParameters,
) -> float:
    return round(
        road_miles(
            haversine_miles(
                origin["lat"],
                origin["lng"],
                destination["lat"],
                destination["lng"],
            ),
            params,
        ),
        3,
    )
