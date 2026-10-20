from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json

from route_opt.baseline import build_route_from_ordered_stops
from route_opt.cost import CostParameters
from route_opt.pricing import revenue_for_cases
from route_opt.rates import contract_status, quote_contract, quote_graduated_contract
from ..models import Route, Stop


def rate_book_content_hash(details: list[dict]) -> str:
    return hashlib.sha256(json.dumps(details, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def depot_delivery_contract_details(contract_details: list[dict], depot_id: str) -> list[dict]:
    details = []
    for original in contract_details:
        detail = deepcopy(original)
        detail["lane_rates"] = [
            lane for lane in detail["lane_rates"]
            if str(lane.get("lane_type", "")).upper() == "DELIVERY"
            and str(lane.get("origin_endpoint_type", "")).lower() == "facility"
            and str(lane.get("origin_endpoint_id") or lane.get("origin")) == depot_id
            and str(lane.get("origin")) == depot_id
        ]
        if detail["lane_rates"]:
            details.append(detail)
    return details


def apply_contracted_overflow(
    solved: dict, *, network_rows: dict, depot_id: str, service_date: str,
    cost_parameters: CostParameters, contract_details: list[dict], enabled: bool,
    snapshot_hash: str | None = None,
    projected_period_volume: float | None = None,
    allow_cost_based_outsourcing: bool = False,
    fleet: list[dict] | None = None,
    travel_matrix: list[dict] | None = None,
) -> None:
    if not enabled:
        return
    if allow_cost_based_outsourcing:
        from .depot_carrier_choice import apply_carrier_choice
        apply_carrier_choice(
            solved, network_rows=network_rows, depot_id=depot_id, service_date=service_date,
            cost_parameters=cost_parameters, contract_details=contract_details,
            snapshot_hash=snapshot_hash, projected_period_volume=projected_period_volume,
            fleet=fleet,
        )
        return
    details_by_contract = {}
    for detail in contract_details:
        if contract_status(detail, service_date) != "published":
            continue
        current = details_by_contract.get(detail["contract_id"])
        if current is None or detail["version"]["version_number"] > current["version"]["version_number"]:
            details_by_contract[detail["contract_id"]] = detail
    details = depot_delivery_contract_details(list(details_by_contract.values()), depot_id)
    depot = next(dict(row) for row in network_rows["dim_facilities"] if row["facility_id"] == depot_id)
    depot["depot_id"] = depot_id
    customers = {row["customer_id"]: row for row in network_rows["dim_network_customers"]}
    groups = defaultdict(list)
    options = {}
    remaining = []
    for order in solved.get("unserved_orders", []):
        customer = customers.get(order["customer_id"])
        if customer is None:
            remaining.append({**order, "reason": "no_contract_rate"})
            continue
        destinations = list(dict.fromkeys(str(value) for value in (
            customer.get("market_id"), customer.get("sales_territory"), customer["customer_id"],
        ) if value))
        candidates = []
        for detail in details:
            eligible = []
            for destination in destinations:
                quote = quote_contract(detail, {
                    "service_date": service_date, "origin": depot_id, "destination": destination,
                    "miles": 0, "stops": 1, "cases": order["demand_cases"],
                })
                if quote["eligible"]:
                    lane = next(lane for lane in detail["lane_rates"] if lane["rule_id"] == quote["matched_lane_rule_id"])
                    endpoint_type = str(lane.get("destination_endpoint_type", "")).lower()
                    endpoint_id = str(lane.get("destination_endpoint_id") or lane.get("destination"))
                    actual = str(customer["customer_id"]) if endpoint_type == "customer" else str(customer.get("market_id") or customer.get("sales_territory") or "")
                    if endpoint_id not in {"*", actual}:
                        continue
                    eligible.append((int(lane.get("priority", 0)), int(lane["destination"] != "*"), destination, quote))
            if eligible:
                selected = max(eligible, key=lambda value: value[:2])
                candidates.append((detail, selected[2], selected[3]["matched_lane_rule_id"]))
        if not candidates:
            remaining.append({**order, "reason": "no_contract_rate"})
            continue
        key = tuple((detail["contract_id"], detail["version"]["version_id"], destination, lane) for detail, destination, lane in candidates)
        options[key] = candidates
        groups[key].append((order, {**customer, **order,
                            "customer_name": customer.get("customer_name") or customer["customer_id"],
                            "receiving_window_start": customer.get("receiving_window_start") or "06:30",
                            "receiving_window_end": customer.get("receiving_window_end") or "18:00",
                            "service_minutes": customer.get("service_minutes") or 20}))
    quotes = []
    matrix = {(row["origin_id"], row["destination_id"]): row for row in travel_matrix or []}
    contracted = []
    versions = set()
    contract_usage = defaultdict(int)
    tier_usage = defaultdict(float)
    for key, stops in groups.items():
        for offset in range(0, len(stops), 6):
            entries = stops[offset:offset + 6]
            chunk_orders = [order for order, _ in entries]
            chunk = [stop for _, stop in entries]
            route, _ = build_route_from_ordered_stops(
                scenario_id="contracted-overflow", route_number=len(quotes) + 1,
                depot=depot, ordered_stops=chunk, delivery_day=service_date, params=cost_parameters,
                vehicle_id="CONTRACTED", driver_id="CONTRACTED",
            )
            nodes = [f"{depot_id}:DEPOT", *[stop["customer_id"] for stop in chunk], f"{depot_id}:DEPOT"]
            arcs = [matrix.get((origin, destination)) for origin, destination in zip(nodes, nodes[1:])]
            mileage_source = "classic_fallback_haversine_circuity"
            if matrix and all(arc is not None for arc in arcs):
                route["total_miles"] = round(sum(float(arc["distance_miles"]) for arc in arcs), 3)
                mileage_source = "solve_matrix"
            accessorials = set()
            for stop in chunk:
                handling = str(stop.get("special_handling", "")).casefold()
                if "liftgate" in handling:
                    accessorials.add("LIFTGATE")
                if "inside" in handling:
                    accessorials.add("INSIDE_DELIVERY")
            candidates = []
            for detail, destination, _ in options[key]:
                pricing_detail = deepcopy(detail)
                commitments = pricing_detail.get("capacity_commitments") or []
                if commitments:
                    commitment = commitments[0]
                    current = float(commitment.get("current_utilization", 0)) + contract_usage[detail["contract_id"]]
                    if current + len(chunk) > float(commitment.get("capacity_quantity", 0)):
                        continue
                    commitment["current_utilization"] = current
                tier_unit = next(iter(detail.get("volume_tiers") or []), {}).get("unit", "stops")
                quote = quote_graduated_contract(pricing_detail, {
                    "service_date": service_date, "origin": depot_id, "destination": destination,
                    "miles": route["total_miles"], "stops": len(chunk),
                    "cases": sum(stop["demand_cases"] for stop in chunk),
                    "period_volume": 0, "accessorial_codes": sorted(accessorials), "commitment_policy": "honor",
                }, projected_period_volume=projected_period_volume,
                    consumed_volume=tier_usage[(detail["contract_id"], tier_unit)])
                if quote["eligible"]:
                    candidates.append(quote)
            if not candidates:
                remaining.extend({**order, "reason": "no_contract_rate"} for order in chunk_orders)
                continue
            quote = min(candidates, key=lambda value: value["total_cost"])
            contract_usage[quote["contract_id"]] += len(chunk)
            tier_unit = quote["tier_breakdown"]["unit"]
            tier_usage[(quote["contract_id"], tier_unit)] += (
                sum(stop["demand_cases"] for stop in chunk) if tier_unit == "cases" else len(chunk)
            )
            quote.update(stops=len(chunk), cases=sum(stop["demand_cases"] for stop in chunk),
                         miles=route["total_miles"], mileage_source=mileage_source)
            quotes.append(quote)
            versions.add((quote["contract_id"], quote["contract_version_id"]))
            for order in chunk_orders:
                contracted.append({
                    **{field: value for field, value in order.items() if field != "reason"},
                    "decision_reason": order.get("decision_reason", "overflow"),
                    **{field: quote[field] for field in ("quote_id", "contract_id", "contract_version_id",
                       "matched_lane", "matched_lane_rule_id", "charge_lines", "rate_book_snapshot_id")},
                })
    solved["contracted_routes"] = []
    for index, quote in enumerate(quotes, start=1):
        orders = [order for order in contracted if order["quote_id"] == quote["quote_id"]]
        stops = [{**customers[order["customer_id"]], **order,
                  "customer_name": customers[order["customer_id"]].get("customer_name") or order["customer_id"],
                  "receiving_window_start": customers[order["customer_id"]].get("receiving_window_start") or "06:30",
                  "receiving_window_end": customers[order["customer_id"]].get("receiving_window_end") or "18:00",
                  "service_minutes": customers[order["customer_id"]].get("service_minutes") or 20}
                 for order in orders]
        route, sequence = build_route_from_ordered_stops(
            scenario_id="contracted-overflow", route_number=index, depot=depot,
            ordered_stops=stops, delivery_day=service_date, params=cost_parameters,
            vehicle_id="CONTRACTED", driver_id="CONTRACTED")
        route.update(
            route_id=f"CONTRACTED-{index:03d}",
            route_name=f"Contracted {index}", fulfillment_method="carrier", total_cost=quote["total_cost"],
            total_miles=quote["miles"],
            contract_version_id=quote["contract_version_id"], carrier_charge_lines=quote["charge_lines"],
            decision_reason=", ".join(sorted({order["decision_reason"] for order in orders})),
            stops=[{**stop, "stop_id": orders[position].get("stop_id") or stop["customer_id"],
                    "location": {"lat": stop["lat"], "lng": stop["lng"]}, "delivery_day": service_date}
                   for position, stop in enumerate(sequence)])
        route = {key: value for key, value in route.items() if key in Route.model_fields}
        route["stops"] = [{key: value for key, value in stop.items() if key in Stop.model_fields}
                          for stop in route["stops"]]
        solved["contracted_routes"].append(route)
    fleet_cost = solved["kpis"]["cost_breakdown"]["total_cost"]
    contracted_cost = round(sum(quote["total_cost"] for quote in quotes), 2)
    contracted_revenue = revenue_for_cases(sum(order["demand_cases"] for order in contracted))
    solved.update(
        fleet_cost=fleet_cost, contracted_cost=contracted_cost, contracted_revenue=contracted_revenue,
        contracted_deliveries=len(contracted), contracted_cases=sum(order["demand_cases"] for order in contracted),
        contracted_orders=contracted, contracted_quotes=quotes, unserved_orders=remaining,
        unserved_cases=sum(order["demand_cases"] for order in remaining),
    )
    cost_categories = {
        "carrier_linehaul_cost": {"lane", "mileage", "minimum"},
        "carrier_lane_cost": {"lane"}, "carrier_stop_cost": {"stops"},
        "carrier_minimum_adjustment": {"minimum"}, "fuel_surcharge_cost": {"fuel"},
        "accessorial_cost": {"accessorial"}, "volume_tier_adjustment": {"volume_tier"},
        "commitment_adjustment": {"commitment"},
    }
    breakdown = solved["kpis"]["cost_breakdown"]
    for field, categories in cost_categories.items():
        breakdown[field] = round(breakdown.get(field, 0) + sum(
            line["amount"] for quote in quotes for line in quote["charge_lines"]
            if line["category"] in categories
        ), 2)
    solved["kpis"]["cost_breakdown"]["total_cost"] = round(fleet_cost + contracted_cost, 2)
    solved["kpis"]["total_revenue"] = round(solved["kpis"].get("total_revenue", 0) + contracted_revenue, 2)
    solved["kpis"]["profit"] = round(
        solved["kpis"]["total_revenue"] - solved["kpis"]["cost_breakdown"]["total_cost"], 2,
    )
    solved.setdefault("execution", {})["contract_versions"] = [
        {"contract_id": contract_id, "version_id": version_id} for contract_id, version_id in sorted(versions)
    ]
    solved["execution"]["contract_snapshots"] = deepcopy([
        detail for detail in details
        if (detail["contract_id"], detail["version"]["version_id"]) in versions
    ])
    solved["execution"]["rate_book_snapshot_hash"] = snapshot_hash or rate_book_content_hash(contract_details)
    solved["execution"]["allow_contracted_overflow"] = True
    for diagnostic in solved.get("diagnostics", []):
        diagnostic.update(
            status="succeeded" if not remaining else "infeasible",
            dropped_stop_count=len(remaining), unserved_cases=solved["unserved_cases"],
            contracted_cases=solved["contracted_cases"], contracted_deliveries=len(contracted),
            message=(f"Assigned {len(contracted)} overflow stops using eligible carrier rate rules; "
                     f"{len(remaining)} remain unserved."),
        )
