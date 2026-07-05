# Databricks notebook source
from __future__ import annotations

import sys
from pathlib import PurePosixPath

from databricks.sdk import WorkspaceClient

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

config = config_from_widgets()
principal = get_widget_value("app_service_principal_client_id", "").strip()
app_name = get_widget_value("app_name", "").strip()
workspace = WorkspaceClient()

if not principal:
    for candidate_app_name in [app_name, "route-scenario-modeling-dev", "route-scenario-modeling"]:
        if not candidate_app_name:
            continue
        try:
            app = workspace.apps.get(candidate_app_name)
        except Exception:
            continue
        principal = str(app.service_principal_client_id or "").strip()
        if principal:
            break
if not principal:
    for app in workspace.apps.list():
        if str(app.name or "").startswith("route-scenario-modeling"):
            principal = str(app.service_principal_client_id or "").strip()
            if principal:
                break

if not principal:
    raise ValueError("app_service_principal_client_id is required.")

quoted_principal = f"`{principal.replace('`', '``')}`"

select_tables = [
    "dim_depots_augmented",
    "dim_customers_augmented",
    "dim_fleet_assets",
    "fact_delivery_orders",
    "baseline_route_daily_summary",
    "scenario_definitions",
    "scenario_parameters",
    "scenario_customer_overrides",
    "scenario_fleet_overrides",
    "scenario_depot_overrides",
    "scenario_frequency_overrides",
]

write_tables = [
    "scenario_definitions",
    "scenario_parameters",
    "scenario_customer_overrides",
    "scenario_fleet_overrides",
    "scenario_depot_overrides",
    "scenario_frequency_overrides",
    "app_scenario_results",
    "scenario_kpis",
    "scenario_comparison_summary",
    "scenario_route_delta",
    "scenario_customer_impact",
    "scenario_constraint_violations",
    "scenario_cost_breakdown",
]

for table_name in sorted(set(select_tables + write_tables)):
    spark.sql(f"GRANT SELECT ON TABLE {config.table(table_name)} TO {quoted_principal}")

for table_name in write_tables:
    spark.sql(f"GRANT MODIFY ON TABLE {config.table(table_name)} TO {quoted_principal}")

print(f"Granted app table permissions to {principal}.")
