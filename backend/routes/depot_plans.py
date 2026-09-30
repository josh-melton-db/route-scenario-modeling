from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..depot_plan_models import (
    CreatePlanRequest,
    CreateRouteScenarioRequest,
    DayDetail,
    OverrideRequest,
    PlanSet,
    RouteScenario,
)


router = APIRouter(tags=["depot-plans"])


def get_depot_plan_service() -> Any:
    from ..services.depot_plans import depot_plan_service

    return depot_plan_service


def _date_text(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _service_call(method: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return method(*args, **kwargs)
    except KeyError as exc:
        detail = str(exc).strip("'") or "Depot plan resource not found."
        raise HTTPException(status_code=404, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/network/runs/{run_id}/depots/{depot_id}/plans",
    response_model=PlanSet,
    status_code=status.HTTP_200_OK,
)
def create_depot_plan(
    run_id: str,
    depot_id: str,
    priority_date: date | None = Query(default=None),
    service: Any = Depends(get_depot_plan_service),
) -> PlanSet:
    request = CreatePlanRequest(priority_date=_date_text(priority_date))
    return _service_call(
        service.get_or_create_plan,
        run_id,
        depot_id,
        priority_date=request.priority_date,
    )


@router.get("/depot-plans/{plan_set_id}", response_model=PlanSet)
def get_depot_plan(
    plan_set_id: str,
    route_scenario_id: str = Query(default="default", min_length=1),
    service: Any = Depends(get_depot_plan_service),
) -> PlanSet:
    return _service_call(
        service.get_plan, plan_set_id, route_scenario_id=route_scenario_id
    )


@router.get(
    "/depot-plans/{plan_set_id}/days/{service_date}",
    response_model=DayDetail,
)
def get_depot_plan_day(
    plan_set_id: str,
    service_date: date,
    route_scenario_id: str = Query(default="default", min_length=1),
    service: Any = Depends(get_depot_plan_service),
) -> DayDetail:
    return _service_call(
        service.get_day,
        plan_set_id,
        _date_text(service_date),
        route_scenario_id=route_scenario_id,
    )


@router.post(
    "/depot-plans/{plan_set_id}/scenarios",
    response_model=RouteScenario,
    status_code=status.HTTP_201_CREATED,
)
def create_depot_route_scenario(
    plan_set_id: str,
    request: CreateRouteScenarioRequest,
    service: Any = Depends(get_depot_plan_service),
) -> RouteScenario:
    scenario_name = request.scenario_name.strip()
    if not scenario_name:
        raise HTTPException(status_code=422, detail="Scenario name is required.")
    return _service_call(service.create_scenario, plan_set_id, scenario_name)


@router.post(
    "/depot-plans/{plan_set_id}/days/{service_date}/optimize",
    response_model=DayDetail,
    status_code=status.HTTP_202_ACCEPTED,
)
def optimize_depot_plan_day(
    plan_set_id: str,
    service_date: date,
    request: OverrideRequest,
    service: Any = Depends(get_depot_plan_service),
) -> DayDetail:
    return _service_call(
        service.optimize_day, plan_set_id, _date_text(service_date), request
    )


@router.delete(
    "/depot-plans/{plan_set_id}/scenarios/{route_scenario_id}/days/{service_date}",
    response_model=DayDetail,
)
def reset_depot_plan_day_override(
    plan_set_id: str,
    route_scenario_id: str,
    service_date: date,
    service: Any = Depends(get_depot_plan_service),
) -> DayDetail:
    if route_scenario_id == "default":
        raise HTTPException(
            status_code=422, detail="The default scenario has no override to reset."
        )
    return _service_call(
        service.reset_day_override,
        plan_set_id,
        route_scenario_id,
        _date_text(service_date),
    )
