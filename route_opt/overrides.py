from __future__ import annotations

import copy
from datetime import datetime

from .schemas import BASELINE_SCENARIO_ID


def seed_scenario_definitions() -> list[dict[str, object]]:
    now = datetime.utcnow().isoformat() + "Z"
    return [
        {
            "scenario_id": "baseline",
            "scenario_name": "Baseline",
            "scenario_type": "baseline",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "status": "completed",
            "created_at": now,
        },
        {
            "scenario_id": "scn_ma_newcustomers",
            "scenario_name": "M&A New Customer Group",
            "scenario_type": "ma_new_customers",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "status": "validated",
            "created_at": now,
        },
        {
            "scenario_id": "scn_new_customer_growth",
            "scenario_name": "Organic New Customer Growth",
            "scenario_type": "new_customer_growth",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "status": "validated",
            "created_at": now,
        },
        {
            "scenario_id": "scn_driver_minus_one",
            "scenario_name": "One Fewer Driver",
            "scenario_type": "driver_count_change",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "status": "validated",
            "created_at": now,
        },
        {
            "scenario_id": "scn_day_change",
            "scenario_name": "Delivery Day Rebalance",
            "scenario_type": "delivery_frequency_day_change",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "status": "validated",
            "created_at": now,
        },
        {
            "scenario_id": "scn_facility_move",
            "scenario_name": "Facility Move Stress Test",
            "scenario_type": "facility_move",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "status": "validated",
            "created_at": now,
        },
        {
            "scenario_id": "scn_custom_composite",
            "scenario_name": "Custom: Fewer Drivers + New Stops + Higher Mileage Cost",
            "scenario_type": "custom",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "status": "validated",
            "created_at": now,
        },
    ]


def seed_scenario_parameters() -> list[dict[str, object]]:
    rows = [
        ("scn_ma_newcustomers", "new_customer_count", "4"),
        ("scn_ma_newcustomers", "avg_cases_per_customer", "95"),
        ("scn_new_customer_growth", "growth_customer_count", "4"),
        ("scn_new_customer_growth", "growth_zone", "east_corridor"),
        ("scn_driver_minus_one", "driver_delta", "-1"),
        ("scn_driver_minus_one", "allow_overtime", "true"),
        ("scn_day_change", "target_customers", "flexible_independents"),
        ("scn_day_change", "target_day", "Thursday"),
        ("scn_facility_move", "new_depot_lat", "41.8000"),
        ("scn_facility_move", "new_depot_lng", "-84.8000"),
        ("scn_facility_move", "preserve_service_windows", "true"),
        ("scn_custom_composite", "driver_delta", "-1"),
        ("scn_custom_composite", "new_customer_count", "5"),
        ("scn_custom_composite", "cost_per_mile", "4.5"),
    ]
    return [
        {"scenario_id": scenario_id, "parameter_name": name, "parameter_value": value}
        for scenario_id, name, value in rows
    ]


OVERRIDE_TABLE_KEYS = [
    "scenario_customer_overrides",
    "scenario_fleet_overrides",
    "scenario_depot_overrides",
    "scenario_frequency_overrides",
    "scenario_cost_overrides",
]

_GROWTH_ZONE_DIRECTIONS = {
    "east_corridor": (0.6, 1.0),
    "south_ring": (-1.0, 0.2),
    "north_suburbs": (1.0, -0.2),
}

COST_OVERRIDE_FIELDS = (
    "cost_per_mile",
    "labor_regular_hour",
    "overtime_multiplier",
    "overtime_threshold_minutes",
    "fixed_truck_daily_cost",
    "late_delivery_penalty",
    "missed_delivery_penalty",
)


def _empty_override_tables() -> dict[str, list[dict[str, object]]]:
    return {key: [] for key in OVERRIDE_TABLE_KEYS}


