from __future__ import annotations

from fastapi import APIRouter

from ..models import ComparisonResult
from ..config import get_data_backend
from ..services.solve_runs import solve_run_manager
from ..services.store_provider import get_store

router = APIRouter(prefix="/scenarios", tags=["results"])


@router.get("/{scenario_id}/results", response_model=ComparisonResult)
async def scenario_results(scenario_id: str) -> ComparisonResult:
    if get_data_backend() == "databricks":
        cached = solve_run_manager.get_result(scenario_id)
        if cached is not None:
            return cached
    return get_store().get_scenario_result(scenario_id)
