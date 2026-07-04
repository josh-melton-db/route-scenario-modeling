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
from route_opt.matrix import build_travel_matrix
from route_opt.spark_io import collect_dicts, write_rows_as_table

config = config_from_widgets()
scenario_filter = get_widget_value("scenario_id", "").strip()

depots = collect_dicts(spark.table(config.table("scenario_planning_depots")))
customers = collect_dicts(spark.table(config.table("scenario_planning_customers")))
if scenario_filter:
    depots = [row for row in depots if row["scenario_id"] == scenario_filter]
    customers = [row for row in customers if row["scenario_id"] == scenario_filter]

nodes = []
matrix_rows = []
for depot in depots:
    scenario_id = depot["scenario_id"]
    depot_id = depot["depot_id"]
    day_customers = [
        row
        for row in customers
        if row["scenario_id"] == scenario_id and row["depot_id"] == depot_id
    ]
    node_rows, arc_rows = build_travel_matrix(
        scenario_id=scenario_id,
        depot=depot,
        stops=day_customers,
        delivery_day="Tuesday",
    )
    nodes.extend(node_rows)
    matrix_rows.extend(arc_rows)

replace_where = f"scenario_id = '{scenario_filter}'" if scenario_filter else None
write_rows_as_table(spark, nodes, config.table("matrix_nodes"), replace_where=replace_where)
write_rows_as_table(spark, matrix_rows, config.table("travel_time_matrix"), replace_where=replace_where)

print(f"Built {len(nodes)} matrix nodes and {len(matrix_rows)} matrix arcs for {scenario_filter or 'all scenarios'}.")
