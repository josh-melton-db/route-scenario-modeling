from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from ortools.graph.python import min_cost_flow


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
    unmet_penalty_per_case: float = 250.0,
) -> dict[str, list[dict[str, Any]]]:
    """Assign fixed demand through fixed supplied capacity.

    The solver can leave demand unmet at the configured penalty, but it never
    creates facility or lane capacity. Distribution-center and depot capacity,
    disabled nodes, disabled lanes, and direct DC-to-depot lane capacities are
    all hard bounds.
    """

    disabled_facilities = disabled_facility_ids or set()
    disabled_lanes = disabled_lane_ids or set()
    cost_adjustments = lane_cost_adjustments_pct or {}
    unit_costs = lane_unit_costs or {}

    facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
    lanes = {str(row["lane_id"]): row for row in rows["dim_network_lanes"]}
    scoped_depots = {
        facility_id
        for facility_id, facility in facilities.items()
        if facility["facility_type"] == "depot"
        and (region_id == "ALL" or str(facility["region_id"]) == region_id)
    }
    scoped_dcs = {
        facility_id
        for facility_id, facility in facilities.items()
        if facility["facility_type"] == "distribution_center"
        and (region_id == "ALL" or str(facility["region_id"]) == region_id)
    }

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
                        max(450.0, float(lane["distance_miles"]) * 3.4)
                        * 1.12
                        / 900,
                    )
                )
                adjustment = float(cost_adjustments.get(lane_id, 0))
                adjusted_unit_cost = max(0.0001, base_unit_cost * (1 + adjustment / 100))
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
