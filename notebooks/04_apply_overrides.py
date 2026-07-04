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

from route_opt.config import config_from_widgets, get_widget_value
from route_opt.overrides import apply_overrides
from route_opt.spark_io import collect_dicts, write_rows_as_table

config = config_from_widgets()
scenario_filter = get_widget_value("scenario_id", "").strip()

depots = collect_dicts(spark.table(config.table("dim_depots_augmented")))
customers = collect_dicts(spark.table(config.table("dim_customers_augmented")))
fleet = collect_dicts(spark.table(config.table("dim_fleet_assets")))
orders = collect_dicts(spark.table(config.table("fact_delivery_orders")))
scenarios = collect_dicts(spark.table(config.table("scenario_definitions")))
if scenario_filter:
    scenarios = [row for row in scenarios if row["scenario_id"] == scenario_filter]
override_tables = {
    table_name: collect_dicts(spark.table(config.table(table_name)))
    for table_name in [
        "scenario_customer_overrides",
        "scenario_fleet_overrides",
        "scenario_depot_overrides",
        "scenario_frequency_overrides",
    ]
}

outputs = {
    "scenario_planning_customers": [],
    "scenario_planning_depots": [],
    "scenario_planning_fleet": [],
    "scenario_planning_stops": [],
}
for scenario in scenarios:
    materialized = apply_overrides(
        scenario=scenario,
        customers=customers,
        depots=depots,
        fleet=fleet,
        orders=orders,
        override_tables=override_tables,
    )
    for table_name, rows in materialized.items():
        outputs[table_name].extend(rows)

for table_name, rows in outputs.items():
    replace_where = f"scenario_id = '{scenario_filter}'" if scenario_filter else None
    write_rows_as_table(spark, rows, config.table(table_name), replace_where=replace_where)

print(f"Scenario planning tables materialized for {scenario_filter or 'all scenarios'}.")
