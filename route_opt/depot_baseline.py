"""Deterministic depot-level baselines derived from the network planning dataset.

Every depot in the canonical network gets a coherent lower-level analysis
surface: its own customers, sweep-clustered routes, and KPIs computed with the
same cost model used elsewhere in the app. DPT_NORTH keeps its hand-modeled
stub baseline; this module serves the remaining depots.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .cost import route_cost
from .network_synthetic import _road_distance_miles

DELIVERY_DAY = "Tuesday"
MAX_STOPS_PER_ROUTE = 8
CAPACITY_CASES = 720
REVENUE_PER_CASE = 6.25
_TIME_WINDOWS = [
    ("08:00", "12:00"),
    ("10:00", "14:00"),
    ("12:00", "16:00"),
    ("14:00", "18:00"),
]


def _first_tuesday(rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    dates = sorted(
        {
            str(row["service_date"])[:10]
            for row in rows["demand_plan_daily"]
        }
    )
    for value in dates:
        year, month, day = (int(part) for part in value.split("-"))
        if datetime(year, month, day).weekday() == 1:
            return value
    return dates[0]


def _sweep_order(
    depot: Mapping[str, Any], customers: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    def angle(customer: Mapping[str, Any]) -> float:
        return math.atan2(
            float(customer["lat"]) - float(depot["lat"]),
            (float(customer["lng"]) - float(depot["lng"]))
            * math.cos(math.radians(float(depot["lat"]))),
        )

    return sorted(customers, key=lambda row: (angle(row), str(row["customer_id"])))


def _minutes_to_clock(minutes: int) -> str:
    total = 8 * 60 + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


def _drive_minutes(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> int:
    miles = _road_distance_miles(from_lat, from_lng, to_lat, to_lng)
    return max(4, int(round(miles / 30.0 * 60)))


def generate_depot_baseline(
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    depot_id: str,
) -> dict[str, Any]:
    facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
    regions = {str(row["region_id"]): row for row in rows["dim_regions"]}
    depot = facilities.get(depot_id)
    if depot is None or depot["facility_type"] != "depot":
        raise KeyError(f"{depot_id} is not a depot in the canonical network.")

    region_name = str(regions[str(depot["region_id"])]["region_name"])
    service_date = _first_tuesday(rows)
    demand_by_customer = {
        str(row["customer_id"]): int(row["demand_units"])
        for row in rows["demand_plan_daily"]
        if str(row["depot_id"]) == depot_id
        and str(row["service_date"])[:10] == service_date
    }
    customers = [
        row
        for row in rows["dim_network_customers"]
        if str(row["depot_id"]) == depot_id
    ]
    ordered = _sweep_order(depot, customers)

    depot_lat = float(depot["lat"])
    depot_lng = float(depot["lng"])
    routes: list[dict[str, Any]] = []
    for start in range(0, len(ordered), MAX_STOPS_PER_ROUTE):
        chunk = ordered[start : start + MAX_STOPS_PER_ROUTE]
        route_index = len(routes) + 1
        window_start, window_end = _TIME_WINDOWS[(route_index - 1) % len(_TIME_WINDOWS)]

        stops: list[dict[str, Any]] = []
        elapsed = 0
        prev_lat, prev_lng = depot_lat, depot_lng
        for position, customer in enumerate(chunk, start=1):
            cases = max(1, demand_by_customer.get(str(customer["customer_id"]), 40))
            service = min(30, max(15, 15 + round(cases / 12)))
            drive = _drive_minutes(prev_lat, prev_lng, float(customer["lat"]), float(customer["lng"]))
            arrival = elapsed + drive
            departure = arrival + service
            stops.append(
                {
                    "stop_id": f"STP-{route_index:02d}-{position:02d}",
                    "customer_id": str(customer["customer_id"]),
                    "customer_name": str(customer["customer_name"]),
                    "sequence": position,
                    "location": {"lat": float(customer["lat"]), "lng": float(customer["lng"])},
                    "demand_cases": cases,
                    "service_minutes": service,
                    "time_window_start": window_start,
                    "time_window_end": window_end,
                    "arrival_time": _minutes_to_clock(arrival),
                    "departure_time": _minutes_to_clock(departure),
                    "delivery_day": DELIVERY_DAY,
                    "window_risk": "at_risk" if cases > 130 else "none",
                }
            )
            elapsed = departure
            prev_lat, prev_lng = float(customer["lat"]), float(customer["lng"])

        return_drive = _drive_minutes(prev_lat, prev_lng, depot_lat, depot_lng)
        route_minutes = elapsed + return_drive
        miles = 0.0
        path_lat, path_lng = depot_lat, depot_lng
        for stop in stops:
            miles += _road_distance_miles(
                path_lat, path_lng, stop["location"]["lat"], stop["location"]["lng"]
            )
            path_lat, path_lng = stop["location"]["lat"], stop["location"]["lng"]
        miles += _road_distance_miles(path_lat, path_lng, depot_lat, depot_lng)
        total_cases = sum(stop["demand_cases"] for stop in stops)
        cost = route_cost(
            miles=miles,
            route_minutes=route_minutes,
            late_stops=0,
            missed_stops=0,
        )
        routes.append(
            {
                "route_id": f"RTE-{route_index:03d}",
                "scenario_id": "baseline",
                "route_name": f"Route {route_index}",
                "depot_id": depot_id,
                "driver_id": f"DRV-{route_index:03d}",
                "driver_name": f"Driver {route_index}",
                "vehicle_id": f"VEH-{route_index:03d}",
                "delivery_day": DELIVERY_DAY,
                "path": [
                    {"lat": depot_lat, "lng": depot_lng},
                    *[stop["location"] for stop in stops],
                    {"lat": depot_lat, "lng": depot_lng},
                ],
                "stops": stops,
                "total_miles": round(miles, 1),
                "drive_minutes": route_minutes - sum(stop["service_minutes"] for stop in stops),
                "service_minutes": sum(stop["service_minutes"] for stop in stops),
                "total_cases": total_cases,
                "capacity_cases": CAPACITY_CASES,
                "capacity_utilization_pct": round(total_cases / CAPACITY_CASES * 100, 1),
                "driver_utilization_pct": round(min(100.0, route_minutes / 600 * 100), 1),
                "overtime_minutes": cost["overtime_minutes"],
                "missed_windows": 0,
                "late_minutes": 0,
                "total_cost": cost["total_cost"],
            }
        )

    total_miles = sum(route["total_miles"] for route in routes)
    drive_minutes = sum(route["drive_minutes"] for route in routes)
    service_minutes = sum(route["service_minutes"] for route in routes)
    total_cases = sum(route["total_cases"] for route in routes)
    total_cost = sum(route["total_cost"] for route in routes)
    overtime = sum(route["overtime_minutes"] for route in routes)
    stop_count = sum(len(route["stops"]) for route in routes)
    revenue = round(total_cases * REVENUE_PER_CASE, 2)
    breakdown = {
        "mileage_cost": round(sum(route["total_miles"] for route in routes) * 3.0, 2),
        "labor_cost": round(
            sum(route["drive_minutes"] + route["service_minutes"] for route in routes)
            / 60
            * 80.0,
            2,
        ),
        "overtime_cost": round(overtime / 60 * 80.0 * 1.5, 2),
        "fixed_vehicle_cost": round(340.0 * len(routes), 2),
        "sla_penalty_cost": 0.0,
        "total_cost": round(total_cost, 2),
    }

    baseline = {
        "scenario_id": "baseline",
        "depot": {
            "depot_id": depot_id,
            "name": str(depot["facility_name"]),
            "region": region_name,
            "sales_territory": f"{region_name} territory",
            "location": {"lat": depot_lat, "lng": depot_lng},
        },
        "delivery_day": DELIVERY_DAY,
        "routes": routes,
        "matrix_source": "haversine_circuity",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": (
            f"Deterministic sweep baseline over {stop_count} customers served by "
            f"{len(routes)} routes on {DELIVERY_DAY}s."
        ),
    }
    kpis = {
        "route_count": len(routes),
        "driver_count": len(routes),
        "vehicle_count": len(routes),
        "total_miles": round(total_miles, 1),
        "drive_minutes": drive_minutes,
        "service_minutes": service_minutes,
        "total_cases": total_cases,
        "avg_stops_per_route": round(stop_count / len(routes), 1) if routes else 0,
        "avg_capacity_utilization_pct": round(
            sum(route["capacity_utilization_pct"] for route in routes) / len(routes), 1
        )
        if routes
        else 0,
        "avg_driver_utilization_pct": round(
            sum(route["driver_utilization_pct"] for route in routes) / len(routes), 1
        )
        if routes
        else 0,
        "overtime_minutes": overtime,
        "missed_windows": 0,
        "late_minutes": 0,
        "total_revenue": revenue,
        "profit": round(revenue - total_cost, 2),
        "cost_breakdown": breakdown,
    }
    return {"baseline": baseline, "kpis": kpis, "service_date": service_date}
