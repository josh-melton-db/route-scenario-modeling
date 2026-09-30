from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from ortools.graph.python import min_cost_flow


_EXTERNAL_DCS_BY_FOCUS_REGION: dict[str, frozenset[str]] = {
    "REGION_TOLA": frozenset({"DC_MEXICO_MONTERREY"}),
}


def _date_text(value: object) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)[:10]


def _in_horizon(value: object, start: str, end: str) -> bool:
    service_date = _date_text(value)
    return start <= service_date <= end


def _proportional_allocations(
    rows: Sequence[Mapping[str, Any]],
    assigned_total: int,
) -> dict[str, int]:
    """Allocate an integer depot total to customers without inventing demand."""

    if not rows or assigned_total <= 0:
        return {str(row["customer_id"]): 0 for row in rows}
    demand_total = sum(int(row["demand_units"]) for row in rows)
    if assigned_total >= demand_total:
        return {str(row["customer_id"]): int(row["demand_units"]) for row in rows}

    allocations: dict[str, int] = {}
    residuals: list[tuple[int, str]] = []
    allocated = 0
    for row in rows:
        customer_id = str(row["customer_id"])
        numerator = assigned_total * int(row["demand_units"])
        value = numerator // demand_total
        allocations[customer_id] = value
        allocated += value
        residuals.append((numerator % demand_total, customer_id))
    for _, customer_id in sorted(residuals, reverse=True)[: assigned_total - allocated]:
        allocations[customer_id] += 1
    return allocations


