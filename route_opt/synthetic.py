from __future__ import annotations

import math
import random
from datetime import date

try:
    from faker import Faker
except Exception:  # pragma: no cover - Faker is available in Databricks/job envs.
    Faker = None  # type: ignore[assignment]

from .cost import CostParameters
from .schemas import DAYS, stable_id

GENERATED_RUN_ID = "seeded-route-scenario-modeling-v0"
SOURCE_SYSTEM = "python_synthetic_generator"


def _source_fields(confidence_level: str = "high", is_inferred: bool = False) -> dict[str, object]:
    return {
        "source_system": SOURCE_SYSTEM,
        "is_inferred": is_inferred,
        "confidence_level": confidence_level,
        "generated_run_id": GENERATED_RUN_ID,
    }


def generate_depots() -> list[dict[str, object]]:
    depots = [
        ("DPT_NORTH", "North Depot", "Great Lakes", "North Metro", 42.3314, -83.0458),
        ("DPT_WEST", "West Depot", "Great Lakes", "West Metro", 42.9634, -85.6681),
        ("DPT_CENTRAL", "Central Depot", "Great Lakes", "Central Michigan", 42.7325, -84.5555),
    ]
    return [
        {
            "depot_id": depot_id,
            "depot_name": name,
            "region": region,
            "sales_territory": territory,
            "lat": lat,
            "lng": lng,
            "operating_calendar": "Mon-Fri",
            **_source_fields(),
        }
        for depot_id, name, region, territory, lat, lng in depots
    ]


def _customer_name(fake: object | None, idx: int) -> str:
    if fake is not None:
        try:
            return str(fake.company())
        except Exception:
            pass
    prefixes = ["Northline", "Parkview", "Orchard", "Summit", "Riverbend", "Lakeside"]
    suffixes = ["Foods", "Retail", "Market", "Grocery", "Depot", "Trade"]
    return f"{prefixes[idx % len(prefixes)]} {suffixes[(idx // len(prefixes)) % len(suffixes)]}"


def generate_customers(customer_count: int = 250, seed: int = 42) -> list[dict[str, object]]:
    rng = random.Random(seed)
    fake = Faker("en_US") if Faker is not None else None
    if fake is not None:
        fake.seed_instance(seed)
    depot_defs = generate_depots()
    customers: list[dict[str, object]] = []
    for idx in range(1, customer_count + 1):
        if idx <= 96:
            depot = depot_defs[0]
        elif idx <= 174:
            depot = depot_defs[1]
        else:
            depot = depot_defs[2]
        depot_lat = float(depot["lat"])
        depot_lng = float(depot["lng"])
        # Elliptical service areas with a few longer-tail stops to create realistic route lengths.
        if idx <= 24:
            radius = rng.triangular(0.03, 0.42, 0.12)
        else:
            radius = rng.triangular(0.03, 0.9, 0.18)
        theta = rng.uniform(0, math.tau)
        lat = depot_lat + radius * math.sin(theta) * 0.65
        lng = depot_lng + radius * math.cos(theta)
        priority_roll = rng.random()
        if priority_roll < 0.12:
            priority = "strategic"
        elif priority_roll < 0.45:
            priority = "key"
        else:
            priority = "standard"
        eligible_days = DAYS if priority != "strategic" else ["Monday", "Tuesday", "Wednesday", "Thursday"]
        # Force the contract anchor: first 24 North customers all appear on Tuesday.
        if idx <= 24:
            eligible_days = ["Tuesday"]
        elif idx <= 96:
            eligible_days = ["Monday", "Wednesday", "Thursday", "Friday"]
        service_minutes = rng.choice([20, 25, 30, 35])
        if priority == "strategic":
            service_minutes += 10
        window_start = rng.choice(["07:30", "08:00", "08:30", "09:00"])
        window_end = rng.choice(["14:30", "15:00", "16:00", "17:00"])
        confidence = "medium" if rng.random() < 0.15 else "high"
        customers.append(
            {
                "customer_id": stable_id("CUST", idx),
                "customer_name": _customer_name(fake, idx),
                "depot_id": depot["depot_id"],
                "region": depot["region"],
                "sales_territory": depot["sales_territory"],
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "customer_priority": priority,
                "delivery_frequency": rng.choice([1, 1, 1, 2, 3]),
                "eligible_delivery_days": ",".join(eligible_days),
                "receiving_window_start": window_start,
                "receiving_window_end": window_end,
                "service_minutes": service_minutes,
                "special_handling": rng.choice(["none", "none", "none", "liftgate", "cold_chain"]),
                **_source_fields(confidence_level=confidence, is_inferred=confidence == "medium"),
            }
        )
    return customers


