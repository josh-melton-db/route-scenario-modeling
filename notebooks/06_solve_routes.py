# Databricks notebook source
import sys
import json
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

import mlflow
import pandas as pd

from route_opt.config import config_from_widgets, get_widget_value
from route_opt.cost import CostParameters
from route_opt.overrides import resolve_cost_override
from route_opt.solver.payload import OUTPUT_COLUMNS, make_input_row
from route_opt.spark_io import collect_dicts, write_rows_as_table

config = config_from_widgets()
solver_model_name = get_widget_value("solver_model_name", f"{config.catalog}.{config.schema}.route_solver")
solver_model_alias = get_widget_value("solver_model_alias", "champion")
scenario_filter = get_widget_value("scenario_id", "").strip()

depots = collect_dicts(spark.table(config.table("scenario_planning_depots")))
customers = collect_dicts(spark.table(config.table("scenario_planning_customers")))
fleet = collect_dicts(spark.table(config.table("scenario_planning_fleet")))
stops = collect_dicts(spark.table(config.table("scenario_planning_stops")))
matrix_rows = collect_dicts(spark.table(config.table("travel_time_matrix")))
base_cost_rows = collect_dicts(spark.table(config.table("cost_parameters")))
try:
    cost_override_rows = collect_dicts(spark.table(config.table("scenario_cost_overrides")))
except Exception:
    cost_override_rows = []
if scenario_filter:
    depots = [row for row in depots if row["scenario_id"] == scenario_filter]
    customers = [row for row in customers if row["scenario_id"] == scenario_filter]
    fleet = [row for row in fleet if row["scenario_id"] == scenario_filter]
    stops = [row for row in stops if row["scenario_id"] == scenario_filter]
    matrix_rows = [row for row in matrix_rows if row["scenario_id"] == scenario_filter]
    cost_override_rows = [row for row in cost_override_rows if row["scenario_id"] == scenario_filter]

base_cost = CostParameters.from_row(base_cost_rows[0] if base_cost_rows else None)

mlflow.set_registry_uri("databricks-uc")
solver_model = mlflow.pyfunc.load_model(f"models:/{solver_model_name}@{solver_model_alias}")

routes = []
route_stops = []
unassigned = []
diagnostics = []

for depot in depots:
    scenario_id = depot["scenario_id"]
    depot_id = depot["depot_id"]
    delivery_day = "Tuesday"
    partition_customers = [
        row for row in customers if row["scenario_id"] == scenario_id and row["depot_id"] == depot_id
    ]
    partition_fleet = [
        row for row in fleet if row["scenario_id"] == scenario_id and row["depot_id"] == depot_id
    ]
    partition_stops = [
        row for row in stops if row["scenario_id"] == scenario_id and row["depot_id"] == depot_id
    ]
    partition_matrix = [
        row
        for row in matrix_rows
        if row["scenario_id"] == scenario_id and row["depot_id"] == depot_id and row["delivery_day"] == delivery_day
    ]
    scenario_cost = base_cost.merged(
        resolve_cost_override(
            {"scenario_cost_overrides": cost_override_rows},
            str(scenario_id),
        )
    )
    # Keep this as a small driver-side loop for the v0 demo. Once payloads
    # stabilize, the same row contract can be passed through applyInPandas.
    model_input = pd.DataFrame(
        [
            make_input_row(
                scenario_id=scenario_id,
                depot_id=depot_id,
                delivery_day=delivery_day,
                planning_depots=[depot],
                planning_customers=partition_customers,
                planning_fleet=partition_fleet,
                planning_stops=partition_stops,
                travel_matrix=partition_matrix,
                cost_parameters=scenario_cost.as_dict(),
            )
        ]
    )
    for column in [
        "scenario_id",
        "depot_id",
        "delivery_day",
        "planning_depots",
        "planning_customers",
        "planning_fleet",
        "planning_stops",
        "travel_matrix",
        "cost_parameters",
    ]:
        model_input[column] = model_input[column].astype(object)
    model_input["time_limit_seconds"] = model_input["time_limit_seconds"].astype("int64")
    prediction = solver_model.predict(model_input).iloc[0].to_dict()
    solution = {column: json.loads(prediction[column]) for column in OUTPUT_COLUMNS}
    routes.extend(solution["routes"])
    route_stops.extend(solution["route_stops"])
    unassigned.extend(solution["unassigned_stops"])
    diagnostics.extend(solution["diagnostics"])

replace_where = f"scenario_id = '{scenario_filter}'" if scenario_filter else None
write_rows_as_table(spark, routes, config.table("optimized_routes"), replace_where=replace_where)
write_rows_as_table(spark, route_stops, config.table("optimized_route_stops"), replace_where=replace_where)
write_rows_as_table(spark, routes, config.table("optimized_route_metrics"), replace_where=replace_where)
write_rows_as_table(spark, unassigned, config.table("optimized_unassigned_stops"), replace_where=replace_where)
write_rows_as_table(spark, diagnostics, config.table("optimization_solver_diagnostics"), replace_where=replace_where)
write_rows_as_table(spark, diagnostics, config.table("optimizer_runs"), replace_where=replace_where)

print(f"Solved {len(routes)} routes across {len(depots)} scenario partitions for {scenario_filter or 'all scenarios'}.")