def solve_fixed_capacity_network(
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    demand_plan_version_id: str,
    capacity_plan_version_id: str,
    horizon_start: str,
    horizon_end: str,
    region_id: str,
    disabled_facility_ids: set[str] | None = None,
    disabled_lane_ids: set[str] | None = None,
    lane_cost_adjustments_pct: Mapping[str, float] | None = None,
    lane_unit_costs: Mapping[str, float] | None = None,
    tariff_per_case_by_date_lane: Mapping[tuple[str, str], float] | None = None,
    unmet_penalty_per_case: float = 250.0,
    release_requests: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Assign fixed demand through fixed supplied capacity.

    The solver can leave demand unmet at the configured penalty, but it never
    creates facility or lane capacity. Distribution-center and depot capacity,
    disabled nodes, disabled lanes, and direct DC-to-depot lane capacities are
    all hard bounds.
    """

    selected_parent_assignments = [
        row
        for row in rows.get("network_customer_assignments_daily", [])
        if str(row.get("demand_plan_version_id")) == demand_plan_version_id
        and str(row.get("capacity_plan_version_id")) == capacity_plan_version_id
        and _in_horizon(row.get("service_date"), horizon_start, horizon_end)
    ]
    if release_requests or selected_parent_assignments:
        return _solve_with_reassignment(
            rows,
            demand_plan_version_id=demand_plan_version_id,
            capacity_plan_version_id=capacity_plan_version_id,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            region_id=region_id,
            release_requests=release_requests or [],
            disabled_facility_ids=disabled_facility_ids or set(),
            disabled_lane_ids=disabled_lane_ids or set(),
            lane_cost_adjustments_pct=lane_cost_adjustments_pct or {},
            lane_unit_costs=lane_unit_costs or {},
            tariff_per_case_by_date_lane=tariff_per_case_by_date_lane or {},
            unmet_penalty_per_case=unmet_penalty_per_case,
        )
    disabled_facilities = disabled_facility_ids or set()
    disabled_lanes = disabled_lane_ids or set()
    cost_adjustments = lane_cost_adjustments_pct or {}
    unit_costs = lane_unit_costs or {}
    tariffs = tariff_per_case_by_date_lane or {}
    if any(float(amount) < 0 for amount in tariffs.values()):
        raise ValueError("Tariff amounts must be nonnegative.")

    facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
    lanes = {str(row["lane_id"]): row for row in rows["dim_network_lanes"]}
    focus_depots = {
        facility_id
        for facility_id, facility in facilities.items()
        if facility["facility_type"] == "depot"
        and (region_id == "ALL" or str(facility["region_id"]) == region_id)
    }
    regional_dcs = {
        facility_id
        for facility_id, facility in facilities.items()
        if facility["facility_type"] == "distribution_center"
        and (region_id == "ALL" or str(facility["region_id"]) == region_id)
    }

    # A regional focus selects demand, not an independent claim on capacity.
    # Include cross-border sources that can serve the focus, then include all
    # external demand already assigned to those DCs in the published plan.
    participating_dcs = set(regional_dcs)
    if region_id == "ALL":
        participating_dcs.update(
            facility_id
            for facility_id, facility in facilities.items()
            if facility["facility_type"] == "distribution_center"
        )
    else:
        permitted_external_dcs = _EXTERNAL_DCS_BY_FOCUS_REGION.get(
            region_id, frozenset()
        )
        for lane in lanes.values():
            origin_id = str(lane["origin_endpoint_id"])
            if (
                str(lane["lane_type"]) == "LINEHAUL"
                and str(lane["destination_endpoint_id"]) in focus_depots
                and origin_id in permitted_external_dcs
            ):
                participating_dcs.add(origin_id)

    demand_rows = [
        row
        for row in rows["demand_plan_daily"]
        if str(row["demand_plan_version_id"]) == demand_plan_version_id
        and _in_horizon(row["service_date"], horizon_start, horizon_end)
    ]
    demand_by_date_depot: defaultdict[tuple[str, str], int] = defaultdict(int)
    demand_by_date_depot_customers: defaultdict[
        tuple[str, str], list[Mapping[str, Any]]
    ] = defaultdict(list)
    for row in demand_rows:
        service_date = _date_text(row["service_date"])
        depot_id = str(row["depot_id"])
        demand_by_date_depot[(service_date, depot_id)] += int(row["demand_units"])
        demand_by_date_depot_customers[(service_date, depot_id)].append(row)

    scoped_depots = set(focus_depots)
    scoped_depots.update(
        str(row["depot_id"])
        for row in demand_rows
        if str(row["distribution_center_id"]) in participating_dcs
    )
    scoped_dcs = participating_dcs

    facility_capacity = {
        (_date_text(row["service_date"]), str(row["facility_id"])): int(
            row["capacity_units"]
        )
        for row in rows["facility_capacity_daily"]
        if str(row["capacity_plan_version_id"]) == capacity_plan_version_id
        and _in_horizon(row["service_date"], horizon_start, horizon_end)
    }
    lane_capacity = {
        (_date_text(row["service_date"]), str(row["lane_id"])): int(
            row["capacity_units"]
        )
        for row in rows["lane_capacity_daily"]
        if str(row["capacity_plan_version_id"]) == capacity_plan_version_id
        and _in_horizon(row["service_date"], horizon_start, horizon_end)
    }

    selected_baseline = [
        dict(row)
        for row in rows["baseline_network_flow_daily"]
        if str(row["demand_plan_version_id"]) == demand_plan_version_id
        and str(row["capacity_plan_version_id"]) == capacity_plan_version_id
        and _in_horizon(row["service_date"], horizon_start, horizon_end)
    ]
    flow_by_key = {
        (_date_text(row["service_date"]), str(row["lane_id"])): {
            **row,
            "service_date": _date_text(row["service_date"]),
        }
        for row in selected_baseline
    }

    direct_lanes_by_depot: defaultdict[str, list[tuple[str, Mapping[str, Any]]]] = (
        defaultdict(list)
    )
    market_lane_by_depot: dict[str, str] = {}
    delivery_lane_by_customer: dict[str, str] = {}
    for lane_id, lane in lanes.items():
        lane_type = str(lane["lane_type"])
        if (
            lane_type == "LINEHAUL"
            and str(lane["origin_endpoint_id"]) in scoped_dcs
            and str(lane["destination_endpoint_id"]) in scoped_depots
        ):
            direct_lanes_by_depot[str(lane["destination_endpoint_id"])].append(
                (lane_id, lane)
            )
        elif lane_type == "MARKET":
            market_lane_by_depot[str(lane["origin_endpoint_id"])] = lane_id
        elif lane_type == "DELIVERY":
            delivery_lane_by_customer[str(lane["destination_endpoint_id"])] = lane_id

    service_dates = sorted(
        {
            service_date
            for service_date, depot_id in demand_by_date_depot
            if depot_id in scoped_depots
        }
    )
    unmet_rows: list[dict[str, Any]] = []
    allocation_rows: list[dict[str, Any]] = []

    for service_date in service_dates:
        solver = min_cost_flow.SimpleMinCostFlow()
        node_ids: dict[str, int] = {}

        def node(name: str) -> int:
            if name not in node_ids:
                node_ids[name] = len(node_ids)
            return node_ids[name]

        source = node("source")
        sink = node("sink")
        total_demand = sum(
            demand_by_date_depot[(service_date, depot_id)]
            for depot_id in scoped_depots
        )
        tracked_lane_arcs: dict[int, tuple[str, str]] = {}
        tracked_unmet_arcs: dict[int, str] = {}

        for dc_id in sorted(scoped_dcs):
            supplied = facility_capacity.get((service_date, dc_id), 0)
            if dc_id in disabled_facilities:
                supplied = 0
            solver.add_arc_with_capacity_and_unit_cost(
                source, node(f"dc:{dc_id}"), supplied, 0
            )

        for depot_id in sorted(scoped_depots):
            demand = demand_by_date_depot[(service_date, depot_id)]
            assigned_node = node(f"assigned:{depot_id}")
            demand_node = node(f"demand:{depot_id}")
            depot_capacity = facility_capacity.get((service_date, depot_id), 0)
            if depot_id in disabled_facilities:
                depot_capacity = 0
            solver.add_arc_with_capacity_and_unit_cost(
                assigned_node, demand_node, min(demand, depot_capacity), 0
            )
            unmet_arc = solver.add_arc_with_capacity_and_unit_cost(
                source,
                demand_node,
                demand,
                max(1, int(round(unmet_penalty_per_case * 100))),
            )
            tracked_unmet_arcs[unmet_arc] = depot_id
            solver.add_arc_with_capacity_and_unit_cost(demand_node, sink, demand, 0)

            for lane_id, lane in direct_lanes_by_depot[depot_id]:
                origin_id = str(lane["origin_endpoint_id"])
                capacity = lane_capacity.get((service_date, lane_id), 0)
                if (
                    lane_id in disabled_lanes
                    or origin_id in disabled_facilities
                    or depot_id in disabled_facilities
                ):
                    capacity = 0
                base_unit_cost = float(
                    unit_costs.get(
                        lane_id,
                        lane.get("planning_cost_per_case")
                        if lane.get("planning_cost_per_case") is not None
                        else max(450.0, float(lane["distance_miles"]) * 3.4)
                        * 1.12
                        / 900,
                    )
                )
                adjustment = float(cost_adjustments.get(lane_id, 0))
                tariff = float(tariffs.get((service_date, lane_id), 0))
                adjusted_unit_cost = max(
                    0.0001,
                    base_unit_cost * (1 + adjustment / 100) + tariff,
                )
                arc = solver.add_arc_with_capacity_and_unit_cost(
                    node(f"dc:{origin_id}"),
                    assigned_node,
                    capacity,
                    max(1, int(round(adjusted_unit_cost * 100))),
                )
                tracked_lane_arcs[arc] = (lane_id, depot_id)

        solver.set_node_supply(source, total_demand)
        solver.set_node_supply(sink, -total_demand)
        status = solver.solve()
        if status != solver.OPTIMAL:
            raise RuntimeError(
                f"Fixed-capacity network solve failed for {service_date}: status {status}."
            )

        assigned_by_depot: defaultdict[str, int] = defaultdict(int)
        for arc, (lane_id, depot_id) in tracked_lane_arcs.items():
            assigned = int(solver.flow(arc))
            assigned_by_depot[depot_id] += assigned
            key = (service_date, lane_id)
            flow_by_key[key]["assigned_units"] = assigned
            allocation_rows.append(
                {
                    "service_date": service_date,
                    "lane_id": lane_id,
                    "depot_id": depot_id,
                    "assigned_units": assigned,
                    "capacity_units": lane_capacity.get(key, 0),
                }
            )

        for arc, depot_id in tracked_unmet_arcs.items():
            demand = demand_by_date_depot[(service_date, depot_id)]
            unmet = int(solver.flow(arc))
            assigned = assigned_by_depot[depot_id]
            unmet_rows.append(
                {
                    "service_date": service_date,
                    "depot_id": depot_id,
                    "demand_units": demand,
                    "assigned_units": assigned,
                    "unmet_units": unmet,
                }
            )

            market_lane_id = market_lane_by_depot.get(depot_id)
            if market_lane_id:
                flow_by_key[(service_date, market_lane_id)]["assigned_units"] = assigned
            customer_rows = demand_by_date_depot_customers[(service_date, depot_id)]
            customer_allocations = _proportional_allocations(customer_rows, assigned)
            for customer_id, customer_assigned in customer_allocations.items():
                delivery_lane_id = delivery_lane_by_customer[customer_id]
                flow_by_key[(service_date, delivery_lane_id)][
                    "assigned_units"
                ] = customer_assigned

        # Inter-DC lanes and any scoped direct lane with no solver flow remain zero.
        for lane_id, lane in lanes.items():
            origin_id = str(lane["origin_endpoint_id"])
            destination_id = str(lane["destination_endpoint_id"])
            if str(lane["lane_type"]) != "LINEHAUL":
                continue
            if origin_id in scoped_dcs and (
                destination_id in scoped_dcs or destination_id in scoped_depots
            ):
                key = (service_date, lane_id)
                if key in flow_by_key and not any(
                    row["service_date"] == service_date and row["lane_id"] == lane_id
                    for row in allocation_rows
                ):
                    flow_by_key[key]["assigned_units"] = 0

    return {
        "flow_rows": [flow_by_key[key] for key in sorted(flow_by_key)],
        "allocation_rows": allocation_rows,
        "unmet_rows": unmet_rows,
    }


def _distance_miles(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    import math

    lat1, lat2 = math.radians(float(left["lat"])), math.radians(float(right["lat"]))
    dlat = lat2 - lat1
    dlng = math.radians(float(right["lng"]) - float(left["lng"]))
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(value))


def _solve_with_reassignment(
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    demand_plan_version_id: str,
    capacity_plan_version_id: str,
    horizon_start: str,
    horizon_end: str,
    region_id: str,
    release_requests: Sequence[Mapping[str, Any]],
    disabled_facility_ids: set[str],
    disabled_lane_ids: set[str],
    lane_cost_adjustments_pct: Mapping[str, float],
    lane_unit_costs: Mapping[str, float],
    tariff_per_case_by_date_lane: Mapping[tuple[str, str], float],
    unmet_penalty_per_case: float,
) -> dict[str, list[dict[str, Any]]]:
    """Jointly source and assign customer demand, including conserved releases."""

    facilities = {str(r["facility_id"]): r for r in rows["dim_facilities"]}
    customers = {str(r["customer_id"]): r for r in rows["dim_network_customers"]}
    lanes = {str(r["lane_id"]): r for r in rows["dim_network_lanes"]}
    all_demand = [r for r in rows["demand_plan_daily"] if str(r["demand_plan_version_id"]) == demand_plan_version_id and _in_horizon(r["service_date"], horizon_start, horizon_end)]
    releases: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    for request in release_requests:
        releases[(str(request["service_date"]), str(request["customer_id"]), str(request["source_depot_id"]))] += int(request["cases"])
    facility_capacity = {(_date_text(r["service_date"]), str(r["facility_id"])): int(r["capacity_units"]) for r in rows["facility_capacity_daily"] if str(r["capacity_plan_version_id"]) == capacity_plan_version_id and _in_horizon(r["service_date"], horizon_start, horizon_end)}
    lane_capacity = {(_date_text(r["service_date"]), str(r["lane_id"])): int(r["capacity_units"]) for r in rows["lane_capacity_daily"] if str(r["capacity_plan_version_id"]) == capacity_plan_version_id and _in_horizon(r["service_date"], horizon_start, horizon_end)}
    release_customer_ids = {customer_id for _, customer_id, _ in releases}
    release_regions = {str(customers[c]["region_id"]) for c in release_customer_ids}
    focus_depots = {fid for fid, f in facilities.items() if str(f["facility_type"]) == "depot" and bool(f.get("active", True)) and (region_id == "ALL" or str(f["region_id"]) == region_id or str(f["region_id"]) in release_regions)}
    dcs = {fid for fid, f in facilities.items() if str(f["facility_type"]) == "distribution_center" and bool(f.get("active", True)) and (region_id == "ALL" or str(f["region_id"]) == region_id)}
    if region_id != "ALL":
        permitted = _EXTERNAL_DCS_BY_FOCUS_REGION.get(region_id, frozenset())
        dcs.update(str(l["origin_endpoint_id"]) for l in lanes.values() if str(l["lane_type"]) == "LINEHAUL" and str(l["destination_endpoint_id"]) in focus_depots and str(l["origin_endpoint_id"]) in permitted)
        dcs.update(str(l["origin_endpoint_id"]) for l in lanes.values() if str(l["lane_type"]) == "LINEHAUL" and str(l["destination_endpoint_id"]) in focus_depots and str(l["origin_endpoint_id"]) in facilities and str(facilities[str(l["origin_endpoint_id"])]["facility_type"]) == "distribution_center")
    demand = [r for r in all_demand if str(r["depot_id"]) in focus_depots or str(r["distribution_center_id"]) in dcs]
    depots = set(focus_depots) | {str(r["depot_id"]) for r in demand}
    linehaul: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    delivery_by_pair: dict[tuple[str, str], str] = {}
    for lid, lane in lanes.items():
        if str(lane["lane_type"]) == "LINEHAUL" and str(lane["origin_endpoint_id"]) in dcs and str(lane["destination_endpoint_id"]) in depots:
            linehaul[str(lane["destination_endpoint_id"])].append((lid, str(lane["origin_endpoint_id"])))
        elif str(lane["lane_type"]) == "DELIVERY":
            delivery_by_pair[(str(lane["origin_endpoint_id"]), str(lane["destination_endpoint_id"]))] = lid

    flow_by_key = {(_date_text(r["service_date"]), str(r["lane_id"])): {**r, "service_date": _date_text(r["service_date"])} for r in rows["baseline_network_flow_daily"] if str(r["demand_plan_version_id"]) == demand_plan_version_id and str(r["capacity_plan_version_id"]) == capacity_plan_version_id and _in_horizon(r["service_date"], horizon_start, horizon_end)}
    scoped_customers = {str(r["customer_id"]) for r in demand}
    for flow in flow_by_key.values():
        lane = lanes.get(str(flow["lane_id"]), {})
        if (str(lane.get("lane_type")) == "LINEHAUL" and str(lane.get("destination_endpoint_id")) in depots) or (str(lane.get("lane_type")) == "MARKET" and str(lane.get("origin_endpoint_id")) in depots) or (str(lane.get("lane_type")) == "DELIVERY" and str(lane.get("destination_endpoint_id")) in scoped_customers):
            flow["assigned_units"] = 0
    output_lanes = [dict(r) for r in rows["dim_network_lanes"]]
    allocation_rows: list[dict[str, Any]] = []
    unmet_rows: list[dict[str, Any]] = []
    assignment_rows: list[dict[str, Any]] = []
    assignment_overlay_rows: list[dict[str, Any]] = []
    generated_lane_capacity: dict[tuple[str, str], int] = {}
    parent_assignments: defaultdict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for assignment in rows.get("network_customer_assignments_daily", []):
        if str(assignment.get("demand_plan_version_id")) != demand_plan_version_id or str(assignment.get("capacity_plan_version_id")) != capacity_plan_version_id:
            continue
        key = (_date_text(assignment["service_date"]), str(assignment["customer_id"]))
        parent_assignments[key][str(assignment["depot_id"])] = int(assignment["required_units"])

    for service_date in sorted({_date_text(r["service_date"]) for r in demand}):
        day_rows = [r for r in demand if _date_text(r["service_date"]) == service_date]
        solver = min_cost_flow.SimpleMinCostFlow()
        ids: dict[str, int] = {}
        def node(name: str) -> int:
            if name not in ids: ids[name] = len(ids)
            return ids[name]
        source, sink = node("source"), node("sink")
        total = sum(int(r["demand_units"]) for r in day_rows)
        tracked_linehaul: dict[int, tuple[str, str]] = {}
        tracked_assign: dict[int, tuple[str, str, str]] = {}
        tracked_unmet: dict[int, tuple[str, str, str, int]] = {}
        delivery_pair_nodes: set[tuple[str, str]] = set()
        for dc in sorted(dcs):
            cap = 0 if dc in disabled_facility_ids else facility_capacity.get((service_date, dc), 0)
            solver.add_arc_with_capacity_and_unit_cost(source, node(f"dc:{dc}"), cap, 0)
        for depot in sorted(depots):
            cap = 0 if depot in disabled_facility_ids else facility_capacity.get((service_date, depot), 0)
            solver.add_arc_with_capacity_and_unit_cost(node(f"depot:{depot}"), node(f"depotcap:{depot}"), cap, 0)
            for lid, dc in linehaul[depot]:
                cap = lane_capacity.get((service_date, lid), 0)
                if lid in disabled_lane_ids or dc in disabled_facility_ids or depot in disabled_facility_ids: cap = 0
                lane = lanes[lid]
                base = float(lane_unit_costs.get(lid, lane.get("planning_cost_per_case") or max(450.0, float(lane["distance_miles"]) * 3.4) * 1.12 / 900))
                cost = base * (1 + float(lane_cost_adjustments_pct.get(lid, 0)) / 100) + float(tariff_per_case_by_date_lane.get((service_date, lid), 0))
                arc = solver.add_arc_with_capacity_and_unit_cost(node(f"dc:{dc}"), node(f"depot:{depot}"), cap, max(1, round(cost * 100)))
                tracked_linehaul[arc] = (lid, depot)
        for row in day_rows:
            customer_id, home, qty = str(row["customer_id"]), str(row["depot_id"]), int(row["demand_units"])
            distribution = parent_assignments.get((service_date, customer_id)) or {home: qty}
            groups: list[tuple[str, str, int, list[str]]] = []
            customer = customers[customer_id]
            for source_depot, source_required in distribution.items():
                released = releases.get((service_date, customer_id, source_depot), 0)
                if released > source_required:
                    raise ValueError(f"Release exceeds parent assignment for {customer_id} at {source_depot} on {service_date}.")
                groups.append((f"locked:{source_depot}", source_depot, source_required - released, [source_depot]))
                if released:
                    alternatives = [d for d in depots if d != source_depot and str(facilities[d]["region_id"]) == str(customer["region_id"]) and bool(facilities[d].get("active", True)) and d not in disabled_facility_ids and linehaul[d]]
                    alternatives.sort(key=lambda d: (_distance_miles(customer, facilities[d]), d))
                    groups.append((f"released:{source_depot}", source_depot, released, alternatives[:3]))
            for label, source_depot, amount, eligible in groups:
                if amount <= 0: continue
                group = f"demand:{customer_id}:{label}"
                solver.add_arc_with_capacity_and_unit_cost(node(group), sink, amount, 0)
                arc = solver.add_arc_with_capacity_and_unit_cost(source, node(group), amount, max(1, round(unmet_penalty_per_case * 100)))
                tracked_unmet[arc] = (customer_id, source_depot, label, amount)
                for depot in eligible:
                    pair = (depot, customer_id)
                    existing_delivery = delivery_by_pair.get((depot, customer_id))
                    if existing_delivery:
                        delivery_lane = lanes[existing_delivery]
                        delivery_capacity = lane_capacity.get((service_date, existing_delivery), 0)
                        if existing_delivery in disabled_lane_ids or not bool(delivery_lane.get("active", True)):
                            delivery_capacity = 0
                    else:
                        delivery_capacity = sum(value for (day, released_customer, _), value in releases.items() if day == service_date and released_customer == customer_id)
                        generated_lane_id = f"LNE_{depot}_TO_{customer_id}"
                        generated_lane_capacity[(service_date, generated_lane_id)] = amount
                        miles = _distance_miles(facilities[depot], customers[customer_id])
                        generated_lane = {"lane_id": generated_lane_id, "lane_name": f"{depot} to {customer_id}", "lane_type": "DELIVERY", "origin_endpoint_id": depot, "origin_endpoint_type": "facility", "destination_endpoint_id": customer_id, "destination_endpoint_type": "customer", "mode": "ground", "distance_miles": round(miles, 1), "transit_minutes": max(1, round(miles / 35 * 60)), "planning_cost_per_case": None, "active": True, "eligibility_source": "deterministic_nearby_same_region_release_v1"}
                        lanes[generated_lane_id] = generated_lane
                        output_lanes.append(generated_lane)
                        delivery_by_pair[(depot, customer_id)] = generated_lane_id
                    miles = _distance_miles(customers[customer_id], facilities[depot])
                    delivery_node = node(f"delivery:{depot}:{customer_id}")
                    if pair not in delivery_pair_nodes:
                        solver.add_arc_with_capacity_and_unit_cost(node(f"depotcap:{depot}"), delivery_node, delivery_capacity, max(1, round(miles * 2)))
                        delivery_pair_nodes.add(pair)
                    arc = solver.add_arc_with_capacity_and_unit_cost(delivery_node, node(group), amount, 0)
                    tracked_assign[arc] = (customer_id, label, depot)
        solver.set_node_supply(source, total); solver.set_node_supply(sink, -total)
        if solver.solve() != solver.OPTIMAL: raise RuntimeError(f"Reassignment solve failed for {service_date}.")
        depot_assigned: defaultdict[str, int] = defaultdict(int)
        customer_assigned: defaultdict[tuple[str, str], int] = defaultdict(int)
        customer_unmet: defaultdict[tuple[str, str], int] = defaultdict(int)
        for arc, (lid, depot) in tracked_linehaul.items():
            units = int(solver.flow(arc)); depot_assigned[depot] += units
            if (service_date, lid) in flow_by_key: flow_by_key[(service_date, lid)]["assigned_units"] = units
            allocation_rows.append({"service_date": service_date, "lane_id": lid, "depot_id": depot, "assigned_units": units, "capacity_units": lane_capacity.get((service_date, lid), 0)})
        for arc, (customer_id, label, depot) in tracked_assign.items():
            units = int(solver.flow(arc))
            if units: customer_assigned[(customer_id, depot)] += units; assignment_rows.append({"service_date": service_date, "customer_id": customer_id, "depot_id": depot, "assignment_kind": label.split(":", 1)[0], "assigned_units": units})
        customer_unmet_by_source: defaultdict[tuple[str, str, str], int] = defaultdict(int)
        for arc, (customer_id, source_depot, label, amount) in tracked_unmet.items():
            units = int(solver.flow(arc))
            customer_unmet[(customer_id, label)] += units
            customer_unmet_by_source[(customer_id, source_depot, label)] += units
        overlay: defaultdict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"assigned_units": 0, "unmet_units": 0})
        for (customer_id, depot), units in customer_assigned.items():
            overlay[(customer_id, depot)]["assigned_units"] += units
        for (customer_id, source_depot, _), units in customer_unmet_by_source.items():
            overlay[(customer_id, source_depot)]["unmet_units"] += units
        for (customer_id, depot), totals in overlay.items():
            source_depot = str(customers[customer_id]["depot_id"])
            required = int(totals["assigned_units"]) + int(totals["unmet_units"])
            if required:
                assignment_overlay_rows.append({"demand_plan_version_id": demand_plan_version_id, "capacity_plan_version_id": capacity_plan_version_id, "service_date": service_date, "customer_id": customer_id, "depot_id": depot, "source_depot_id": source_depot, "required_units": required, "assigned_units": int(totals["assigned_units"]), "unmet_units": int(totals["unmet_units"]), "assignment_kind": "home" if depot == source_depot else "reassigned"})
        for depot in sorted(depots):
            demand_units = sum(int(values["assigned_units"]) + int(values["unmet_units"]) for (customer_id, assigned_depot), values in overlay.items() if assigned_depot == depot)
            unmet = sum(v for (_customer_id, source_depot, _), v in customer_unmet_by_source.items() if source_depot == depot)
            unmet_rows.append({"service_date": service_date, "depot_id": depot, "demand_units": demand_units, "assigned_units": depot_assigned[depot], "unmet_units": unmet})
            market_lane = next((lid for lid, lane in lanes.items() if str(lane["lane_type"]) == "MARKET" and str(lane["origin_endpoint_id"]) == depot), None)
            if market_lane and (service_date, market_lane) in flow_by_key:
                flow_by_key[(service_date, market_lane)]["assigned_units"] = depot_assigned[depot]
        for (customer_id, depot), units in customer_assigned.items():
            lane_id = delivery_by_pair.get((depot, customer_id), f"LNE_{depot}_TO_{customer_id}")
            if lane_id not in lanes:
                lane = {"lane_id": lane_id, "lane_name": f"{depot} to {customer_id}", "lane_type": "DELIVERY", "origin_endpoint_id": depot, "origin_endpoint_type": "facility", "destination_endpoint_id": customer_id, "destination_endpoint_type": "customer", "mode": "ground", "distance_miles": round(_distance_miles(facilities[depot], customers[customer_id]), 1), "transit_minutes": max(1, round(_distance_miles(facilities[depot], customers[customer_id]) / 35 * 60)), "planning_cost_per_case": None, "active": True}
                lane["eligibility_source"] = "deterministic_nearby_same_region_release_v1"
                lanes[lane_id] = lane; output_lanes.append(lane)
            template = next((r for r in flow_by_key.values() if str(r.get("lane_id")) == lane_id), None)
            flow_by_key[(service_date, lane_id)] = {**(template or {"demand_plan_version_id": demand_plan_version_id, "capacity_plan_version_id": capacity_plan_version_id}), "service_date": service_date, "lane_id": lane_id, "lane_type": "DELIVERY", "assigned_units": units}
    output_capacity = [dict(r) for r in rows["lane_capacity_daily"]]
    output_capacity.extend({"capacity_plan_version_id": capacity_plan_version_id, "service_date": day, "lane_id": lane_id, "capacity_units": amount, "capacity_source": "release_eligibility_cap"} for (day, lane_id), amount in generated_lane_capacity.items())
    return {"flow_rows": [flow_by_key[k] for k in sorted(flow_by_key)], "allocation_rows": allocation_rows, "unmet_rows": unmet_rows, "assignment_rows": assignment_rows, "assignment_overlay_rows": assignment_overlay_rows, "network_lanes": output_lanes, "lane_capacity_rows": output_capacity}
