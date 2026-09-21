from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from ..models import NetworkLaneType, NetworkMetric, NetworkOptions, NetworkOverview
from ..services.network_overview import network_overview_service

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
