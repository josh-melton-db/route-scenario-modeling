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
    bundle_root = "."
    candidates = [bundle_root]

import mlflow
import pandas as pd
from mlflow.models.signature import ModelSignature
from mlflow.tracking import MlflowClient
from mlflow.types.schema import ColSpec, Schema

from route_opt.config import config_from_widgets, get_widget_value
from route_opt.solver.pyfunc_model import RouteScenarioSolverModel, make_input_row

config = config_from_widgets()
solver_model_name = get_widget_value("solver_model_name", f"{config.catalog}.{config.schema}.route_solver")
solver_model_alias = get_widget_value("solver_model_alias", "champion")

mlflow.set_registry_uri("databricks-uc")

input_example = pd.DataFrame(
    [
        make_input_row(
            scenario_id="example",
            depot_id="DPT_EXAMPLE",
            delivery_day="Tuesday",
            planning_depots=[
                {
                    "scenario_id": "example",
                    "depot_id": "DPT_EXAMPLE",
                    "depot_name": "Example Depot",
                    "region": "Example",
                    "sales_territory": "Example",
                    "lat": 42.3314,
                    "lng": -83.0458,
                }
            ],
            planning_customers=[
                {
                    "scenario_id": "example",
                    "customer_id": "CUST-001",
                    "customer_name": "Example Customer",
                    "depot_id": "DPT_EXAMPLE",
                    "region": "Example",
                    "sales_territory": "Example",
                    "lat": 42.35,
                    "lng": -83.02,
                    "customer_priority": "standard",
                    "receiving_window_start": "08:00",
                    "receiving_window_end": "16:00",
                    "service_minutes": 20,
                    "is_new_customer": False,
                }
            ],
            planning_fleet=[
                {
                    "scenario_id": "example",
                    "vehicle_id": "VEH-001",
                    "depot_id": "DPT_EXAMPLE",
                    "capacity_cases": 1000,
                    "fixed_truck_daily_cost": 340.0,
                    "max_route_minutes": 600,
                    "available_days": "Tuesday",
                }
            ],
            planning_stops=[
                {
                    "scenario_id": "example",
                    "order_id": "ORD-001",
                    "customer_id": "CUST-001",
                    "depot_id": "DPT_EXAMPLE",
                    "delivery_day": "Tuesday",
                    "route_date": "2026-07-07",
                    "demand_cases": 100,
                }
            ],
            time_limit_seconds=1,
        )
    ]
)
signature = ModelSignature(
    inputs=Schema(
        [
            ColSpec("string", "scenario_id"),
            ColSpec("string", "depot_id"),
            ColSpec("string", "delivery_day"),
            ColSpec("string", "planning_depots"),
            ColSpec("string", "planning_customers"),
            ColSpec("string", "planning_fleet"),
            ColSpec("string", "planning_stops"),
            ColSpec("string", "travel_matrix"),
            ColSpec("long", "time_limit_seconds"),
        ]
    ),
    outputs=Schema(
        [
            ColSpec("string", "scenario_id"),
            ColSpec("string", "depot_id"),
            ColSpec("string", "delivery_day"),
            ColSpec("string", "routes"),
            ColSpec("string", "route_stops"),
            ColSpec("string", "unassigned_stops"),
            ColSpec("string", "diagnostics"),
        ]
    ),
)
with mlflow.start_run(run_name="register-route-solver-pyfunc") as run:
    model_kwargs = {
        "artifact_path": "route_solver",
        "python_model": RouteScenarioSolverModel(),
        "pip_requirements": ["mlflow", "numpy<2", "ortools==9.8.3296", "pandas"],
        "signature": signature,
        "registered_model_name": solver_model_name,
    }
    code_root = next((candidate for candidate in candidates if candidate.startswith("/Workspace/")), bundle_root)
    code_path = str(PurePosixPath(code_root) / "route_opt")
    try:
        model_info = mlflow.pyfunc.log_model(code_paths=[code_path], **model_kwargs)
    except TypeError as exc:
        if "code_paths" not in str(exc):
            raise
        model_info = mlflow.pyfunc.log_model(code_path=[code_path], **model_kwargs)
    mlflow.set_tags(
        {
            "catalog": config.catalog,
            "schema": config.schema,
            "solver": "ortools_cvrptw",
            "model_name": solver_model_name,
            "model_alias": solver_model_alias,
        }
    )

client = MlflowClient()
registered_version = getattr(model_info, "registered_model_version", None)
if registered_version is None:
    versions = client.search_model_versions(f"name = '{solver_model_name}'")
    registered_version = max(int(version.version) for version in versions)
client.set_registered_model_alias(solver_model_name, solver_model_alias, str(registered_version))

print(f"Registered {solver_model_name} version {registered_version} as @{solver_model_alias}.")
