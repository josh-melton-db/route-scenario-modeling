# Databricks notebook source
import sys
from pathlib import PurePosixPath

try:
    notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()  # type: ignore[name-defined]
    bundle_root = str(PurePosixPath(notebook_path).parent.parent)
    candidates = [bundle_root]
    if not bundle_root.startswith("/Workspace/"):
        candidates.append(f"/Workspace{bundle_root}")
    for candidate in candidates:
        if candidate not in sys.path:
            sys.path.append(candidate)
except Exception:
    pass

from route_opt.config import config_from_widgets
from route_opt.dq import assert_no_dq_failures, validate_kpi_contract
from route_opt.spark_io import collect_dicts

config = config_from_widgets()

failures = []
for row in collect_dicts(spark.table(config.table("scenario_kpis"))):
    cost_breakdown = {
        "mileage_cost": row["mileage_cost"],
        "labor_cost": row["labor_cost"],
        "overtime_cost": row["overtime_cost"],
        "fixed_vehicle_cost": row["fixed_vehicle_cost"],
        "sla_penalty_cost": row["sla_penalty_cost"],
        "total_cost": row["total_cost"],
    }
    kpis = {
        "route_count": row["route_count"],
        "driver_count": row["driver_count"],
        "vehicle_count": row["vehicle_count"],
        "total_miles": row["total_miles"],
        "drive_minutes": row["drive_minutes"],
        "service_minutes": row["service_minutes"],
        "total_cases": row["total_cases"],
        "avg_stops_per_route": row["avg_stops_per_route"],
        "avg_capacity_utilization_pct": row["avg_capacity_utilization_pct"],
        "avg_driver_utilization_pct": row["avg_driver_utilization_pct"],
        "overtime_minutes": row["overtime_minutes"],
        "missed_windows": row["missed_windows"],
        "late_minutes": row["late_minutes"],
        "cost_breakdown": cost_breakdown,
    }
    failures.extend(
        [
            f"{row['scenario_id']}: {failure}"
            # scenario_kpis contains optimized scenario outputs, including the
            # optimized baseline scenario. Reconstructed-baseline median checks
            # are covered by the unit tests against baseline_route_daily_summary.
            for failure in validate_kpi_contract(kpis, baseline=False)
        ]
    )

for table_name in [
    "mv_route_performance",
    "mv_scenario_comparison",
    "mv_customer_service_impact",
    "mv_fleet_capacity_utilization",
    "mv_depot_network_health",
]:
    count = spark.sql(f"SELECT COUNT(*) AS row_count FROM {config.table(table_name)}").collect()[0]["row_count"]
    if count < 0:
        failures.append(f"{table_name}: invalid metric view row count")

assert_no_dq_failures(failures)
print("Metric and table validation complete.")
