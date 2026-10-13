# Databricks notebook source
# MAGIC %pip install faker==40.38.0

# COMMAND ----------
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
from route_opt.spark_io import write_rows_as_parquet
from route_opt.synthetic import generate_all

config = config_from_widgets()

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {config.catalog}.{config.schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {config.catalog}.{config.schema}.{config.raw_volume}")

tables = generate_all(seed=42, customer_count=250, network_scope="national")
for table_name, rows in tables.items():
    write_rows_as_parquet(spark, rows, f"{config.raw_path}/{table_name}")

# The medallion pipeline owns the gold tables and network_bootstrap owns the
# canonical network tables, so this task only lands raw data.
print(f"Generated {len(tables)} raw datasets under {config.raw_path}")
