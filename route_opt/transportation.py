from __future__ import annotations

from collections import Counter
from datetime import date

from .baseline import build_route_from_ordered_stops
from .cost import CostParameters
from .rates import contract_detail_from_legacy, contract_status, quote_contract


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
    rate_contract_details: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    raw = parameters.get("transportation_choices")
    choices = dict(raw) if isinstance(raw, dict) else {}
    carrier_id = str(choices.get("carrier_id", ""))
    contract_id = str(choices.get("contract_id", ""))
    if not choices.get("allow_carrier"):
        return {**DEFAULT_CHOICES, **choices}
    pricing_context = parameters.get("pricing_context")
    pricing = dict(pricing_context) if isinstance(pricing_context, dict) else {}
    service_date = str(pricing.get("service_date") or date.today().isoformat())
    carrier_by_id = {str(row.get("carrier_id")): row for row in carriers}
    selection_mode = str(choices.get("contract_selection", "locked" if contract_id else "automatic"))
    allowed_carrier_ids = {
        str(value)
        for value in choices.get("eligible_carrier_ids", [])
        if value
    }
    if selection_mode == "locked" and carrier_id:
        allowed_carrier_ids.add(carrier_id)
    details_by_contract: dict[str, list[dict[str, object]]] = {}
    for detail in rate_contract_details or []:
        if not isinstance(detail, dict):
            continue
        details_by_contract.setdefault(str(detail.get("contract_id", "")), []).append(detail)
    candidate_contracts: list[dict[str, object]] = []
    for contract in contracts:
        current_contract_id = str(contract.get("contract_id"))
        current_carrier_id = str(contract.get("carrier_id"))
        carrier = carrier_by_id.get(current_carrier_id)
        if carrier is None or not bool(carrier.get("active", True)) or not bool(contract.get("active", True)):
            continue
        if selection_mode == "locked" and contract_id and current_contract_id != contract_id:
            continue
        if allowed_carrier_ids and current_carrier_id not in allowed_carrier_ids:
            continue
        available_details = details_by_contract.get(current_contract_id) or [
            contract_detail_from_legacy(
                contract, str(carrier.get("carrier_name", current_carrier_id))
            )
        ]
        effective_details = [
            detail
            for detail in available_details
            if contract_status(detail, service_date) == "published"
        ]
        if not effective_details:
            continue
        detail = max(
            effective_details,
            key=lambda row: int(
                row.get("version", {}).get("version_number", 0)
                if isinstance(row.get("version"), dict)
                else 0
            ),
        )
        candidate_contracts.append(
            {
                "contract": dict(contract),
                "detail": detail,
                "capacity_stops": int(contract.get("capacity_stops", 0)),
            }
        )
    if not candidate_contracts:
        raise ValueError(
            "No active carrier contract is effective for the selected service date and sourcing policy."
        )
    selected_contract = candidate_contracts[0]["contract"]
    selected_detail = candidate_contracts[0]["detail"]
    if not isinstance(selected_contract, dict) or not isinstance(selected_detail, dict):
        raise ValueError("Selected carrier contract could not be resolved.")
    return {
        **DEFAULT_CHOICES,
        **choices,
        "service_date": service_date,
        "carrier_name": selected_detail["carrier_name"],
        "contract_name": selected_detail["contract_name"],
        "carrier_capacity_stops": selected_contract["capacity_stops"],
        "rate_per_mile": selected_contract["rate_per_mile"],
        "rate_per_stop": selected_contract["rate_per_stop"],
        "minimum_charge": selected_contract["minimum_charge"],
        "fuel_surcharge_pct": selected_contract["fuel_surcharge_pct"],
        "candidate_contracts": candidate_contracts,
    }


def resolve_operating_constraints(
    parameters: dict[str, object], parameter_sets: list[dict[str, object]]
) -> dict[str, object]:
    raw = parameters.get("operating_constraints")
    overrides = dict(raw) if isinstance(raw, dict) else {}
    parameter_set_id = str(overrides.get("parameter_set_id", "default"))
    selected = next(
        (row for row in parameter_sets if str(row.get("parameter_set_id")) == parameter_set_id),
        parameter_sets[0] if parameter_sets else {},
    )
    return {**selected, **overrides, "parameter_set_id": parameter_set_id}


