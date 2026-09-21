from __future__ import annotations

from datetime import date

from fastapi import APIRouter, status
from fastapi.responses import Response

from ..models import (
    NetworkLaneType,
    NetworkMetric,
    NetworkOptions,
    NetworkOverview,
    NetworkScenario,
    NetworkScenarioCreateRequest,
    NetworkScenarioResult,
    NetworkScenarioRunResponse,
    NetworkScenarioUpdateRequest,
)
from ..services.network_overview import network_overview_service
from ..services.network_scenarios import network_scenario_service

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
    response_model=NetworkScenarioRunResponse,
)
def run_network_scenario(scenario_id: str) -> NetworkScenarioRunResponse:
    return network_scenario_service.run(scenario_id)


@router.get(
    "/scenarios/{scenario_id}/result",
    response_model=NetworkScenarioResult,
)
def network_scenario_result(scenario_id: str) -> NetworkScenarioResult:
    return network_scenario_service.result(scenario_id)


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_network_scenario(scenario_id: str) -> Response:
    network_scenario_service.delete(scenario_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
