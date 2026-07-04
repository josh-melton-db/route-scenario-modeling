from __future__ import annotations

from .cost import total_cost_is_consistent
from .ranges import validate_baseline_near_median, validate_metric_ranges


def validate_kpi_contract(kpis: dict[str, object], *, baseline: bool = False) -> list[str]:
    flat = dict(kpis)
    cost_breakdown = flat.pop("cost_breakdown", {})
    if isinstance(cost_breakdown, dict):
        flat.update(cost_breakdown)
    failures = validate_metric_ranges({k: float(v) for k, v in flat.items() if isinstance(v, (int, float))})
    if baseline:
        failures.extend(
            validate_baseline_near_median(
                {k: float(v) for k, v in flat.items() if isinstance(v, (int, float))}
            )
        )
    if isinstance(cost_breakdown, dict) and not total_cost_is_consistent(cost_breakdown):  # type: ignore[arg-type]
        failures.append("total_cost does not equal the sum of cost components")
    if float(flat.get("avg_capacity_utilization_pct", 0)) > 100:
        failures.append("capacity utilization exceeds 100%")
    if float(flat.get("avg_driver_utilization_pct", 0)) > 100:
        failures.append("driver utilization exceeds 100%")
    if baseline and int(flat.get("missed_windows", 0)) != 0:
        failures.append("baseline missed_windows must be 0")
    return failures


def assert_no_dq_failures(failures: list[str]) -> None:
    if failures:
        joined = "\n".join(f"- {failure}" for failure in failures)
        raise AssertionError(f"Metric validation failed:\n{joined}")
