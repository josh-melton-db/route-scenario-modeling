from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from .baseline import summarize_kpis
from .cost import CostParameters
from .schemas import MATRIX_SOURCE
from .solver import solve_scenario_partition


NetworkRows = Mapping[str, Sequence[Mapping[str, object]]]


def materialize_depot_targets(
    network_rows: NetworkRows,
    flow_rows: Sequence[Mapping[str, object]],
    depot_id: str,
    service_date: str | date,
) -> dict[str, object]:
    """Materialize one depot/date's exact assigned delivery targets.

    DELIVERY lane assignments are authoritative. LINEHAUL and MARKET rows are
    intentionally ignored so multiple inbound DC sources cannot duplicate the
    depot's downstream customer demand.
    """

    service_date_text = _date_text(service_date)
    _validate_snapshot_coverage(network_rows, service_date_text)

    facilities = _index_rows(network_rows, "dim_facilities", "facility_id")
    customers = _index_rows(network_rows, "dim_network_customers", "customer_id")
    lanes = _index_rows(network_rows, "dim_network_lanes", "lane_id")
    depot = facilities.get(depot_id)
    if depot is None or str(depot.get("facility_type")) != "depot":
        raise ValueError(f"Unknown depot_id {depot_id!r}.")

    assigned_by_customer: defaultdict[str, int] = defaultdict(int)
    reassigned = {
        (str(row.get("customer_id")), str(row.get("depot_id"))): int(
            row.get("assigned_units", 0)
        )
        for row in network_rows.get("network_customer_assignments_daily", [])
        if _date_text(row.get("service_date")) == service_date_text
    }
    seen_delivery_lanes: dict[str, int] = {}
    for flow in flow_rows:
        if _date_text(flow.get("service_date")) != service_date_text:
            continue
        lane_id = str(flow.get("lane_id", ""))
        lane = lanes.get(lane_id)
        lane_type = str(flow.get("lane_type") or (lane or {}).get("lane_type") or "")
        if lane_type != "DELIVERY":
            continue
        if lane is None:
            raise ValueError(f"Assigned flow references unknown delivery lane {lane_id!r}.")
        if str(lane.get("origin_endpoint_id")) != depot_id:
            continue
        assigned_cases = _assigned_cases(flow)
        prior = seen_delivery_lanes.get(lane_id)
        if prior is not None:
            if prior != assigned_cases:
                raise ValueError(
                    f"Delivery lane {lane_id!r} has conflicting assignments on {service_date_text}."
                )
            continue
        seen_delivery_lanes[lane_id] = assigned_cases
        customer_id = str(lane.get("destination_endpoint_id", ""))
        if customer_id not in customers:
            raise ValueError(f"Delivery lane {lane_id!r} references unknown customer {customer_id!r}.")
        home_depot = str(customers[customer_id].get("depot_id"))
        if home_depot != depot_id and reassigned.get((customer_id, depot_id), 0) < assigned_cases:
            raise ValueError(
                f"Delivery lane {lane_id!r} lacks a solved reassignment overlay."
            )
        assigned_by_customer[customer_id] += assigned_cases

    planning_customers: list[dict[str, object]] = []
    planning_stops: list[dict[str, object]] = []
    orders: list[dict[str, object]] = []
    for customer_id in sorted(assigned_by_customer):
        assigned_cases = assigned_by_customer[customer_id]
        if assigned_cases == 0:
            continue
        customer = customers[customer_id]
        order_id = _order_id(depot_id, service_date_text, customer_id)
        planning_customer = {
            **customer,
            "customer_id": customer_id,
            "customer_name": str(customer.get("customer_name") or customer_id),
            "customer_priority": str(customer.get("customer_priority") or customer.get("customer_tier") or "standard"),
            "receiving_window_start": str(customer.get("receiving_window_start") or "06:30"),
            "receiving_window_end": str(customer.get("receiving_window_end") or "18:00"),
            "service_minutes": int(customer.get("service_minutes", 20)),
            "hard_time_window_flag": _bool_value(customer.get("hard_time_window_flag", False)),
        }
        order = {
            "order_id": order_id,
            "stop_id": f"STOP-{order_id}",
            "customer_id": customer_id,
            "depot_id": depot_id,
            "service_date": service_date_text,
            "delivery_day": service_date_text,
            "route_date": service_date_text,
            "demand_cases": assigned_cases,
        }
        planning_customers.append(planning_customer)
        planning_stops.append(dict(order))
        orders.append(dict(order))

    planning_depot = {
        **depot,
        "depot_id": depot_id,
        "depot_name": str(depot.get("depot_name") or depot.get("facility_name") or depot_id),
        "region": str(depot.get("region") or depot.get("region_id") or ""),
        "sales_territory": str(
            depot.get("sales_territory") or depot.get("region") or depot.get("region_id") or ""
        ),
    }
    assigned_cases = sum(int(order["demand_cases"]) for order in orders)
    return {
        "service_date": service_date_text,
        "depot": _depot_contract(planning_depot),
        "assigned_cases": assigned_cases,
        "orders": orders,
        "planning_depots": [planning_depot],
        "planning_customers": planning_customers,
        "planning_stops": planning_stops,
    }


