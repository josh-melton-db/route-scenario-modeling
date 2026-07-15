from __future__ import annotations

import time

from fastapi import APIRouter

from ..models import (
    CreateScenarioResponse,
    RunStartResponse,
    ScenarioCreateRequest,
    ScenarioDefinition,
    ValidationResponse,
)
from ..config import get_data_backend
from ..services.run_simulator import simulator
from ..services.solve_runs import solve_run_manager
from ..services.store_provider import get_store

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.post("", response_model=CreateScenarioResponse)
async def create_scenario(payload: ScenarioCreateRequest) -> CreateScenarioResponse:
    store = get_store()
    backend = get_data_backend()
    started_at = time.perf_counter()
    scenario, result_stub_id = store.create_scenario(payload)
    run = solve_run_manager.create_run(scenario) if backend == "lakebase" else None
    if run is not None:
        record_duration = getattr(store, "record_create_duration", None)
        if callable(record_duration):
            record_duration(run.run_id, round((time.perf_counter() - started_at) * 1000))
    return CreateScenarioResponse(scenario=scenario, result_stub_id=result_stub_id, run=run)


@router.get("/{scenario_id}", response_model=ScenarioDefinition)
async def scenario_definition(scenario_id: str) -> ScenarioDefinition:
    return get_store().get_scenario_definition(scenario_id)


@router.post("/{scenario_id}/validate", response_model=ValidationResponse)
async def validate_scenario(scenario_id: str) -> ValidationResponse:
    return get_store().validate_scenario(scenario_id)


@router.post("/{scenario_id}/run", response_model=RunStartResponse)
async def run_scenario(scenario_id: str) -> RunStartResponse:
    store = get_store()
    if get_data_backend() in {"databricks", "lakebase"}:
        if get_data_backend() == "databricks":
            store.set_scenario_status(scenario_id, "running")
        return solve_run_manager.create_run(store.get_scenario_definition(scenario_id))
    store.set_scenario_status(scenario_id, "running")
    target_status = store.get_target_status(scenario_id)
    return simulator.create_run(scenario_id, target_status)  # type: ignore[arg-type]
