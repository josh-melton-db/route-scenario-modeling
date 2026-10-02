# Databricks notebook source
import json
import sys
from pathlib import PurePosixPath

dbutils.widgets.text("catalog", "demos")
dbutils.widgets.text("schema", "route_scenario_modeling")
notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
root = str(PurePosixPath(notebook_path).parent.parent)
if not root.startswith("/Workspace/"):
    root = "/Workspace" + root
sys.path.insert(0, root)

from route_opt.network_bootstrap import bootstrap_network_tables
from route_opt.network_synthetic import national_dataset_cached

result = bootstrap_network_tables(
    spark,
    national_dataset_cached(),
    catalog=dbutils.widgets.get("catalog"),
    schema=dbutils.widgets.get("schema"),
)
dbutils.notebook.exit(json.dumps(result))