def solve_depot_plan(
    network_rows: NetworkRows,
    flow_rows: Sequence[Mapping[str, object]],
    depot_id: str,
    service_date: str | date,
    fleet: Sequence[Mapping[str, object]],
    *,
    scenario_id: str = "network-depot-plan",
    travel_matrix: Iterable[Mapping[str, object]] | None = None,
    cost_parameters: CostParameters | None = None,
    time_limit_seconds: int = 2,
) -> dict[str, object]:
    """Materialize and solve exactly one depot/date with the supplied fleet."""

    targets = materialize_depot_targets(network_rows, flow_rows, depot_id, service_date)
    service_date_text = str(targets["service_date"])
    planning_fleet = _available_fleet(fleet, depot_id, service_date_text)
    matrix_rows = list(travel_matrix) if travel_matrix is not None else None
    solver_result = solve_scenario_partition(
        scenario_id=scenario_id,
        depot_id=depot_id,
        delivery_day=service_date_text,
        planning_depots=list(targets["planning_depots"]),
        planning_customers=list(targets["planning_customers"]),
        planning_fleet=planning_fleet,
        planning_stops=list(targets["planning_stops"]),
        travel_matrix=matrix_rows,
        params=cost_parameters,
        time_limit_seconds=time_limit_seconds,
    )

    raw_routes = list(solver_result["routes"])
    route_stops = list(solver_result["route_stops"])
    orders_by_customer = {
        str(order["customer_id"]): order for order in targets["orders"]
    }
    routes = _route_contracts(raw_routes, route_stops, orders_by_customer, service_date_text)
    unserved_orders = []
    for unassigned in solver_result["unassigned_stops"]:
        customer_id = str(unassigned["customer_id"])
        order = orders_by_customer[customer_id]
        unserved_orders.append(
            {
                **order,
                "reason": str(unassigned["reason"]),
            }
        )

    assigned_cases = int(targets["assigned_cases"])
    routed_cases = sum(int(route["total_cases"]) for route in raw_routes)
    unserved_cases = sum(int(order["demand_cases"]) for order in unserved_orders)
    if assigned_cases != routed_cases + unserved_cases:
        raise RuntimeError(
            "Depot route accounting failed: assigned cases must equal routed plus unserved cases."
        )

    diagnostics = list(solver_result["diagnostics"])
    for diagnostic in diagnostics:
        diagnostic["service_date"] = service_date_text
        diagnostic["matrix_source"] = _matrix_source(matrix_rows)
        diagnostic["assigned_cases"] = assigned_cases
        diagnostic["routed_cases"] = routed_cases
        diagnostic["unserved_cases"] = unserved_cases

    return {
        "service_date": service_date_text,
        "depot": targets["depot"],
        "targets": {
            "service_date": service_date_text,
            "depot_id": depot_id,
            "assigned_cases": assigned_cases,
            "orders": targets["orders"],
        },
        "routes": routes,
        "kpis": summarize_kpis(raw_routes),
        "assigned_cases": assigned_cases,
        "routed_cases": routed_cases,
        "unserved_cases": unserved_cases,
        "unserved_orders": unserved_orders,
        "diagnostics": diagnostics,
        "matrix_source": _matrix_source(matrix_rows),
    }


