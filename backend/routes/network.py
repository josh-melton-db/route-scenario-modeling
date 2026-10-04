from __future__ import annotations

from datetime import date
import json
from time import perf_counter

from typing import Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import Response

from ..models import (
    NetworkLaneType,
    NetworkChargeAuditPage,
    NetworkMetric,
    NetworkOptions,
    NetworkOverview,
    NetworkScenario,
    NetworkScenarioCreateRequest,
    NetworkScenarioResult,
    NetworkScenarioRunResponse,
    NetworkRunLaunchRequest,
    NetworkRunRecord,
    NetworkScenarioUpdateRequest,
    NetworkDemandChange,
    NetworkDemandChangeCreateRequest,
    NetworkReleaseTarget,
)
from ..services.network_overview import network_overview_service
from ..services.network_scenarios import network_scenario_service
from ..services.demand_changes import demand_change_service
from ..services.network_run_jobs import network_run_manager

router = APIRouter(prefix="/network", tags=["network"])


@router.get("/options", response_model=NetworkOptions)
def network_options() -> NetworkOptions:
    return network_overview_service.get_options()


@router.get("/overview", response_model=NetworkOverview)
def network_overview(
    demand_plan_version_id: str | None = None,
    capacity_plan_version_id: str | None = None,
    horizon_start: date | None = None,
    horizon_end: date | None = None,
    region_id: str | None = None,
    lane_type: NetworkLaneType = "LINEHAUL",
    metric: NetworkMetric = "assigned_flow",
) -> NetworkOverview:
    return network_overview_service.get_overview(
        demand_plan_version_id=demand_plan_version_id,
        capacity_plan_version_id=capacity_plan_version_id,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        region_id=region_id,
        lane_type=lane_type,
        metric=metric,
    )


@router.get("/scenarios", response_model=list[NetworkScenario])
def network_scenarios() -> list[NetworkScenario]:
    return network_scenario_service.list()


@router.post(
    "/scenarios",
    response_model=NetworkScenario,
    status_code=status.HTTP_201_CREATED,
)
def create_network_scenario(
    payload: NetworkScenarioCreateRequest,
) -> NetworkScenario:
    return network_scenario_service.create(payload)


@router.get("/scenarios/{scenario_id}", response_model=NetworkScenario)
def network_scenario(scenario_id: str) -> NetworkScenario:
    return network_scenario_service.get(scenario_id)


@router.patch("/scenarios/{scenario_id}", response_model=NetworkScenario)
def update_network_scenario(
    scenario_id: str, payload: NetworkScenarioUpdateRequest
) -> NetworkScenario:
    return network_scenario_service.update(scenario_id, payload)


@router.post(
    "/scenarios/{scenario_id}/validate",
    response_model=NetworkScenario,
)
def validate_network_scenario(scenario_id: str) -> NetworkScenario:
    return network_scenario_service.validate(scenario_id)


@router.post(
    "/scenarios/{scenario_id}/run",
    response_model=NetworkRunRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_network_scenario(
    scenario_id: str, payload: NetworkRunLaunchRequest
) -> NetworkRunRecord:
    scenario = network_scenario_service.get(scenario_id)
    if scenario.revision != payload.expected_revision:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Scenario revision is stale.")
    return network_run_manager.launch(scenario)


@router.get("/run-requests/{run_id}", response_model=NetworkRunRecord)
def network_run_request(run_id: str) -> NetworkRunRecord:
    return network_run_manager.repository.get(run_id)


@router.post("/run-requests/{run_id}/cancel", response_model=NetworkRunRecord)
def cancel_network_run(run_id: str) -> NetworkRunRecord:
    return network_run_manager.cancel(run_id)


@router.get(
    "/scenarios/{scenario_id}/result",
    response_model=NetworkScenarioResult,
    response_model_exclude={"charge_details", "baseline_charge_details"},
)
def network_scenario_result(scenario_id: str) -> NetworkScenarioResult:
    return network_scenario_service.result(scenario_id)


@router.get(
    "/runs/{run_id}",
    response_model=NetworkScenarioResult,
    response_model_exclude={"charge_details", "baseline_charge_details"},
)
def network_run_result(run_id: str) -> Response:
    result = network_scenario_service.run_result(run_id)
    payload = result.model_dump(
        mode="json", exclude={"charge_details", "baseline_charge_details"}
    )
    started = perf_counter()
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    elapsed = perf_counter() - started
    network_run_manager.repository.record_api_response(
        run_id, encoding_seconds=elapsed, payload_bytes=len(encoded)
    )
    return Response(content=encoded, media_type="application/json")


@router.get("/runs/{run_id}/charges", response_model=NetworkChargeAuditPage)
def network_run_charges(
    run_id: str,
    side: Literal["scenario", "baseline"] = "scenario",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=250),
    query: str = Query(default="", max_length=200),
) -> NetworkChargeAuditPage:
    return network_scenario_service.charge_audit(
        run_id, side=side, offset=offset, limit=limit, query=query
    )


@router.get("/runs/{run_id}/demand-changes", response_model=list[NetworkDemandChange])
def network_demand_changes(run_id: str) -> list[NetworkDemandChange]:
    return demand_change_service.list(run_id)


@router.post("/runs/{run_id}/demand-changes", response_model=NetworkDemandChange, status_code=status.HTTP_201_CREATED)
def create_network_demand_change(run_id: str, payload: NetworkDemandChangeCreateRequest) -> NetworkDemandChange:
    return demand_change_service.create(run_id, payload)


@router.get("/runs/{run_id}/depots/{depot_id}/release-targets", response_model=list[NetworkReleaseTarget])
def network_release_targets(run_id: str, depot_id: str, service_date: date) -> list[NetworkReleaseTarget]:
    return demand_change_service.release_targets(run_id, depot_id, service_date.isoformat())


@router.post(
    "/runs/{run_id}/reassign",
    response_model=NetworkRunRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
def reassign_network_demand(run_id: str) -> NetworkRunRecord:
    return demand_change_service.reassign(run_id)


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_network_scenario(scenario_id: str) -> Response:
    network_scenario_service.delete(scenario_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
