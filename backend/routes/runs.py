from __future__ import annotations

from fastapi import APIRouter, Query

from ..models import RunStatusResponse
from ..config import get_data_backend
from ..services.run_simulator import simulator
from ..services.solve_runs import solve_run_manager
from ..services.store_provider import get_store

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunStatusResponse)
async def run_status(run_id: str, scenario_id: str | None = Query(default=None, alias="scenarioId")) -> RunStatusResponse:
    if get_data_backend() in {"databricks", "lakebase"}:
        status = solve_run_manager.get_status(run_id)
        if get_data_backend() == "databricks":
            store = get_store()
            if status.status == "succeeded":
                store.set_scenario_status(status.scenario_id, "completed")
            elif status.status in {"infeasible", "failed"}:
                store.set_scenario_status(status.scenario_id, status.status)
        return status
    status = simulator.get_run_status(run_id)
    store = get_store()
    if status.status == "succeeded":
        store.set_scenario_status(status.scenario_id, "completed")
    elif status.status in {"infeasible", "failed"}:
        store.set_scenario_status(status.scenario_id, status.status)
    return status
