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
from route_opt.metric_views import certification_sql, metric_view_sql

config = config_from_widgets()

for statement in metric_view_sql(config.catalog, config.schema):
    spark.sql(statement)

for statement in certification_sql(config.catalog, config.schema):
    try:
        spark.sql(statement)
    except Exception as exc:
        print(f"Metric view tag statement skipped: {exc}")

print("Metric views published.")