def generate_fleet() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    asset_idx = 1
    for depot in generate_depots():
        vehicle_count = 4 if depot["depot_id"] == "DPT_NORTH" else 5
        for slot in range(vehicle_count):
            rows.append(
                {
                    "vehicle_id": stable_id("VEH", asset_idx),
                    "depot_id": depot["depot_id"],
                    "vehicle_type": "box_truck" if slot % 4 else "large_box_truck",
                    "capacity_cases": 900 if slot % 4 else 1100,
                    "fixed_truck_daily_cost": 340.0 if slot % 4 else 410.0,
                    "cost_per_mile": 3.0,
                    "max_route_minutes": 600,
                    "available_days": ",".join(DAYS),
                    **_source_fields(),
                }
            )
            asset_idx += 1
    return rows


def generate_drivers() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    driver_idx = 1
    for depot in generate_depots():
        driver_count = 4 if depot["depot_id"] == "DPT_NORTH" else 5
        for _ in range(driver_count):
            rows.append(
                {
                    "driver_id": stable_id("DRV", driver_idx),
                    "driver_name": f"Driver {driver_idx}",
                    "depot_id": depot["depot_id"],
                    "shift_start": "06:30",
                    "shift_end": "16:30",
                    "overtime_threshold_minutes": 480,
                    "labor_regular_hour": 80.0,
                    "available_days": ",".join(DAYS),
                    **_source_fields(),
                }
            )
            driver_idx += 1
    return rows


def generate_demand_and_orders(
    customers: list[dict[str, object]], seed: int = 42
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rng = random.Random(seed + 7)
    demand_rows: list[dict[str, object]] = []
    order_rows: list[dict[str, object]] = []
    order_idx = 1
    for customer in customers:
        eligible = str(customer["eligible_delivery_days"]).split(",")
        for day in DAYS:
            if day not in eligible:
                continue
            if int(str(customer["customer_id"]).split("-")[-1]) <= 24 and day == "Tuesday":
                # Sum first 24 Tuesday rows to 2840 cases, matching the current stub anchor.
                case_pattern = [130, 120, 110, 140, 95, 125, 115, 100] * 3
                case_pattern[-1] += 35
                cases = case_pattern[int(str(customer["customer_id"]).split("-")[-1]) - 1]
            else:
                cases = int(max(30, rng.lognormvariate(4.35, 0.35)))
            demand_rows.append(
                {
                    "customer_id": customer["customer_id"],
                    "depot_id": customer["depot_id"],
                    "delivery_day": day,
                    "expected_cases": cases,
                    "product_family": "cartons",
                    **_source_fields(),
                }
            )
            order_rows.append(
                {
                    "order_id": stable_id("ORD", order_idx, width=5),
                    "customer_id": customer["customer_id"],
                    "depot_id": customer["depot_id"],
                    "delivery_day": day,
                    "route_date": str(date(2026, 7, 7)),
                    "demand_cases": cases,
                    "product_family": "cartons",
                    **_source_fields(),
                }
            )
            order_idx += 1
    return demand_rows, order_rows


def generate_all(seed: int = 42, customer_count: int = 250) -> dict[str, list[dict[str, object]]]:
    customers = generate_customers(customer_count=customer_count, seed=seed)
    demand, orders = generate_demand_and_orders(customers, seed=seed)
    return {
        "depot_master": generate_depots(),
        "location_data": customers,
        "fleet_assets": generate_fleet(),
        "drivers": generate_drivers(),
        "fact_customer_product_demand": demand,
        "fact_delivery_orders": orders,
        "cost_parameters": [CostParameters().as_row(GENERATED_RUN_ID)],
    }
