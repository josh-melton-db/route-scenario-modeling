from __future__ import annotations

import math
from itertools import product

from .cost import CostParameters
from .schemas import MATRIX_SOURCE

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    d_lat = lat2 - lat1
    d_lng = math.radians(b_lng - a_lng)
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def road_miles(haversine: float, params: CostParameters | None = None) -> float:
    params = params or CostParameters()
    return haversine * params.circuity


def drive_minutes(distance_miles: float, params: CostParameters | None = None) -> int:
    params = params or CostParameters()
    return max(1, int(round((distance_miles / params.avg_speed_mph) * 60)))


def build_nodes(
    scenario_id: str,
    depot: dict[str, object],
    stops: list[dict[str, object]],
    delivery_day: str,
) -> list[dict[str, object]]:
    nodes = [
        {
            "scenario_id": scenario_id,
            "depot_id": depot["depot_id"],
            "delivery_day": delivery_day,
            "node_id": f"{depot['depot_id']}:DEPOT",
            "node_type": "depot",
            "node_index": 0,
            "lat": float(depot["lat"]),
            "lng": float(depot["lng"]),
        }
    ]
    for idx, stop in enumerate(stops, start=1):
        nodes.append(
            {
                "scenario_id": scenario_id,
                "depot_id": depot["depot_id"],
                "delivery_day": delivery_day,
                "node_id": str(stop["customer_id"]),
                "node_type": "customer",
                "node_index": idx,
                "lat": float(stop["lat"]),
                "lng": float(stop["lng"]),
            }
        )
    return nodes


def build_travel_matrix(
    scenario_id: str,
    depot: dict[str, object],
    stops: list[dict[str, object]],
    delivery_day: str,
    params: CostParameters | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    params = params or CostParameters()
    nodes = build_nodes(scenario_id, depot, stops, delivery_day)
    rows: list[dict[str, object]] = []
    for origin, destination in product(nodes, nodes):
        hav = haversine_miles(
            float(origin["lat"]),
            float(origin["lng"]),
            float(destination["lat"]),
            float(destination["lng"]),
        )
        miles = road_miles(hav, params)
        rows.append(
            {
                "scenario_id": scenario_id,
                "depot_id": depot["depot_id"],
                "delivery_day": delivery_day,
                "origin_id": origin["node_id"],
                "destination_id": destination["node_id"],
                "origin_index": origin["node_index"],
                "destination_index": destination["node_index"],
                "distance_miles": round(miles, 3),
                "duration_minutes": 0 if origin["node_id"] == destination["node_id"] else drive_minutes(miles, params),
                "matrix_source": MATRIX_SOURCE,
                "distance_method": "haversine_circuity",
                "duration_method": "average_speed",
            }
        )
    return nodes, rows


def route_path_distance(
    depot: dict[str, object],
    ordered_stops: list[dict[str, object]],
    params: CostParameters | None = None,
) -> float:
    params = params or CostParameters()
    points = [
        {"lat": float(depot["lat"]), "lng": float(depot["lng"])},
        *ordered_stops,
        {"lat": float(depot["lat"]), "lng": float(depot["lng"])},
    ]
    total = 0.0
    for prev, nxt in zip(points, points[1:]):
        total += road_miles(
            haversine_miles(
                float(prev["lat"]),
                float(prev["lng"]),
                float(nxt["lat"]),
                float(nxt["lng"]),
            ),
            params,
        )
    return round(total, 2)
