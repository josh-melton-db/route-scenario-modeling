from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricRange:
    min_value: float
    median_value: float
    max_value: float
    unit: str
    tolerance_pct: float = 0.2

    def contains(self, value: float) -> bool:
        return self.min_value <= value <= self.max_value

    def near_median(self, value: float) -> bool:
        tolerance = abs(self.median_value) * self.tolerance_pct
        return (self.median_value - tolerance) <= value <= (
            self.median_value + tolerance
        )


METRIC_RANGES: dict[str, MetricRange] = {
    "route_count": MetricRange(3, 4, 6, "routes"),
    "driver_count": MetricRange(3, 4, 6, "drivers"),
    "vehicle_count": MetricRange(3, 4, 6, "vehicles"),
    "total_miles": MetricRange(150, 235, 440, "miles"),
    "drive_minutes": MetricRange(240, 370, 640, "minutes"),
    "service_minutes": MetricRange(400, 590, 840, "minutes"),
    "total_cases": MetricRange(1800, 2840, 4200, "cases"),
    "avg_stops_per_route": MetricRange(5, 6, 9, "stops/route"),
    "avg_capacity_utilization_pct": MetricRange(65, 82, 98, "percent"),
    "avg_driver_utilization_pct": MetricRange(70, 86, 100, "percent"),
    "overtime_minutes": MetricRange(0, 0, 200, "minutes", tolerance_pct=0),
    "missed_windows": MetricRange(0, 0, 0, "stops", tolerance_pct=0),
    "late_minutes": MetricRange(0, 0, 60, "minutes", tolerance_pct=0),
    "total_cost": MetricRange(3300, 4625, 7200, "USD"),
    "mileage_cost": MetricRange(450, 705, 1320, "USD"),
    "labor_cost": MetricRange(1800, 2580, 3600, "USD"),
    "overtime_cost": MetricRange(0, 0, 700, "USD", tolerance_pct=0),
    "fixed_vehicle_cost": MetricRange(1020, 1360, 2040, "USD"),
    "sla_penalty_cost": MetricRange(0, 0, 0, "USD", tolerance_pct=0),
}


def validate_metric_ranges(metrics: dict[str, float]) -> list[str]:
    failures: list[str] = []
    for name, bounds in METRIC_RANGES.items():
        if name not in metrics:
            continue
        value = float(metrics[name])
        if not bounds.contains(value):
            failures.append(
                f"{name}={value} outside [{bounds.min_value}, {bounds.max_value}] {bounds.unit}"
            )
    return failures


def validate_baseline_near_median(metrics: dict[str, float]) -> list[str]:
    failures: list[str] = []
    for name, bounds in METRIC_RANGES.items():
        if name not in metrics:
            continue
        value = float(metrics[name])
        if not bounds.near_median(value):
            failures.append(
                f"{name}={value} not near median {bounds.median_value} {bounds.unit}"
            )
    return failures