def _merge_override_tables(
    *tables: dict[str, list[dict[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    result = _empty_override_tables()
    for table in tables:
        for key in OVERRIDE_TABLE_KEYS:
            result[key].extend(table.get(key, []))
    return result


def _generated_customer_add_rows(
    *,
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    depot: dict[str, object],
    count: int,
    cases: int,
    name_prefix: str,
    id_prefix: str,
    service_minutes: int,
    window_start: str,
    window_end: str,
    growth_zone: str = "east_corridor",
) -> list[dict[str, object]]:
    base_lat = float(depot["lat"])
    base_lng = float(depot["lng"])
    lat_dir, lng_dir = _GROWTH_ZONE_DIRECTIONS.get(
        growth_zone,
        _GROWTH_ZONE_DIRECTIONS["east_corridor"],
    )
    suffix = scenario_id[-6:]
    rows: list[dict[str, object]] = []
    for idx in range(1, count + 1):
        rows.append(
            {
                "scenario_id": scenario_id,
                "override_type": "add_customer",
                "customer_id": f"{id_prefix}-{suffix}-{idx:03d}",
                "customer_name": f"{name_prefix} {idx}",
                "depot_id": depot_id,
                "lat": round(base_lat + lat_dir * (0.05 + idx * 0.015), 6),
                "lng": round(base_lng + lng_dir * (0.06 + idx * 0.018), 6),
                "delivery_day": delivery_day,
                "demand_cases": cases,
                "service_minutes": service_minutes,
                "receiving_window_start": window_start,
                "receiving_window_end": window_end,
            }
        )
    return rows


def _manual_customer_add_rows(
    *,
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    deliveries: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    suffix = scenario_id[-6:]
    for idx, delivery in enumerate(deliveries, start=1):
        customer_id = str(delivery.get("customer_id") or f"NEW-MANUAL-{suffix}-{idx:03d}")
        rows.append(
            {
                "scenario_id": scenario_id,
                "override_type": "add_customer",
                "customer_id": customer_id,
                "customer_name": str(delivery.get("customer_name") or f"Manual Delivery {idx}"),
                "depot_id": depot_id,
                "lat": float(delivery["lat"]),
                "lng": float(delivery["lng"]),
                "delivery_day": str(delivery.get("delivery_day") or delivery_day),
                "demand_cases": int(delivery.get("demand_cases") or 80),
                "service_minutes": int(delivery.get("service_minutes") or 30),
                "receiving_window_start": str(delivery.get("receiving_window_start") or "08:00"),
                "receiving_window_end": str(delivery.get("receiving_window_end") or "16:00"),
            }
        )
    return rows


def _fleet_delta_rows(
    *,
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    driver_delta: int,
    allow_overtime: bool = True,
) -> list[dict[str, object]]:
    return [
        {
            "scenario_id": scenario_id,
            "depot_id": depot_id,
            "delivery_day": delivery_day,
            "driver_delta": int(driver_delta),
            "vehicle_delta": int(driver_delta),
            "allow_overtime": bool(allow_overtime),
        }
    ]


def _frequency_rows(
    *,
    scenario_id: str,
    delivery_day: str,
    target_day: str,
    eligible_customer_ids: list[str] | None,
    limit: int = 6,
) -> list[dict[str, object]]:
    return [
        {
            "scenario_id": scenario_id,
            "customer_id": str(customer_id),
            "baseline_day": delivery_day,
            "scenario_day": target_day,
        }
        for customer_id in list(eligible_customer_ids or [])[:limit]
    ]


def _depot_move_rows(
    *,
    scenario_id: str,
    depot_id: str,
    new_lat: float,
    new_lng: float,
    preserve_service_windows: bool = True,
) -> list[dict[str, object]]:
    return [
        {
            "scenario_id": scenario_id,
            "depot_id": depot_id,
            "new_lat": float(new_lat),
            "new_lng": float(new_lng),
            "preserve_service_windows": bool(preserve_service_windows),
        }
    ]


def _cost_override_rows(
    *,
    scenario_id: str,
    cost: dict[str, object] | None,
) -> list[dict[str, object]]:
    if not cost:
        return []
    row: dict[str, object] = {"scenario_id": scenario_id}
    has_value = False
    for field in COST_OVERRIDE_FIELDS:
        value = cost.get(field)
        if value is None:
            row[field] = None
            continue
        has_value = True
        row[field] = float(value) if field != "overtime_threshold_minutes" else int(value)
    return [row] if has_value else []


def _append_generated_customers(
    result: dict[str, list[dict[str, object]]],
    *,
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    parameters: dict[str, object],
    depot: dict[str, object] | None,
    scenario_type: str,
) -> None:
    if depot is None:
        raise ValueError("depot is required to place new customers")
    if scenario_type == "ma_new_customers":
        count = int(parameters.get("new_customer_count") or 4)
        cases = int(parameters.get("avg_cases_per_customer") or 95)
        name_prefix, id_prefix = "Acquired Retailer", "NEW-MA"
        service_minutes = 30
        window_start, window_end = "08:00", "16:00"
    else:
        count = int(parameters.get("growth_customer_count") or 4)
        cases = int(parameters.get("avg_cases_per_customer") or 80)
        name_prefix, id_prefix = "Growth Account", "NEW-GROWTH"
        service_minutes = 25
        window_start, window_end = "09:00", "17:00"
    result["scenario_customer_overrides"].extend(
        _generated_customer_add_rows(
            scenario_id=scenario_id,
            depot_id=depot_id,
            delivery_day=delivery_day,
            depot=depot,
            count=count,
            cases=cases,
            name_prefix=name_prefix,
            id_prefix=id_prefix,
            service_minutes=service_minutes,
            window_start=window_start,
            window_end=window_end,
            growth_zone=str(parameters.get("growth_zone") or "east_corridor"),
        )
    )


def _apply_custom_change(
    result: dict[str, list[dict[str, object]]],
    *,
    change: dict[str, object],
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    depot: dict[str, object] | None,
    eligible_customer_ids: list[str] | None,
) -> None:
    kind = str(change.get("kind") or "")
    if kind == "add_deliveries":
        deliveries = change.get("deliveries") or []
        if not isinstance(deliveries, list):
            raise ValueError("add_deliveries requires a deliveries list")
        result["scenario_customer_overrides"].extend(
            _manual_customer_add_rows(
                scenario_id=scenario_id,
                depot_id=depot_id,
                delivery_day=delivery_day,
                deliveries=[row for row in deliveries if isinstance(row, dict)],
            )
        )
    elif kind == "driver_count_change":
        result["scenario_fleet_overrides"].extend(
            _fleet_delta_rows(
                scenario_id=scenario_id,
                depot_id=depot_id,
                delivery_day=delivery_day,
                driver_delta=int(change.get("driver_delta") or 0),
                allow_overtime=bool(change.get("allow_overtime", True)),
            )
        )
    elif kind == "delivery_frequency_day_change":
        result["scenario_frequency_overrides"].extend(
            _frequency_rows(
                scenario_id=scenario_id,
                delivery_day=delivery_day,
                target_day=str(change.get("target_day") or "Thursday"),
                eligible_customer_ids=eligible_customer_ids,
            )
        )
    elif kind == "facility_move":
        location = change.get("new_depot_location")
        new_lat = location.get("lat") if isinstance(location, dict) else None
        new_lng = location.get("lng") if isinstance(location, dict) else None
        if new_lat is None or new_lng is None:
            raise ValueError("facility_move requires a new depot location")
        result["scenario_depot_overrides"].extend(
            _depot_move_rows(
                scenario_id=scenario_id,
                depot_id=depot_id,
                new_lat=float(new_lat),
                new_lng=float(new_lng),
                preserve_service_windows=bool(change.get("preserve_service_windows", True)),
            )
        )
    else:
        raise ValueError(f"Unsupported custom change kind: {kind}")


def build_scenario_overrides(
    *,
    scenario_id: str,
    scenario_type: str,
    depot_id: str,
    delivery_day: str,
    parameters: dict[str, object],
    depot: dict[str, object] | None = None,
    eligible_customer_ids: list[str] | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Translate scenario parameters into normalized override rows.

    Preset scenario types keep their existing parameter contracts. Custom
    scenarios compose any combination of change kinds via parameters["changes"].
    Cost overrides are independent and live in parameters["cost"].
    """

    result = _empty_override_tables()

    if scenario_type in {"ma_new_customers", "new_customer_growth"}:
        _append_generated_customers(
            result,
            scenario_id=scenario_id,
            depot_id=depot_id,
            delivery_day=delivery_day,
            parameters=parameters,
            depot=depot,
            scenario_type=scenario_type,
        )
    elif scenario_type == "driver_count_change":
        result["scenario_fleet_overrides"].extend(
            _fleet_delta_rows(
                scenario_id=scenario_id,
                depot_id=depot_id,
                delivery_day=delivery_day,
                driver_delta=int(parameters.get("driver_delta") or 0),
                allow_overtime=bool(parameters.get("allow_overtime", True)),
            )
        )
    elif scenario_type == "delivery_frequency_day_change":
        result["scenario_frequency_overrides"].extend(
            _frequency_rows(
                scenario_id=scenario_id,
                delivery_day=delivery_day,
                target_day=str(parameters.get("target_day") or "Thursday"),
                eligible_customer_ids=eligible_customer_ids,
            )
        )
    elif scenario_type == "facility_move":
        location = parameters.get("new_depot_location")
        new_lat = location.get("lat") if isinstance(location, dict) else None
        new_lng = location.get("lng") if isinstance(location, dict) else None
        if new_lat is None:
            new_lat = parameters.get("new_depot_lat")
        if new_lng is None:
            new_lng = parameters.get("new_depot_lng")
        if new_lat is None or new_lng is None:
            raise ValueError("facility_move requires a new depot location")
        result["scenario_depot_overrides"].extend(
            _depot_move_rows(
                scenario_id=scenario_id,
                depot_id=depot_id,
                new_lat=float(new_lat),
                new_lng=float(new_lng),
                preserve_service_windows=bool(parameters.get("preserve_service_windows", True)),
            )
        )
    elif scenario_type == "custom":
        changes = parameters.get("changes") or []
        if not isinstance(changes, list):
            raise ValueError("custom scenario parameters.changes must be a list")
        for change in changes:
            if not isinstance(change, dict):
                continue
            _apply_custom_change(
                result,
                change=change,
                scenario_id=scenario_id,
                depot_id=depot_id,
                delivery_day=delivery_day,
                depot=depot,
                eligible_customer_ids=eligible_customer_ids,
            )
        # Convenience: allow top-level cost on custom scenarios.
        cost = parameters.get("cost")
        if isinstance(cost, dict):
            result["scenario_cost_overrides"].extend(
                _cost_override_rows(scenario_id=scenario_id, cost=cost)
            )

    # Cost overrides can also ride on any scenario type via parameters["cost"].
    if scenario_type != "custom":
        cost = parameters.get("cost")
        if isinstance(cost, dict):
            result["scenario_cost_overrides"].extend(
                _cost_override_rows(scenario_id=scenario_id, cost=cost)
            )

    return result


def seed_override_tables(customers: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    strategic = [row for row in customers if row["depot_id"] == "DPT_NORTH"][:4]
    flexible = [row for row in customers if row["depot_id"] == "DPT_NORTH"][8:14]
    customer_overrides: list[dict[str, object]] = []
    for idx in range(1, 5):
        customer_overrides.append(
            {
                "scenario_id": "scn_ma_newcustomers",
                "override_type": "add_customer",
                "customer_id": f"NEW-MA-{idx:03d}",
                "customer_name": f"Acquired Retailer {idx}",
                "depot_id": "DPT_NORTH",
                "lat": 42.3314 + 0.07 + idx * 0.015,
                "lng": -83.0458 - 0.11 - idx * 0.02,
                "delivery_day": "Tuesday",
                "demand_cases": 95,
                "service_minutes": 30,
                "receiving_window_start": "08:00",
                "receiving_window_end": "16:00",
            }
        )
    for idx in range(1, 5):
        customer_overrides.append(
            {
                "scenario_id": "scn_new_customer_growth",
                "override_type": "add_customer",
                "customer_id": f"NEW-GROWTH-{idx:03d}",
                "customer_name": f"Growth Account {idx}",
                "depot_id": "DPT_NORTH",
                "lat": 42.3314 + 0.04 + idx * 0.012,
                "lng": -83.0458 + 0.18 + idx * 0.018,
                "delivery_day": "Tuesday",
                "demand_cases": 80,
                "service_minutes": 25,
                "receiving_window_start": "09:00",
                "receiving_window_end": "17:00",
            }
        )
    for idx in range(1, 6):
        customer_overrides.append(
            {
                "scenario_id": "scn_custom_composite",
                "override_type": "add_customer",
                "customer_id": f"NEW-CUSTOM-{idx:03d}",
                "customer_name": f"Composite Delivery {idx}",
                "depot_id": "DPT_NORTH",
                "lat": 42.3314 + 0.08 + idx * 0.012,
                "lng": -83.0458 + 0.10 + idx * 0.015,
                "delivery_day": "Tuesday",
                "demand_cases": 85,
                "service_minutes": 28,
                "receiving_window_start": "08:00",
                "receiving_window_end": "16:00",
            }
        )
    for row in strategic:
        customer_overrides.append(
            {
                "scenario_id": "scn_day_change",
                "override_type": "customer_priority",
                "customer_id": row["customer_id"],
                "delivery_day": "Thursday",
            }
        )
    fleet_overrides = [
        {
            "scenario_id": "scn_driver_minus_one",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "driver_delta": -1,
            "vehicle_delta": -1,
            "allow_overtime": True,
        },
        {
            "scenario_id": "scn_custom_composite",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "driver_delta": -1,
            "vehicle_delta": -1,
            "allow_overtime": True,
        },
    ]
    depot_overrides = [
        {
            "scenario_id": "scn_facility_move",
            "depot_id": "DPT_NORTH",
            "new_lat": 41.8000,
            "new_lng": -84.8000,
            "preserve_service_windows": True,
        }
    ]
    frequency_overrides = [
        {
            "scenario_id": "scn_day_change",
            "customer_id": row["customer_id"],
            "baseline_day": "Tuesday",
            "scenario_day": "Thursday",
        }
        for row in flexible
    ]
    cost_overrides = [
        {
            "scenario_id": "scn_custom_composite",
            "cost_per_mile": 4.5,
            "labor_regular_hour": None,
            "overtime_multiplier": None,
            "overtime_threshold_minutes": None,
            "fixed_truck_daily_cost": None,
            "late_delivery_penalty": None,
            "missed_delivery_penalty": None,
        }
    ]
    return {
        "scenario_customer_overrides": customer_overrides,
        "scenario_fleet_overrides": fleet_overrides,
        "scenario_depot_overrides": depot_overrides,
        "scenario_frequency_overrides": frequency_overrides,
        "scenario_cost_overrides": cost_overrides,
    }


def apply_overrides(
    *,
    scenario: dict[str, object],
    customers: list[dict[str, object]],
    depots: list[dict[str, object]],
    fleet: list[dict[str, object]],
    orders: list[dict[str, object]],
    override_tables: dict[str, list[dict[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    """Materialize planning inputs from override rows.

    Applies each override family by row presence for the scenario, not by
    scenario_type, so custom/composites and presets share one code path.
    """
    scenario_id = str(scenario["scenario_id"])
    depot_id = str(scenario["depot_id"])
    delivery_day = str(scenario["delivery_day"])
    planning_customers = [copy.deepcopy(row) for row in customers]
    planning_depots = [copy.deepcopy(row) for row in depots]
    planning_fleet = [copy.deepcopy(row) for row in fleet]
    planning_orders = [copy.deepcopy(row) for row in orders]

    if scenario_id == BASELINE_SCENARIO_ID:
        return _scope_planning(
            scenario_id,
            depot_id,
            delivery_day,
            planning_customers,
            planning_depots,
            planning_fleet,
            planning_orders,
        )

    for override in override_tables.get("scenario_customer_overrides", []):
        if override.get("scenario_id") != scenario_id or override.get("override_type") != "add_customer":
            continue
        planning_customers.append(
            {
                "customer_id": override["customer_id"],
                "customer_name": override["customer_name"],
                "depot_id": override["depot_id"],
                "region": "Great Lakes",
                "sales_territory": "North Metro",
                "lat": override["lat"],
                "lng": override["lng"],
                "customer_priority": "key",
                "delivery_frequency": 1,
                "eligible_delivery_days": delivery_day,
                "receiving_window_start": override["receiving_window_start"],
                "receiving_window_end": override["receiving_window_end"],
                "service_minutes": override["service_minutes"],
                "special_handling": "none",
                "source_system": "scenario_override",
                "is_inferred": False,
                "confidence_level": "high",
                "generated_run_id": scenario_id,
                "is_new_customer": True,
            }
        )
        planning_orders.append(
            {
                "order_id": f"ORD-{override['customer_id']}",
                "customer_id": override["customer_id"],
                "depot_id": override["depot_id"],
                "delivery_day": override.get("delivery_day") or delivery_day,
                "route_date": "2026-07-07",
                "demand_cases": override["demand_cases"],
                "product_family": "cartons",
                "source_system": "scenario_override",
                "is_inferred": False,
                "confidence_level": "high",
                "generated_run_id": scenario_id,
            }
        )

    for override in override_tables.get("scenario_fleet_overrides", []):
        if override.get("scenario_id") != scenario_id:
            continue
        vehicle_delta = int(override.get("vehicle_delta") or 0)
        eligible = [row for row in planning_fleet if row["depot_id"] == depot_id]
        if vehicle_delta < 0:
            remove_count = abs(vehicle_delta)
            remove_ids = {row["vehicle_id"] for row in eligible[-remove_count:]}
            planning_fleet = [row for row in planning_fleet if row["vehicle_id"] not in remove_ids]
        elif vehicle_delta > 0:
            # Clone existing vehicles for positive deltas so capacity grows.
            for idx in range(1, vehicle_delta + 1):
                if not eligible:
                    break
                template = copy.deepcopy(eligible[(idx - 1) % len(eligible)])
                template["vehicle_id"] = f"{template['vehicle_id']}-ADD-{idx}"
                template["source_system"] = "scenario_override"
                template["generated_run_id"] = scenario_id
                planning_fleet.append(template)

    change_map = {
        row["customer_id"]: row["scenario_day"]
        for row in override_tables.get("scenario_frequency_overrides", [])
        if row.get("scenario_id") == scenario_id
    }
    if change_map:
        for order in planning_orders:
            if order["customer_id"] in change_map and order["delivery_day"] == delivery_day:
                order["delivery_day"] = change_map[order["customer_id"]]

    for override in override_tables.get("scenario_depot_overrides", []):
        if override.get("scenario_id") != scenario_id:
            continue
        for depot in planning_depots:
            if depot["depot_id"] == depot_id:
                depot["lat"] = override["new_lat"]
                depot["lng"] = override["new_lng"]
                depot["is_inferred"] = False
                depot["confidence_level"] = "high"

    return _scope_planning(
        scenario_id,
        depot_id,
        delivery_day,
        planning_customers,
        planning_depots,
        planning_fleet,
        planning_orders,
    )


def resolve_cost_override(
    override_tables: dict[str, list[dict[str, object]]],
    scenario_id: str,
) -> dict[str, object]:
    """Return the first non-empty cost override row for a scenario as a sparse dict."""
    for row in override_tables.get("scenario_cost_overrides", []):
        if row.get("scenario_id") != scenario_id:
            continue
        return {
            field: row[field]
            for field in COST_OVERRIDE_FIELDS
            if field in row and row[field] is not None
        }
    return {}


def _scope_planning(
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    customers: list[dict[str, object]],
    depots: list[dict[str, object]],
    fleet: list[dict[str, object]],
    orders: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    scoped_orders = [
        {**row, "scenario_id": scenario_id}
        for row in orders
        if row["depot_id"] == depot_id and row["delivery_day"] == delivery_day
    ]
    customer_ids = {row["customer_id"] for row in scoped_orders}
    scoped_customers = [
        {**row, "scenario_id": scenario_id, "is_new_customer": bool(row.get("is_new_customer", False))}
        for row in customers
        if row["customer_id"] in customer_ids
    ]
    scoped_depots = [
        {**row, "scenario_id": scenario_id}
        for row in depots
        if row["depot_id"] == depot_id
    ]
    scoped_fleet = [
        {**row, "scenario_id": scenario_id}
        for row in fleet
        if row["depot_id"] == depot_id and delivery_day in str(row["available_days"]).split(",")
    ]
    return {
        "scenario_planning_customers": scoped_customers,
        "scenario_planning_depots": scoped_depots,
        "scenario_planning_fleet": scoped_fleet,
        "scenario_planning_stops": scoped_orders,
    }
