# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "4"
# ///
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

dbutils.widgets.text("app_auth_secret_scope", "route-scenario-modeling-depot-job")  # type: ignore[name-defined]
dbutils.widgets.text("app_auth_uc_secret_schema", "")  # type: ignore[name-defined]
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


def get_app_credentials(secrets, uc_secret_schema, secret_scope):
    uc_secret_schema = uc_secret_schema.strip()
    secret_scope = secret_scope.strip()
    if uc_secret_schema:
        parts = uc_secret_schema.split(".")
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise ValueError("app_auth_uc_secret_schema must be catalog.schema.")
        catalog, schema = parts
        credentials = {}
        for field, key in (("client_id", "depot_job_client_id"), ("client_secret", "depot_job_client_secret")):
            try:
                value = secrets.get(catalog=catalog, schema=schema, key=key)
            except TypeError:
                raise RuntimeError(
                    "Unity Catalog secret reads require serverless environment version 4 or later "
                    "(or DBR 17.3+); dbutils.secrets.get must accept catalog= and schema=."
                ) from None
            except Exception:
                raise RuntimeError(
                    f"Cannot read Unity Catalog secret {uc_secret_schema}.{key}. "
                    "Check that the key exists and the job run-as identity has USE CATALOG, "
                    "USE SCHEMA and READ SECRET."
                ) from None
            if not value:
                raise RuntimeError(
                    f"Unity Catalog secret {uc_secret_schema}.{key} is empty. "
                    "Check the key and the job run-as identity's READ SECRET privilege."
                ) from None
            credentials[field] = value
        return credentials
    if secret_scope:
        return {
            "client_id": secrets.get(scope=secret_scope, key="client-id"),
            "client_secret": secrets.get(scope=secret_scope, key="client-secret"),
        }
    return None


app_credentials = get_app_credentials(
    dbutils.secrets,  # type: ignore[name-defined]
    dbutils.widgets.get("app_auth_uc_secret_schema"),  # type: ignore[name-defined]
    dbutils.widgets.get("app_auth_secret_scope"),  # type: ignore[name-defined]
)
if app_credentials is not None:
    app_client = WorkspaceClient(
        host=workspace.config.host, auth_type="oauth-m2m",
        **app_credentials,
    )
    app_auth_headers = app_client.config.authenticate
else:
    # Optional notebook-token flow for workspaces that support this exchange.
    app_auth = NotebookAppAuth(
        workspace, str(app.oauth2_app_client_id or ""),
        notebook_token=lambda: dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get(),  # type: ignore[name-defined]
    )
    app_auth_headers = app_auth.headers


def request(method, path, body=None):
    # Refresh auth headers on each poll; never print credentials or response HTML.
    response = requests.request(method, f"{app_url}/api/network/baseline/{path}",
        headers=app_auth_headers(), json=body, timeout=30, allow_redirects=False)
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
