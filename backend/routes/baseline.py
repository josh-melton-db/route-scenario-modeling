from __future__ import annotations

from fastapi import APIRouter

from ..models import BaselineNetwork, Kpis
from ..services.store_provider import get_store

router = APIRouter(prefix="/baseline", tags=["baseline"])


@router.get("/network", response_model=BaselineNetwork)
async def baseline_network(depot_id: str, delivery_day: str) -> BaselineNetwork:
    return get_store().get_baseline_network(depot_id, delivery_day)


@router.get("/kpis", response_model=Kpis)
async def baseline_kpis(depot_id: str, delivery_day: str) -> Kpis:
    return get_store().get_baseline_kpis(depot_id, delivery_day)
