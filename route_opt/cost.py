from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class CostParameters:
    cost_per_mile: float = 3.0
    labor_regular_hour: float = 80.0
    overtime_multiplier: float = 1.5
    overtime_threshold_minutes: int = 480
    fixed_truck_daily_cost: float = 340.0
    max_route_minutes: int = 600
    late_delivery_penalty: float = 75.0
    missed_delivery_penalty: float = 400.0
    avg_speed_mph: float = 38.0
    circuity: float = 1.3

    def as_row(self, generated_run_id: str = "seeded-v0") -> dict[str, object]:
        row = asdict(self)
        row.update(
            {
                "parameter_set_id": "default",
                "source_system": "python_synthetic_generator",
                "is_inferred": False,
                "confidence_level": "high",
                "generated_run_id": generated_run_id,
            }
        )
        return row


def route_cost(
    *,
    miles: float,
    route_minutes: int,
    late_stops: int = 0,
    missed_stops: int = 0,
    params: CostParameters | None = None,
) -> dict[str, float]:
    params = params or CostParameters()
    overtime_minutes = max(0, route_minutes - params.overtime_threshold_minutes)
    regular_minutes = max(
        min(route_minutes, params.overtime_threshold_minutes),
        params.overtime_threshold_minutes,
    )
    mileage_cost = miles * params.cost_per_mile
    labor_cost = (regular_minutes / 60.0) * params.labor_regular_hour
    overtime_cost = (
        (overtime_minutes / 60.0)
        * params.labor_regular_hour
        * params.overtime_multiplier
    )
    fixed_vehicle_cost = params.fixed_truck_daily_cost
    sla_penalty_cost = (
        late_stops * params.late_delivery_penalty
        + missed_stops * params.missed_delivery_penalty
    )
    total_cost = (
        mileage_cost
        + labor_cost
        + overtime_cost
        + fixed_vehicle_cost
        + sla_penalty_cost
    )
    return {
        "mileage_cost": round(mileage_cost, 2),
        "labor_cost": round(labor_cost, 2),
        "overtime_cost": round(overtime_cost, 2),
        "fixed_vehicle_cost": round(fixed_vehicle_cost, 2),
        "sla_penalty_cost": round(sla_penalty_cost, 2),
        "total_cost": round(total_cost, 2),
        "overtime_minutes": overtime_minutes,
    }


def total_cost_is_consistent(row: dict[str, float], tolerance: float = 0.01) -> bool:
    expected = (
        row["mileage_cost"]
        + row["labor_cost"]
        + row["overtime_cost"]
        + row["fixed_vehicle_cost"]
        + row["sla_penalty_cost"]
    )
    return abs(expected - row["total_cost"]) <= tolerance
