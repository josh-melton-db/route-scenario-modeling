# Databricks notebook source
from __future__ import annotations

import sys
import time
from datetime import timedelta
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

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput,
    Route,
    ServedEntityInput,
    ServingEndpointAccessControlRequest,
    ServingEndpointPermissionLevel,
    ServingModelWorkloadType,
    TrafficConfig,
)
from mlflow.tracking import MlflowClient

from route_opt.config import config_from_widgets, get_widget_value

config = config_from_widgets()
solver_model_name = get_widget_value("solver_model_name", f"{config.catalog}.{config.schema}.route_solver")
solver_model_alias = get_widget_value("solver_model_alias", "champion")
endpoint_name = get_widget_value("route_solver_endpoint_name", "route-solver-dev")
app_service_principal_client_id = get_widget_value("app_service_principal_client_id", "").strip()
app_name = get_widget_value("app_name", "").strip()

mlflow_client = MlflowClient(registry_uri="databricks-uc")
try:
    model_version = mlflow_client.get_model_version_by_alias(
        solver_model_name,
        solver_model_alias,
    )
    registered_version = str(model_version.version)
except AttributeError:
    versions = mlflow_client.search_model_versions(f"name = '{solver_model_name}'")
    matching = [
        version
        for version in versions
        if solver_model_alias in (getattr(version, "aliases", None) or [])
    ]
    if not matching:
        raise ValueError(f"No {solver_model_name}@{solver_model_alias} model version found.")
    registered_version = str(max(int(version.version) for version in matching))

served_entity_name = f"{endpoint_name}-v{registered_version}".replace(".", "-").replace("_", "-")
served_entity = ServedEntityInput(
    name=served_entity_name,
    entity_name=solver_model_name,
    entity_version=registered_version,
    scale_to_zero_enabled=True,
    workload_size="Small",
    workload_type=ServingModelWorkloadType.CPU,
)
traffic = TrafficConfig(routes=[Route(served_entity_name=served_entity_name, traffic_percentage=100)])

workspace = WorkspaceClient()
if not app_service_principal_client_id:
    for candidate_app_name in [app_name, "route-scenario-modeling-dev", "route-scenario-modeling"]:
        if not candidate_app_name:
            continue
        try:
            app = workspace.apps.get(candidate_app_name)
        except Exception:
            continue
        app_service_principal_client_id = str(app.service_principal_client_id or "").strip()
        if app_service_principal_client_id:
            break
if not app_service_principal_client_id:
    for app in workspace.apps.list():
        if str(app.name or "").startswith("route-scenario-modeling"):
            app_service_principal_client_id = str(app.service_principal_client_id or "").strip()
            if app_service_principal_client_id:
                break

try:
    workspace.serving_endpoints.get(endpoint_name)
except NotFound:
    workspace.serving_endpoints.create_and_wait(
        name=endpoint_name,
        config=EndpointCoreConfigInput(
            name=endpoint_name,
            served_entities=[served_entity],
            traffic_config=traffic,
        ),
        timeout=timedelta(minutes=20),
    )
else:
    workspace.serving_endpoints.wait_get_serving_endpoint_not_updating(
        endpoint_name,
        timeout=timedelta(minutes=20),
    )
    for attempt in range(1, 6):
        try:
            workspace.serving_endpoints.update_config_and_wait(
                name=endpoint_name,
                served_entities=[served_entity],
                traffic_config=traffic,
                timeout=timedelta(minutes=20),
            )
            break
        except Exception as exc:
            if "currently being updated" not in str(exc) or attempt == 5:
                raise
            workspace.serving_endpoints.wait_get_serving_endpoint_not_updating(
                endpoint_name,
                timeout=timedelta(minutes=20),
            )
            time.sleep(15)

if app_service_principal_client_id:
    endpoint = workspace.serving_endpoints.get(endpoint_name)
    endpoint_id = str(getattr(endpoint, "id", None) or endpoint_name)
    workspace.serving_endpoints.update_permissions(
        serving_endpoint_id=endpoint_id,
        access_control_list=[
            ServingEndpointAccessControlRequest(
                service_principal_name=app_service_principal_client_id,
                permission_level=ServingEndpointPermissionLevel.CAN_QUERY,
            )
        ],
    )

print(
    f"Serving endpoint {endpoint_name} now serves {solver_model_name} "
    f"version {registered_version} from @{solver_model_alias}."
)
