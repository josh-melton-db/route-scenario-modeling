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
]

_GROWTH_ZONE_DIRECTIONS = {
    "east_corridor": (0.6, 1.0),
    "south_ring": (-1.0, 0.2),
    "north_suburbs": (1.0, -0.2),
}


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

    Mirrors the seed override patterns but is driven entirely by the scenario's
    own parameters so app-created scenarios materialize real changes instead of
    silently returning the baseline.
    """

    result: dict[str, list[dict[str, object]]] = {key: [] for key in OVERRIDE_TABLE_KEYS}

    if scenario_type in {"ma_new_customers", "new_customer_growth"}:
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
        base_lat = float(depot["lat"])
        base_lng = float(depot["lng"])
        lat_dir, lng_dir = _GROWTH_ZONE_DIRECTIONS.get(
            str(parameters.get("growth_zone") or "east_corridor"),
            _GROWTH_ZONE_DIRECTIONS["east_corridor"],
        )
        suffix = scenario_id[-6:]
        for idx in range(1, count + 1):
            result["scenario_customer_overrides"].append(
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

    elif scenario_type == "driver_count_change":
        driver_delta = int(parameters.get("driver_delta") or 0)
        result["scenario_fleet_overrides"].append(
            {
                "scenario_id": scenario_id,
                "depot_id": depot_id,
                "delivery_day": delivery_day,
                "driver_delta": driver_delta,
                "vehicle_delta": driver_delta,
                "allow_overtime": bool(parameters.get("allow_overtime", True)),
            }
        )

    elif scenario_type == "delivery_frequency_day_change":
        target_day = str(parameters.get("target_day") or "Thursday")
        for customer_id in list(eligible_customer_ids or [])[:6]:
            result["scenario_frequency_overrides"].append(
                {
                    "scenario_id": scenario_id,
                    "customer_id": str(customer_id),
                    "baseline_day": delivery_day,
                    "scenario_day": target_day,
                }
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
        result["scenario_depot_overrides"].append(
            {
                "scenario_id": scenario_id,
                "depot_id": depot_id,
                "new_lat": float(new_lat),
                "new_lng": float(new_lng),
                "preserve_service_windows": bool(parameters.get("preserve_service_windows", True)),
            }
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
        }
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
    return {
        "scenario_customer_overrides": customer_overrides,
        "scenario_fleet_overrides": fleet_overrides,
        "scenario_depot_overrides": depot_overrides,
        "scenario_frequency_overrides": frequency_overrides,
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
    scenario_id = str(scenario["scenario_id"])
    depot_id = str(scenario["depot_id"])
    delivery_day = str(scenario["delivery_day"])
    planning_customers = [copy.deepcopy(row) for row in customers]
    planning_depots = [copy.deepcopy(row) for row in depots]
    planning_fleet = [copy.deepcopy(row) for row in fleet]
    planning_orders = [copy.deepcopy(row) for row in orders]

    if scenario_id == BASELINE_SCENARIO_ID:
        return _scope_planning(scenario_id, depot_id, delivery_day, planning_customers, planning_depots, planning_fleet, planning_orders)

    if str(scenario["scenario_type"]) in {"ma_new_customers", "new_customer_growth"}:
        for override in override_tables["scenario_customer_overrides"]:
            if override["scenario_id"] != scenario_id or override["override_type"] != "add_customer":
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
                    "delivery_day": delivery_day,
                    "route_date": "2026-07-07",
                    "demand_cases": override["demand_cases"],
                    "product_family": "cartons",
                    "source_system": "scenario_override",
                    "is_inferred": False,
                    "confidence_level": "high",
                    "generated_run_id": scenario_id,
                }
            )

    if scenario["scenario_type"] == "driver_count_change":
        for override in override_tables["scenario_fleet_overrides"]:
            if override["scenario_id"] == scenario_id:
                remove_count = abs(int(override["vehicle_delta"]))
                eligible = [row for row in planning_fleet if row["depot_id"] == depot_id]
                remove_ids = {row["vehicle_id"] for row in eligible[-remove_count:]}
                planning_fleet = [row for row in planning_fleet if row["vehicle_id"] not in remove_ids]

    if scenario["scenario_type"] == "delivery_frequency_day_change":
        change_map = {
            row["customer_id"]: row["scenario_day"]
            for row in override_tables["scenario_frequency_overrides"]
            if row["scenario_id"] == scenario_id
        }
        for order in planning_orders:
            if order["customer_id"] in change_map and order["delivery_day"] == delivery_day:
                order["delivery_day"] = change_map[order["customer_id"]]

    if scenario["scenario_type"] == "facility_move":
        for override in override_tables["scenario_depot_overrides"]:
            if override["scenario_id"] == scenario_id:
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
