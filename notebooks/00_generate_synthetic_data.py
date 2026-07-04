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
from route_opt.spark_io import write_rows_as_parquet, write_rows_as_table
from route_opt.synthetic import generate_all

config = config_from_widgets()

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {config.catalog}.{config.schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {config.catalog}.{config.schema}.{config.raw_volume}")

tables = generate_all(seed=42, customer_count=250)
for table_name, rows in tables.items():
    write_rows_as_parquet(spark, rows, f"{config.raw_path}/{table_name}")

gold_table_map = {
    "dim_depots_augmented": tables["depot_master"],
    "dim_customers_augmented": tables["location_data"],
    "dim_customer_constraints": tables["location_data"],
    "dim_fleet_assets": tables["fleet_assets"],
    "dim_drivers": tables["drivers"],
    "fact_customer_product_demand": tables["fact_customer_product_demand"],
    "fact_delivery_orders": tables["fact_delivery_orders"],
    "cost_parameters": tables["cost_parameters"],
}
for table_name, rows in gold_table_map.items():
    write_rows_as_table(spark, rows, config.table(table_name))

print(f"Generated {len(tables)} raw datasets under {config.raw_path}")
