# Databricks notebook source
# MAGIC %pip install faker==40.38.0

# COMMAND ----------
"""Request saved routes through the App, using its existing Lakebase/solver setup."""
from datetime import date, datetime
import json
import os
import sys
from pathlib import PurePosixPath
import time
from zoneinfo import ZoneInfo

import requests
from databricks.sdk import WorkspaceClient

dbutils.widgets.text("app_name", "route-scenario-modeling")  # type: ignore[name-defined]
dbutils.widgets.text("service_date", "today")  # type: ignore[name-defined]
dbutils.widgets.text("catalog", "demos")  # type: ignore[name-defined]
dbutils.widgets.text("schema", "route_scenario_modeling")  # type: ignore[name-defined]
dbutils.widgets.dropdown("publish_daily_plans", "true", ["true", "false"])  # type: ignore[name-defined]
dbutils.widgets.text("timezone", "America/Indiana/Indianapolis")  # type: ignore[name-defined]

notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()  # type: ignore[name-defined]
root = str(PurePosixPath(notebook_path).parent.parent)
sys.path.insert(0, root if root.startswith("/Workspace/") else "/Workspace" + root)
from route_opt.app_notebook_auth import NotebookAppAuth

workspace = WorkspaceClient()
app = workspace.apps.get(name=dbutils.widgets.get("app_name"))  # type: ignore[name-defined]
app_url = str(app.url or "").rstrip("/")
if not app_url.startswith("https://"):
    raise RuntimeError("The Databricks App must be deployed and running before preparing routes.")
selected_date = dbutils.widgets.get("service_date")  # type: ignore[name-defined]
if selected_date == "today":
    selected_date = datetime.now(ZoneInfo(dbutils.widgets.get("timezone"))).date().isoformat()  # type: ignore[name-defined]
elif selected_date != "first":
    selected_date = date.fromisoformat(selected_date).isoformat()


publish_daily = dbutils.widgets.get("publish_daily_plans").lower() == "true"  # type: ignore[name-defined]
if publish_daily:
    if selected_date == "first":
        raise ValueError("Daily publication requires an explicit date or today.")
    # Resolve the generation anchor before importing modules that freeze IDs.
    os.environ["DEMO_DATE_ANCHOR"] = selected_date
    from route_opt.network_synthetic import national_dataset_cached
    from route_opt.network_bootstrap import publish_daily_network_plans
    publication = publish_daily_network_plans(
        spark, national_dataset_cached(),  # type: ignore[name-defined]
        catalog=dbutils.widgets.get("catalog"), schema=dbutils.widgets.get("schema"),  # type: ignore[name-defined]
    )
    print(json.dumps(publication, indent=2))


app_auth = NotebookAppAuth(
    workspace, str(app.oauth2_app_client_id or ""),
    # The documented exchange uses the notebook context PAT specifically.
    # Serverless SDK native credentials need not be this same token type.
    notebook_token=lambda: dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get(),  # type: ignore[name-defined]
)

def request(method, path, body=None):
    # Refresh auth headers on each poll; never print credentials or response HTML.
    response = requests.request(method, f"{app_url}/api/network/baseline/{path}",
        headers=app_auth.headers(), json=body, timeout=30, allow_redirects=False)
    if response.status_code not in {200, 202}:
        raise RuntimeError(f"App request failed: HTTP {response.status_code}. Job run-as identity needs CAN_USE on the App.")
    if "application/json" not in response.headers.get("content-type", ""):
        raise RuntimeError("App did not return JSON; check Job run-as identity access to the App.")
    return response.json()


status = request("POST", "depot-routes/prepare", {
    "service_date": None if selected_date == "first" else selected_date,
    "refresh_daily_baseline": publish_daily,
})
preparation_id = status["preparation_id"]
deadline = time.monotonic() + 1900
while status["state"] == "running":
    if time.monotonic() >= deadline:
        raise TimeoutError("Route preparation exceeded 1900 seconds; saved routes are retained.")
    time.sleep(5)
    status = request("GET", f"depot-routes/preparations/{preparation_id}")
print(json.dumps(status, indent=2))
if status["state"] != "completed":
    raise RuntimeError("Some depot routes could not be prepared; inspect the report above.")