def _validate_snapshot_coverage(network_rows: NetworkRows, service_date: str) -> None:
    target = date.fromisoformat(service_date)
    checked = False
    for table_name in ("demand_plan_versions", "capacity_plan_versions"):
        versions = network_rows.get(table_name, ())
        if not versions:
            continue
        checked = True
        if not any(
            date.fromisoformat(_date_text(row["horizon_start"]))
            <= target
            <= date.fromisoformat(_date_text(row["horizon_end"]))
            for row in versions
        ):
            raise ValueError(
                f"service_date {service_date} is outside {table_name} snapshot coverage."
            )
    if not checked:
        raise ValueError("network_rows must include demand or capacity plan version coverage.")


def _index_rows(
    network_rows: NetworkRows, table_name: str, key_name: str
) -> dict[str, Mapping[str, object]]:
    rows = network_rows.get(table_name)
    if rows is None:
        raise ValueError(f"network_rows is missing required table {table_name!r}.")
    return {str(row[key_name]): row for row in rows}


def _assigned_cases(flow: Mapping[str, object]) -> int:
    value = flow.get("assigned_units", flow.get("assigned_cases"))
    if value is None:
        raise ValueError("Assigned flow row is missing assigned_units/assigned_cases.")
    assigned_cases = int(value)
    if assigned_cases < 0:
        raise ValueError("Assigned cases cannot be negative.")
    return assigned_cases


def _available_fleet(
    fleet: Sequence[Mapping[str, object]], depot_id: str, service_date: str
) -> list[dict[str, object]]:
    weekday = date.fromisoformat(service_date).strftime("%A")
    available: list[dict[str, object]] = []
    for vehicle in fleet:
        if str(vehicle.get("depot_id")) != depot_id:
            continue
        if int(vehicle.get("capacity_cases", 0)) <= 0:
            raise ValueError("Every supplied vehicle must have a positive capacity_cases value.")
        availability = vehicle.get("available_dates", vehicle.get("available_days"))
        if availability is not None:
            if isinstance(availability, str):
                values = {value.strip() for value in availability.split(",") if value.strip()}
            else:
                values = {str(value) for value in availability}  # type: ignore[arg-type]
            if service_date not in values and weekday not in values:
                continue
        available.append(
            {
                **vehicle,
                "depot_id": depot_id,
                "available_days": service_date,
            }
        )
    return available


def _route_contracts(
    raw_routes: Sequence[Mapping[str, object]],
    route_stops: Sequence[Mapping[str, object]],
    orders_by_customer: Mapping[str, Mapping[str, object]],
    service_date: str,
) -> list[dict[str, object]]:
    stops_by_route: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
    for stop in route_stops:
        stops_by_route[str(stop["route_id"])].append(stop)
    contracts: list[dict[str, object]] = []
    for route in raw_routes:
        stops = sorted(stops_by_route[str(route["route_id"])], key=lambda row: int(row["sequence"]))
        contracts.append(
            {
                "route_id": route["route_id"],
                "scenario_id": route["scenario_id"],
                "route_name": route["route_name"],
                "depot_id": route["depot_id"],
                "driver_id": route["driver_id"],
                "driver_name": route["driver_name"],
                "vehicle_id": route["vehicle_id"],
                "delivery_day": service_date,
                "path": route["path"],
                "stops": [
                    {
                        "stop_id": orders_by_customer[str(stop["customer_id"])]["stop_id"],
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
                        "delivery_day": service_date,
                        "window_risk": stop["window_risk"],
                        "is_new_customer": stop.get("is_new_customer", False),
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
                "rated_service_date": service_date,
            }
        )
    return contracts


def _depot_contract(depot: Mapping[str, object]) -> dict[str, object]:
    return {
        "depot_id": str(depot["depot_id"]),
        "name": str(depot["depot_name"]),
        "region": str(depot["region"]),
        "sales_territory": str(depot["sales_territory"]),
        "location": {"lat": float(depot["lat"]), "lng": float(depot["lng"])},
    }


def _matrix_source(travel_matrix: Iterable[Mapping[str, object]] | None) -> str:
    if travel_matrix is None:
        return MATRIX_SOURCE
    sources = {str(row.get("matrix_source", MATRIX_SOURCE)) for row in travel_matrix}
    return sources.pop() if len(sources) == 1 else MATRIX_SOURCE


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _order_id(depot_id: str, service_date: str, customer_id: str) -> str:
    return f"ORD-{depot_id}-{service_date.replace('-', '')}-{customer_id}"


def _date_text(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()
