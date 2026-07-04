from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import mean

from .config import DEFAULT_GENERATED_AT
from .cost import CostParameters, route_cost
from .matrix import drive_minutes, haversine_miles, road_miles, route_path_distance
from .schemas import BASELINE_SCENARIO_ID, MATRIX_SOURCE, stable_id


def _minutes_to_hhmm(minutes: int) -> str:
    start = datetime(2026, 7, 7, 0, 0)
    return (start + timedelta(minutes=minutes)).strftime("%H:%M")


def _hhmm_to_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _angle(depot: dict[str, object], stop: dict[str, object]) -> float:
    return math.atan2(float(stop["lat"]) - float(depot["lat"]), float(stop["lng"]) - float(depot["lng"]))


def _select_vehicle_count(fleet: list[dict[str, object]], depot_id: str, delivery_day: str) -> int:
    vehicles = [
        row
        for row in fleet
        if row["depot_id"] == depot_id and delivery_day in str(row["available_days"]).split(",")
    ]
    return max(1, min(6, len(vehicles)))


def _join_delivery_stops(
    customers: list[dict[str, object]],
    orders: list[dict[str, object]],
    depot_id: str,
    delivery_day: str,
) -> list[dict[str, object]]:
    by_customer = {row["customer_id"]: row for row in customers}
    stops: list[dict[str, object]] = []
    for order in orders:
        if order["depot_id"] != depot_id or order["delivery_day"] != delivery_day:
            continue
        customer = by_customer[order["customer_id"]]
        stops.append(
            {
                **customer,
                "demand_cases": int(order["demand_cases"]),
                "delivery_day": delivery_day,
                "route_date": order["route_date"],
            }
        )
    return stops


