from __future__ import annotations

from fastapi import APIRouter

from ..models import Depot, ScenarioTypeSpec
from ..services.store_provider import get_store

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/depots", response_model=list[Depot])
async def depots() -> list[Depot]:
    return get_store().list_depots()


@router.get("/scenario-types", response_model=list[ScenarioTypeSpec])
async def scenario_types() -> list[ScenarioTypeSpec]:
    return get_store().list_scenario_types()


@router.get("/days", response_model=list[str])
async def days() -> list[str]:
    return get_store().list_days()
