# Databricks notebook source
"""Request saved routes through the App, using its existing Lakebase/solver setup."""
from datetime import date, datetime
import json
import time
from zoneinfo import ZoneInfo

import requests
from databricks.sdk import WorkspaceClient

dbutils.widgets.text("app_name", "route-scenario-modeling")  # type: ignore[name-defined]
dbutils.widgets.text("service_date", "today")  # type: ignore[name-defined]
dbutils.widgets.text("timezone", "America/Indiana/Indianapolis")  # type: ignore[name-defined]

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


def request(method, path, body=None):
    # Refresh auth headers on each poll; never print credentials or response HTML.
    response = requests.request(method, f"{app_url}/api/network/baseline/{path}",
        headers=workspace.config.authenticate(), json=body, timeout=30, allow_redirects=False)
    if response.status_code not in {200, 202}:
        raise RuntimeError(f"App request failed: HTTP {response.status_code}. Job run-as identity needs CAN_USE on the App.")
    if "application/json" not in response.headers.get("content-type", ""):
        raise RuntimeError("App did not return JSON; check Job run-as identity access to the App.")
    return response.json()


status = request("POST", "depot-routes/prepare", {
    "service_date": None if selected_date == "first" else selected_date,
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