def build_route_from_ordered_stops(
    *,
    scenario_id: str,
    route_number: int,
    depot: dict[str, object],
    ordered_stops: list[dict[str, object]],
    delivery_day: str,
    params: CostParameters,
    vehicle_id: str,
    driver_id: str,
    capacity_cases: int = 1000,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    route_id = stable_id("RTE", route_number)
    sequence_rows: list[dict[str, object]] = []
    path = [{"lat": float(depot["lat"]), "lng": float(depot["lng"])}]
    elapsed = 390  # 06:30
    drive_total = 0
    service_total = 0
    late_minutes = 0
    missed_windows = 0
    prev = {"lat": float(depot["lat"]), "lng": float(depot["lng"])}
    for sequence, stop in enumerate(ordered_stops, start=1):
        leg_miles = road_miles(
            haversine_miles(
                float(prev["lat"]),
                float(prev["lng"]),
                float(stop["lat"]),
                float(stop["lng"]),
            ),
            params,
        )
        leg_minutes = drive_minutes(leg_miles, params)
        drive_total += leg_minutes
        arrival = elapsed + leg_minutes
        window_open = _hhmm_to_minutes(str(stop["receiving_window_start"]))
        window_close = _hhmm_to_minutes(str(stop["receiving_window_end"]))
        if arrival < window_open:
            arrival = window_open
        service_minutes = int(stop["service_minutes"])
        departure = arrival + service_minutes
        service_total += service_minutes
        late = max(0, arrival - window_close)
        late_minutes += late
        if late > 0:
            missed_windows += 1
        sequence_rows.append(
            {
                "route_id": route_id,
                "scenario_id": scenario_id,
                "depot_id": depot["depot_id"],
                "delivery_day": delivery_day,
                "customer_id": stop["customer_id"],
                "customer_name": stop["customer_name"],
                "sequence": sequence,
                "lat": float(stop["lat"]),
                "lng": float(stop["lng"]),
                "demand_cases": int(stop["demand_cases"]),
                "service_minutes": service_minutes,
                "time_window_start": stop["receiving_window_start"],
                "time_window_end": stop["receiving_window_end"],
                "arrival_time": _minutes_to_hhmm(arrival),
                "departure_time": _minutes_to_hhmm(departure),
                "window_risk": "missed" if late > 0 else "none",
                "is_new_customer": bool(stop.get("is_new_customer", False)),
                "late_minutes": late,
            }
        )
        path.append({"lat": float(stop["lat"]), "lng": float(stop["lng"])})
        prev = stop
        elapsed = departure
    return_leg_miles = road_miles(
        haversine_miles(
            float(prev["lat"]),
            float(prev["lng"]),
            float(depot["lat"]),
            float(depot["lng"]),
        ),
        params,
    )
    return_minutes = drive_minutes(return_leg_miles, params)
    drive_total += return_minutes
    total_miles = route_path_distance(depot, ordered_stops, params)
    route_minutes = drive_total + service_total
    costs = route_cost(
        miles=total_miles,
        route_minutes=route_minutes,
        late_stops=missed_windows,
        params=params,
    )
    total_cases = sum(int(stop["demand_cases"]) for stop in ordered_stops)
    path.append({"lat": float(depot["lat"]), "lng": float(depot["lng"])})
    route = {
        "route_id": route_id,
        "scenario_id": scenario_id,
        "route_name": f"Route {route_number}",
        "depot_id": depot["depot_id"],
        "driver_id": driver_id,
        "driver_name": driver_id.replace("DRV-", "Driver "),
        "vehicle_id": vehicle_id,
        "delivery_day": delivery_day,
        "path": path,
        "total_miles": total_miles,
        "drive_minutes": drive_total,
        "service_minutes": service_total,
        "total_cases": total_cases,
        "capacity_cases": capacity_cases,
        "capacity_utilization_pct": round(100 * total_cases / capacity_cases, 1),
        "driver_utilization_pct": min(
            100.0,
            round(
                100 * max(route_minutes, 360) / params.overtime_threshold_minutes,
                1,
            ),
        ),
        "overtime_minutes": int(costs["overtime_minutes"]),
        "missed_windows": missed_windows,
        "late_minutes": late_minutes,
        "stop_count": len(sequence_rows),
        "total_cost": float(costs["total_cost"]),
        **{key: value for key, value in costs.items() if key.endswith("_cost")},
    }
    return route, sequence_rows


def _build_route(
    *,
    scenario_id: str,
    route_number: int,
    depot: dict[str, object],
    stops: list[dict[str, object]],
    delivery_day: str,
    params: CostParameters,
    vehicle_id: str,
    driver_id: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    return build_route_from_ordered_stops(
        scenario_id=scenario_id,
        route_number=route_number,
        depot=depot,
        ordered_stops=sorted(stops, key=lambda stop: _angle(depot, stop)),
        delivery_day=delivery_day,
        params=params,
        vehicle_id=vehicle_id,
        driver_id=driver_id,
    )


def summarize_kpis(routes: list[dict[str, object]]) -> dict[str, object]:
    if not routes:
        return {
            "route_count": 0,
            "driver_count": 0,
            "vehicle_count": 0,
            "total_miles": 0.0,
            "drive_minutes": 0,
            "service_minutes": 0,
            "total_cases": 0,
            "avg_stops_per_route": 0.0,
            "avg_capacity_utilization_pct": 0.0,
            "avg_driver_utilization_pct": 0.0,
            "overtime_minutes": 0,
            "missed_windows": 0,
            "late_minutes": 0,
            "cost_breakdown": {
                "mileage_cost": 0.0,
                "labor_cost": 0.0,
                "overtime_cost": 0.0,
                "fixed_vehicle_cost": 0.0,
                "sla_penalty_cost": 0.0,
                "total_cost": 0.0,
            },
        }
    cost_keys = [
        "mileage_cost",
        "labor_cost",
        "overtime_cost",
        "fixed_vehicle_cost",
        "sla_penalty_cost",
        "total_cost",
    ]
    route_count = len(routes)
    return {
        "route_count": route_count,
        "driver_count": len({row["driver_id"] for row in routes}),
        "vehicle_count": len({row["vehicle_id"] for row in routes}),
        "total_miles": round(sum(float(row["total_miles"]) for row in routes), 1),
        "drive_minutes": sum(int(row["drive_minutes"]) for row in routes),
        "service_minutes": sum(int(row["service_minutes"]) for row in routes),
        "total_cases": sum(int(row["total_cases"]) for row in routes),
        "avg_stops_per_route": round(mean(int(row["stop_count"]) for row in routes), 1),
        "avg_capacity_utilization_pct": round(mean(float(row["capacity_utilization_pct"]) for row in routes), 1),
        "avg_driver_utilization_pct": round(mean(float(row["driver_utilization_pct"]) for row in routes), 1),
        "overtime_minutes": sum(int(row["overtime_minutes"]) for row in routes),
        "missed_windows": sum(int(row["missed_windows"]) for row in routes),
        "late_minutes": sum(int(row["late_minutes"]) for row in routes),
        "cost_breakdown": {
            key: round(sum(float(row.get(key, 0)) for row in routes), 2)
            for key in cost_keys
        },
    }


def reconstruct_baseline(
    depots: list[dict[str, object]],
    customers: list[dict[str, object]],
    orders: list[dict[str, object]],
    fleet: list[dict[str, object]],
    depot_id: str = "DPT_NORTH",
    delivery_day: str = "Tuesday",
    params: CostParameters | None = None,
    scenario_id: str = BASELINE_SCENARIO_ID,
) -> dict[str, object]:
    params = params or CostParameters()
    depot = next(row for row in depots if row["depot_id"] == depot_id)
    stops = _join_delivery_stops(customers, orders, depot_id, delivery_day)
    stops = sorted(stops, key=lambda stop: _angle(depot, stop))
    vehicle_count = min(_select_vehicle_count(fleet, depot_id, delivery_day), max(1, math.ceil(len(stops) / 6)))
    chunk_size = max(1, math.ceil(len(stops) / vehicle_count))
    routes: list[dict[str, object]] = []
    route_stops: list[dict[str, object]] = []
    for route_number, start in enumerate(range(0, len(stops), chunk_size), start=1):
        chunk = stops[start : start + chunk_size]
        route, sequence_rows = _build_route(
            scenario_id=scenario_id,
            route_number=route_number,
            depot=depot,
            stops=chunk,
            delivery_day=delivery_day,
            params=params,
            vehicle_id=stable_id("VEH", route_number),
            driver_id=stable_id("DRV", route_number),
        )
        routes.append(route)
        route_stops.extend(sequence_rows)
    kpis = summarize_kpis(routes)
    return {
        "network": {
            "scenario_id": "baseline",
            "depot": {
                "depot_id": depot["depot_id"],
                "name": depot["depot_name"],
                "region": depot["region"],
                "sales_territory": depot["sales_territory"],
                "location": {"lat": depot["lat"], "lng": depot["lng"]},
            },
            "delivery_day": delivery_day,
            "routes": [_route_contract(route, route_stops) for route in routes],
            "matrix_source": MATRIX_SOURCE,
            "generated_at": DEFAULT_GENERATED_AT,
            "summary": f"Reconstructed {len(routes)} baseline routes for {depot['depot_name']} on {delivery_day}.",
        },
        "routes": routes,
        "route_stops": route_stops,
        "kpis": kpis,
    }


def _route_contract(route: dict[str, object], all_stops: list[dict[str, object]]) -> dict[str, object]:
    stops = [stop for stop in all_stops if stop["route_id"] == route["route_id"]]
    return {
        "route_id": route["route_id"],
        "scenario_id": route["scenario_id"],
        "route_name": route["route_name"],
        "depot_id": route["depot_id"],
        "driver_id": route["driver_id"],
        "driver_name": route["driver_name"],
        "vehicle_id": route["vehicle_id"],
        "delivery_day": route["delivery_day"],
        "path": route["path"],
        "stops": [
            {
                "stop_id": f"{stop['route_id']}-{stop['sequence']}",
                "customer_id": stop["customer_id"],
                "customer_name": stop["customer_name"],
                "sequence": stop["sequence"],
                "location": {"lat": stop["lat"], "lng": stop["lng"]},
                "demand_cases": stop["demand_cases"],
                "service_minutes": stop["service_minutes"],
                "time_window_start": stop["time_window_start"],
                "time_window_end": stop["time_window_end"],
                "arrival_time": stop["arrival_time"],
                "departure_time": stop["departure_time"],
                "delivery_day": stop["delivery_day"],
                "window_risk": stop["window_risk"],
                "is_new_customer": stop["is_new_customer"],
            }
            for stop in stops
        ],
        "total_miles": route["total_miles"],
        "drive_minutes": route["drive_minutes"],
        "service_minutes": route["service_minutes"],
        "total_cases": route["total_cases"],
        "capacity_cases": route["capacity_cases"],
        "capacity_utilization_pct": route["capacity_utilization_pct"],
        "driver_utilization_pct": route["driver_utilization_pct"],
        "overtime_minutes": route["overtime_minutes"],
        "missed_windows": route["missed_windows"],
        "late_minutes": route["late_minutes"],
        "total_cost": route["total_cost"],
    }