def apply_operating_constraints(
    fleet: list[dict[str, object]], parameters: dict[str, object],
    parameter_sets: list[dict[str, object]] | None = None,
    overtime_threshold_minutes: int = 480,
) -> list[dict[str, object]]:
    choices = parameters.get("transportation_choices")
    if isinstance(choices, dict) and not bool(choices.get("allow_private_fleet", True)):
        return []
    constraints = resolve_operating_constraints(parameters, parameter_sets or [])
    if not constraints:
        return fleet
    limit = max(0, int(constraints.get("private_vehicle_limit", len(fleet))))
    rows = [dict(row) for row in fleet[:limit]]
    for row in rows:
        if constraints.get("max_route_minutes") is not None:
            row["max_route_minutes"] = int(constraints["max_route_minutes"])
        if not bool(constraints.get("allow_overtime", True)):
            row["max_route_minutes"] = min(
                int(row.get("max_route_minutes", overtime_threshold_minutes)),
                overtime_threshold_minutes,
            )
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
    unassigned = list(solution["unassigned_stops"])
    if not unassigned:
        return
    stop_by_id = {str(row["customer_id"]): row for row in planning_stops}
    customer_by_id = {
        str(row["customer_id"]): {**row, **stop_by_id.get(str(row["customer_id"]), {})}
        for row in customers
    }
    stops = [customer_by_id[str(row["customer_id"])] for row in unassigned]
    candidate_contracts = choices.get("candidate_contracts")
    candidates = [row for row in candidate_contracts if isinstance(row, dict)] if isinstance(candidate_contracts, list) else []
    if not candidates:
        fallback_contract = {
            "contract_id": str(choices.get("contract_id", "SCENARIO_RATE")),
            "carrier_id": str(choices.get("carrier_id", "SCENARIO_CARRIER")),
            "contract_name": str(choices.get("contract_name", "Scenario carrier rate")),
            "capacity_stops": int(choices.get("carrier_capacity_stops", len(stops))),
            "rate_per_mile": float(choices.get("rate_per_mile", 0)),
            "rate_per_stop": float(choices.get("rate_per_stop", 0)),
            "minimum_charge": float(choices.get("minimum_charge", 0)),
            "fuel_surcharge_pct": float(choices.get("fuel_surcharge_pct", 0)),
            "effective_start": None,
            "effective_end": None,
        }
        candidates = [
            {
                "contract": fallback_contract,
                "detail": contract_detail_from_legacy(
                    fallback_contract, str(choices.get("carrier_name", "Contracted carrier"))
                ),
                "capacity_stops": int(fallback_contract["capacity_stops"]),
            }
        ]
    candidate_usage = {
        str(row["contract"].get("contract_id")): 0
        for row in candidates
        if isinstance(row.get("contract"), dict)
    }
    pricing_context = parameters.get("pricing_context")
    pricing = pricing_context if isinstance(pricing_context, dict) else {}
    service_date = str(choices.get("service_date") or pricing.get("service_date") or date.today().isoformat())
    projected_period_stops = float(pricing.get("projected_period_stops", 0) or 0)
    explicit_accessorials = [
        str(code)
        for code in choices.get("accessorial_codes", [])
        if code
    ]
    max_per_route = 6
    start_number = len(solution["routes"]) + 1
    assigned_count = 0
    remaining: list[dict[str, object]] = []
    for offset in range(0, len(stops), max_per_route):
        chunk = stops[offset : offset + max_per_route]
        unassigned_chunk = unassigned[offset : offset + max_per_route]
        destination_counts = Counter(
            str(row.get("sales_territory", "")) for row in chunk if row.get("sales_territory")
        )
        destination = destination_counts.most_common(1)[0][0] if destination_counts else str(depot.get("sales_territory", "*"))
        inferred_accessorials = set(explicit_accessorials)
        for row in chunk:
            handling = str(row.get("special_handling", "")).casefold()
            if "liftgate" in handling:
                inferred_accessorials.add("LIFTGATE")
            if "inside" in handling:
                inferred_accessorials.add("INSIDE_DELIVERY")

        priced_candidates: list[tuple[float, dict[str, object], dict[str, object]]] = []
        for candidate in candidates:
            contract = candidate.get("contract")
            detail = candidate.get("detail")
            if not isinstance(contract, dict) or not isinstance(detail, dict):
                continue
            resolved_contract_id = str(contract.get("contract_id"))
            available = int(candidate.get("capacity_stops", 0)) - candidate_usage.get(resolved_contract_id, 0)
            if available < len(chunk):
                continue
            quote = quote_contract(
                detail,
                {
                    "contract_id": resolved_contract_id,
                    "version_id": detail["version"]["version_id"],
                    "service_date": service_date,
                    "origin": str(depot.get("depot_id", "*")),
                    "destination": destination,
                    "miles": 0,
                    "stops": len(chunk),
                    "cases": sum(int(row.get("demand_cases", 0)) for row in chunk),
                    "period_volume": projected_period_stops,
                    "accessorial_codes": sorted(inferred_accessorials),
                    "commitment_policy": choices.get("commitment_policy", "honor"),
                },
            )
            if quote["eligible"]:
                priced_candidates.append((float(quote["total_cost"]), candidate, quote))
        if not priced_candidates:
            remaining.extend(unassigned_chunk)
            continue
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
        # Re-rate with solved road miles, then select the lowest eligible contract.
        final_candidates: list[tuple[float, dict[str, object], dict[str, object]]] = []
        for _, candidate, _ in priced_candidates:
            contract = candidate["contract"]
            detail = candidate["detail"]
            quote = quote_contract(
                detail,
                {
                    "contract_id": contract["contract_id"],
                    "version_id": detail["version"]["version_id"],
                    "service_date": service_date,
                    "origin": str(depot.get("depot_id", "*")),
                    "destination": destination,
                    "miles": float(route["total_miles"]),
                    "stops": len(chunk),
                    "cases": sum(int(row.get("demand_cases", 0)) for row in chunk),
                    "period_volume": projected_period_stops,
                    "accessorial_codes": sorted(inferred_accessorials),
                    "commitment_policy": choices.get("commitment_policy", "honor"),
                },
            )
            if quote["eligible"]:
                final_candidates.append((float(quote["total_cost"]), candidate, quote))
        if not final_candidates:
            remaining.extend(unassigned_chunk)
            continue
        _, selected_candidate, quote = min(final_candidates, key=lambda item: item[0])
        selected_contract = selected_candidate["contract"]
        selected_detail = selected_candidate["detail"]
        resolved_contract_id = str(selected_contract["contract_id"])
        candidate_usage[resolved_contract_id] = candidate_usage.get(resolved_contract_id, 0) + len(chunk)
        charge_lines = quote["charge_lines"]

        def charge_total(*categories: str) -> float:
            return round(
                sum(
                    float(line["amount"])
                    for line in charge_lines
                    if str(line["category"]) in categories
                ),
                2,
            )

        lane_cost = charge_total("lane")
        mileage_cost = charge_total("mileage")
        minimum_adjustment = charge_total("minimum")
        linehaul = round(lane_cost + mileage_cost + minimum_adjustment, 2)
        stop_cost = charge_total("stops")
        fuel = charge_total("fuel")
        accessorial = charge_total("accessorial")
        volume_adjustment = charge_total("volume_tier")
        commitment_adjustment = charge_total("commitment")
        total = float(quote["total_cost"])
        route.update(
            fulfillment_method="carrier",
            carrier_name=str(selected_detail["carrier_name"]),
            contract_name=str(selected_detail["contract_name"]),
            contract_version_id=str(quote["contract_version_id"]),
            rated_service_date=service_date,
            rate_lane=str(quote["matched_lane"]),
            rate_book_snapshot_id=str(quote["rate_book_snapshot_id"]),
            carrier_charge_lines=charge_lines,
            decision_reason="Private-fleet capacity was exhausted; selected the lowest eligible published carrier quote.",
            mileage_cost=0.0,
            labor_cost=0.0,
            overtime_cost=0.0,
            fixed_vehicle_cost=0.0,
            sla_penalty_cost=0.0,
            carrier_linehaul_cost=round(linehaul, 2),
            carrier_lane_cost=lane_cost,
            carrier_stop_cost=round(stop_cost, 2),
            carrier_minimum_adjustment=minimum_adjustment,
            fuel_surcharge_cost=round(fuel, 2),
            accessorial_cost=accessorial,
            volume_tier_adjustment=volume_adjustment,
            commitment_adjustment=commitment_adjustment,
            total_cost=total,
        )
        solution["routes"].append(route)
        solution["route_stops"].extend(route_stops)
        assigned_count += len(chunk)
    solution["unassigned_stops"] = remaining
    for diagnostic in solution["diagnostics"]:
        diagnostic["dropped_stop_count"] = len(remaining)
        diagnostic["status"] = "succeeded" if not remaining else "infeasible"
        diagnostic["message"] = (
            f"Assigned {assigned_count} overflow stops using eligible carrier rate rules; "
            f"{len(remaining)} remain unserved."
        )
