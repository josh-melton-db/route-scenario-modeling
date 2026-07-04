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

from route_opt.baseline import reconstruct_baseline
from route_opt.config import config_from_widgets
from route_opt.spark_io import collect_dicts, write_rows_as_table

config = config_from_widgets()

depots = collect_dicts(spark.table(config.table("dim_depots_augmented")))
customers = collect_dicts(spark.table(config.table("dim_customers_augmented")))
orders = collect_dicts(spark.table(config.table("fact_delivery_orders")))
fleet = collect_dicts(spark.table(config.table("dim_fleet_assets")))

baseline = reconstruct_baseline(depots, customers, orders, fleet)

write_rows_as_table(spark, baseline["routes"], config.table("baseline_routes"))
write_rows_as_table(spark, baseline["route_stops"], config.table("baseline_route_stops"))
write_rows_as_table(
    spark,
    [{"scenario_id": "baseline", "depot_id": "DPT_NORTH", "delivery_day": "Tuesday", **baseline["kpis"]}],
    config.table("baseline_route_kpis"),
)
write_rows_as_table(
    spark,
    [{
        "scenario_id": "baseline",
        "depot_id": "DPT_NORTH",
        "delivery_day": "Tuesday",
        "summary": baseline["network"]["summary"],
        "generated_at": baseline["network"]["generated_at"],
        "payload_json": baseline["network"],
    }],
    config.table("baseline_route_daily_summary"),
)

print("Baseline reconstruction complete.")
