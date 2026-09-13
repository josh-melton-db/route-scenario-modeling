from __future__ import annotations

from .baseline import build_route_from_ordered_stops
from .cost import CostParameters


DEFAULT_CHOICES: dict[str, object] = {
    "allow_private_fleet": True,
    "allow_carrier": False,
    "carrier_name": "Great Lakes Logistics",
    "contract_name": "GL-Standard-2026",
    "carrier_capacity_stops": 12,
    "rate_per_mile": 4.25,
    "rate_per_stop": 45.0,
    "minimum_charge": 350.0,
    "fuel_surcharge_pct": 12.0,
}


def resolve_transportation_choices(
    parameters: dict[str, object],
    carriers: list[dict[str, object]],
    contracts: list[dict[str, object]],
) -> dict[str, object]:
    raw = parameters.get("transportation_choices")
    choices = dict(raw) if isinstance(raw, dict) else {}
    carrier_id = str(choices.get("carrier_id", ""))
    contract_id = str(choices.get("contract_id", ""))
    carrier = next((row for row in carriers if str(row.get("carrier_id")) == carrier_id), None)
    contract = next((row for row in contracts if str(row.get("contract_id")) == contract_id), None)
    if not choices.get("allow_carrier"):
        return {**DEFAULT_CHOICES, **choices}
    if carrier is None or contract is None or str(contract.get("carrier_id")) != carrier_id:
        raise ValueError("Selected carrier contract is not available for the selected carrier.")
    if not bool(carrier.get("active", True)) or not bool(contract.get("active", True)):
        raise ValueError("Selected carrier or contract is inactive.")
    return {
        **DEFAULT_CHOICES,
        **choices,
        "carrier_name": carrier["carrier_name"],
        "contract_name": contract["contract_name"],
        "carrier_capacity_stops": contract["capacity_stops"],
        "rate_per_mile": contract["rate_per_mile"],
        "rate_per_stop": contract["rate_per_stop"],
        "minimum_charge": contract["minimum_charge"],
        "fuel_surcharge_pct": contract["fuel_surcharge_pct"],
    }


def apply_operating_constraints(
    fleet: list[dict[str, object]], parameters: dict[str, object]
) -> list[dict[str, object]]:
    choices = parameters.get("transportation_choices")
    if isinstance(choices, dict) and not bool(choices.get("allow_private_fleet", True)):
        return []
    constraints = parameters.get("operating_constraints")
    if not isinstance(constraints, dict):
        return fleet
    limit = max(0, int(constraints.get("private_vehicle_limit", len(fleet))))
    rows = [dict(row) for row in fleet[:limit]]
    for row in rows:
        if constraints.get("max_route_minutes") is not None:
            row["max_route_minutes"] = int(constraints["max_route_minutes"])
        if constraints.get("max_stops_per_route") is not None:
            row["max_stops_per_route"] = int(constraints["max_stops_per_route"])
    return rows


def add_carrier_fallback(
    *,
    solution: dict[str, list[dict[str, object]]],
    scenario_id: str,
    depot: dict[str, object],
    customers: list[dict[str, object]],
    planning_stops: list[dict[str, object]],
    delivery_day: str,
    parameters: dict[str, object],
    cost_parameters: CostParameters,
) -> None:
    raw = parameters.get("transportation_choices")
    choices = {**DEFAULT_CHOICES, **(raw if isinstance(raw, dict) else {})}
    if not bool(choices["allow_carrier"]):
        return
    unassigned = solution["unassigned_stops"]
    capacity = max(0, int(choices["carrier_capacity_stops"]))
    accepted, remaining = unassigned[:capacity], unassigned[capacity:]
    if not accepted:
        return
    stop_by_id = {str(row["customer_id"]): row for row in planning_stops}
    customer_by_id = {
        str(row["customer_id"]): {**row, **stop_by_id.get(str(row["customer_id"]), {})}
        for row in customers
    }
    stops = [customer_by_id[str(row["customer_id"])] for row in accepted]
    max_per_route = 6
    start_number = len(solution["routes"]) + 1
    for offset in range(0, len(stops), max_per_route):
        chunk = stops[offset : offset + max_per_route]
        route_number = start_number + offset // max_per_route
        route, route_stops = build_route_from_ordered_stops(
            scenario_id=scenario_id,
            route_number=route_number,
            depot=depot,
            ordered_stops=chunk,
            delivery_day=delivery_day,
            params=cost_parameters,
            vehicle_id=f"CARRIER-{route_number:03d}",
            driver_id=f"CARRIER-{route_number:03d}",
        )
        linehaul = max(
            float(choices["minimum_charge"]),
            float(route["total_miles"]) * float(choices["rate_per_mile"]),
        )
        stop_cost = len(chunk) * float(choices["rate_per_stop"])
        fuel = linehaul * float(choices["fuel_surcharge_pct"]) / 100
        total = round(linehaul + stop_cost + fuel, 2)
        route.update(
            fulfillment_method="carrier",
            carrier_name=str(choices["carrier_name"]),
            contract_name=str(choices["contract_name"]),
            decision_reason="Private-fleet constraints were exhausted; assigned to eligible carrier capacity.",
            mileage_cost=0.0,
            labor_cost=0.0,
            overtime_cost=0.0,
            fixed_vehicle_cost=0.0,
            sla_penalty_cost=0.0,
            carrier_linehaul_cost=round(linehaul, 2),
            carrier_stop_cost=round(stop_cost, 2),
            fuel_surcharge_cost=round(fuel, 2),
            total_cost=total,
        )
        solution["routes"].append(route)
        solution["route_stops"].extend(route_stops)
    solution["unassigned_stops"] = remaining
    for diagnostic in solution["diagnostics"]:
        diagnostic["dropped_stop_count"] = len(remaining)
        diagnostic["status"] = "succeeded" if not remaining else "infeasible"
        diagnostic["message"] = (
            f"Assigned {len(accepted)} overflow stops to {choices['carrier_name']}; "
            f"{len(remaining)} remain unserved."
        )
