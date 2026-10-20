from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from route_opt.baseline import build_route_from_ordered_stops
from route_opt.cost import CostParameters, route_cost
from route_opt.pricing import revenue_for_cases
from route_opt.matrix import drive_minutes, haversine_miles, road_miles
from ..models import Route, Stop


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _rebuild(original: dict, stops: list[dict], *, depot: dict, service_date: str,
             cost_parameters: CostParameters, matrix: dict) -> dict:
    ordered = [{**stop, **stop["location"], "receiving_window_start": stop["time_window_start"],
                "receiving_window_end": stop["time_window_end"]} for stop in stops]
    route, sequence = build_route_from_ordered_stops(
        scenario_id=original["scenario_id"], route_number=1, depot=depot,
        ordered_stops=ordered, delivery_day=service_date, params=cost_parameters,
        vehicle_id=original["vehicle_id"], driver_id=original["driver_id"],
        capacity_cases=original["capacity_cases"])
    nodes = [f'{depot["depot_id"]}:DEPOT', *[stop["customer_id"] for stop in stops], f'{depot["depot_id"]}:DEPOT']
    arcs = [matrix.get((origin, destination)) for origin, destination in zip(nodes, nodes[1:])]
    if matrix and all(arc is not None for arc in arcs):
        elapsed = 390
        waiting = 0
        missed = 0
        late = 0
        for stop, arc in zip(sequence, arcs):
            arrival = elapsed + int(arc["duration_minutes"])
            waiting += max(0, _minutes(stop["time_window_start"]) - arrival)
            arrival = max(arrival, _minutes(stop["time_window_start"]))
            delay = max(0, arrival - _minutes(stop["time_window_end"]))
            missed += int(delay > 0)
            late += delay
            elapsed = arrival + stop["service_minutes"]
            stop.update(arrival_time=f"{arrival // 60:02d}:{arrival % 60:02d}",
                        departure_time=f"{elapsed // 60:02d}:{elapsed % 60:02d}",
                        window_risk="missed" if delay else "none")
        route.update(total_miles=round(sum(float(arc["distance_miles"]) for arc in arcs), 2),
                     drive_minutes=sum(int(arc["duration_minutes"]) for arc in arcs),
                     waiting_minutes=waiting, missed_windows=missed, late_minutes=late)
    else:
        return_minutes = drive_minutes(road_miles(haversine_miles(
            float(stops[-1]["location"]["lat"]), float(stops[-1]["location"]["lng"]),
            float(depot["lat"]), float(depot["lng"])), cost_parameters), cost_parameters) if stops else 0
        route["waiting_minutes"] = max(0, _minutes(sequence[-1]["departure_time"]) - 390 -
                                       route["service_minutes"] - route["drive_minutes"] + return_minutes) if sequence else 0
    if not stops:
        route.update(total_miles=0, drive_minutes=0, service_minutes=0, waiting_minutes=0)
    route["route_minutes"] = route["drive_minutes"] + route["service_minutes"] + route["waiting_minutes"]
    route["driver_utilization_pct"] = min(100, round(100 * max(route["route_minutes"], 360) /
                                                   cost_parameters.overtime_threshold_minutes, 1))
    costs = route_cost(miles=route["total_miles"], route_minutes=route["route_minutes"],
                       late_stops=route["missed_windows"], params=cost_parameters)
    route.update(costs)
    route.update(route_id=original["route_id"], route_name=original["route_name"],
                 driver_name=original["driver_name"],
                 stops=[{**stop, **{key: value for key, value in sequence[index].items()
                                   if key in {"sequence", "arrival_time", "departure_time", "window_risk"}}}
                        for index, stop in enumerate(stops)])
    return route


