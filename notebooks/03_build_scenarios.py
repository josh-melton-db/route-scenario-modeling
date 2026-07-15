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
from route_opt.overrides import (
    COST_OVERRIDE_FIELDS,
    seed_override_tables,
    seed_scenario_definitions,
    seed_scenario_parameters,
)
from route_opt.spark_io import collect_dicts, write_rows_as_table
from pyspark.sql import types as T

config = config_from_widgets()

customers = collect_dicts(spark.table(config.table("dim_customers_augmented")))
override_tables = seed_override_tables(customers)

write_rows_as_table(spark, seed_scenario_definitions(), config.table("scenario_definitions"))
write_rows_as_table(spark, seed_scenario_parameters(), config.table("scenario_parameters"))
for table_name, rows in override_tables.items():
    if table_name == "scenario_cost_overrides" and not rows:
        # Explicit schema so an empty cost-override table still materializes.
        schema = T.StructType(
            [T.StructField("scenario_id", T.StringType(), False)]
            + [T.StructField(field, T.DoubleType(), True) for field in COST_OVERRIDE_FIELDS]
        )
        # overtime_threshold_minutes is an int in the dataclass; keep Double for Spark simplicity.
        spark.createDataFrame([], schema).write.mode("overwrite").option(
            "overwriteSchema", "true"
        ).saveAsTable(config.table(table_name))
        continue
    write_rows_as_table(spark, rows, config.table(table_name))

print("Seed scenarios and normalized override tables written.")