def apply_carrier_choice(solved: dict, **arguments) -> None:
    from .depot_contracted_overflow import apply_contracted_overflow

    source = deepcopy(solved)
    matrix_rows = source.pop("_cost_based_matrix", [])
    matrix = {(row["origin_id"], row["destination_id"]): row for row in matrix_rows}
    fleet = {vehicle["vehicle_id"]: vehicle for vehicle in arguments.pop("fleet", None) or []}
    solved.pop("_cost_based_matrix", None)
    depot = next(dict(row) for row in arguments["network_rows"]["dim_facilities"]
                 if row["facility_id"] == arguments["depot_id"])
    depot["depot_id"] = arguments["depot_id"]
    rebuild_arguments = dict(depot=depot, service_date=arguments["service_date"],
                             cost_parameters=arguments["cost_parameters"], matrix=matrix)
    best = deepcopy(source)
    apply_contracted_overflow(best, **arguments, enabled=True)
    arguments["travel_matrix"] = matrix_rows
    initial_cost = best["kpis"]["cost_breakdown"]["total_cost"]
    initial_revenue = best["kpis"].get("total_revenue", 0)
    required_contracts = {order["customer_id"] for order in best["contracted_orders"]}
    chosen = []
    while True:
        accepted = False
        marginal = []
        before_routes = {}
        mileage_calibration = {}
        for route_index, original in enumerate(best["routes"]):
            if not original["stops"]:
                continue
            before = _rebuild(original, original["stops"], **rebuild_arguments)
            before_routes[route_index] = before
            mileage_calibration[route_index] = round(original["total_cost"] - before["total_cost"], 2)
            for stop_index, stop in enumerate(original["stops"]):
                retained = original["stops"][:stop_index] + original["stops"][stop_index + 1:]
                after = _rebuild(original, retained, **rebuild_arguments)
                if (after["missed_windows"] or after["route_minutes"] > arguments["cost_parameters"].max_route_minutes
                        or after["total_cases"] > after["capacity_cases"]):
                    continue
                saving = round(before["total_cost"] - after["total_cost"], 2)
                if saving >= 0:
                    marginal.append((-saving, route_index, stop_index))
        ranked = [(route_index, stop_index) for _, route_index, stop_index in sorted(marginal)]
        groups = {(entry,) for entry in ranked}
        rankings = [ranked, *[[entry for entry in ranked if entry[0] == route_index]
                             for route_index in before_routes]]
        for ranking in rankings:
            for size in range(2, min(6, len(ranking)) + 1):
                groups.add(tuple(sorted(ranking[:size])))
        candidates = []
        for group in sorted(groups):
            replacements = {}
            saving = 0
            for route_index in sorted({entry[0] for entry in group}):
                original = best["routes"][route_index]
                removed = {stop_index for index, stop_index in group if index == route_index}
                after = _rebuild(original, [stop for index, stop in enumerate(original["stops"])
                                            if index not in removed], **rebuild_arguments)
                vehicle_limit = int(fleet.get(original["vehicle_id"], {}).get("max_route_minutes")
                                    or arguments["cost_parameters"].max_route_minutes)
                if (after["missed_windows"] or after["route_minutes"] > min(vehicle_limit, arguments["cost_parameters"].max_route_minutes)
                        or after["total_cases"] > after["capacity_cases"]):
                    break
                after["mileage_cost"] = round(max(0, after["mileage_cost"] + mileage_calibration[route_index]), 2)
                after["total_cost"] = round(sum(after[field] for field in (
                    "mileage_cost", "labor_cost", "overtime_cost", "fixed_vehicle_cost", "sla_penalty_cost")), 2)
                route_saving = round(original["total_cost"] - after["total_cost"], 2)
                if before_routes[route_index]["mileage_cost"] + mileage_calibration[route_index] < 0:
                    break
                replacements[route_index] = after
                saving += route_saving
            else:
                if saving > 0:
                    candidates.append((-round(saving, 2), group, replacements))
        for _, group, replacements in sorted(candidates, key=lambda item: item[:2]):
            trial = deepcopy(source)
            trial["routes"] = deepcopy(best["routes"])
            for route_index, after in replacements.items():
                trial["routes"][route_index] = deepcopy(after)
            moved = [*chosen, *[{**best["routes"][route_index]["stops"][stop_index],
                                 "decision_reason": "outsourced_by_cost"}
                                for route_index, stop_index in group]]
            trial["unserved_orders"] = [*source["unserved_orders"], *moved]
            trial["routed_cases"] = source["routed_cases"] - sum(order["demand_cases"] for order in moved)
            trial["kpis"] = deepcopy(source["kpis"])
            breakdown = trial["kpis"]["cost_breakdown"]
            breakdown["total_cost"] = round(sum(route["total_cost"] for route in trial["routes"]), 2)
            for field in ("mileage_cost", "labor_cost", "overtime_cost", "fixed_vehicle_cost", "sla_penalty_cost"):
                delta = sum(after[field] - before_routes[route_index][field]
                            - (mileage_calibration[route_index] if field == "mileage_cost" else 0)
                            for route_index, after in replacements.items())
                breakdown[field] = round(best["kpis"]["cost_breakdown"].get(field, 0) + delta, 2)
            trial["kpis"]["total_revenue"] = round(source["kpis"].get("total_revenue", 0) -
                                                        revenue_for_cases(sum(order["demand_cases"] for order in moved)), 2)
            apply_contracted_overflow(trial, **arguments, enabled=True)
            contracted = {order["customer_id"] for order in trial["contracted_orders"]}
            if not required_contracts.issubset(contracted) or not all(order["customer_id"] in contracted for order in moved):
                continue
            if trial["kpis"].get("total_revenue", 0) != initial_revenue:
                continue
            if trial["kpis"]["cost_breakdown"]["total_cost"] >= best["kpis"]["cost_breakdown"]["total_cost"]:
                continue
            chosen, best, accepted = moved, trial, True
            break
        if not accepted:
            break
    for quote_index, quote in enumerate(best["contracted_quotes"]):
        old_id = quote["quote_id"]
        payload = {key: value for key, value in quote.items() if key != "quote_id"}
        payload["chunk_index"] = quote_index
        quote["quote_id"] = "quote_" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
        for order in best["contracted_orders"]:
            if order["quote_id"] == old_id:
                order["quote_id"] = quote["quote_id"]
    for route in best["routes"] if chosen else []:
        for key in list(route):
            if key not in Route.model_fields:
                del route[key]
        route["stops"] = [{key: value for key, value in stop.items() if key in Stop.model_fields}
                          for stop in route["stops"]]
    for field in ("total_miles", "drive_minutes", "service_minutes", "waiting_minutes", "overtime_minutes",
                  "missed_windows", "late_minutes"):
        if chosen:
            best["kpis"][field] = round(sum(route.get(field, 0) for route in best["routes"]), 3)
    if chosen:
        best["kpis"]["total_cases"] = best["routed_cases"]
        best["kpis"]["avg_stops_per_route"] = round(sum(len(route["stops"]) for route in best["routes"]) / max(1, len(best["routes"])), 1)
        for field in ("capacity_utilization_pct", "driver_utilization_pct"):
            best["kpis"][f"avg_{field}"] = round(sum(route[field] for route in best["routes"]) / max(1, len(best["routes"])), 1)
    best.update(outsourced_by_cost_deliveries=len(chosen),
                outsourcing_savings=round(initial_cost - best["kpis"]["cost_breakdown"]["total_cost"], 2))
    best["execution"].update(allow_cost_based_outsourcing=True,
                             outsourcing_mileage_basis="solve_matrix" if matrix else "haversine_circuity_marginal_estimate",
                             outsourcing_fixed_cost_policy="Retain vehicle fixed cost and guaranteed shift labor, including empty routes.")
    solved.clear()
    solved.update(best)
