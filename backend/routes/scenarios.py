from __future__ import annotations

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
    scenario, result_stub_id = store.create_scenario(payload)
    return CreateScenarioResponse(scenario=scenario, result_stub_id=result_stub_id)


@router.get("/{scenario_id}", response_model=ScenarioDefinition)
async def scenario_definition(scenario_id: str) -> ScenarioDefinition:
    return get_store().get_scenario_definition(scenario_id)


@router.post("/{scenario_id}/validate", response_model=ValidationResponse)
async def validate_scenario(scenario_id: str) -> ValidationResponse:
    return get_store().validate_scenario(scenario_id)


@router.post("/{scenario_id}/run", response_model=RunStartResponse)
async def run_scenario(scenario_id: str) -> RunStartResponse:
    store = get_store()
    store.set_scenario_status(scenario_id, "running")
    if get_data_backend() == "databricks":
        return solve_run_manager.create_run(store.get_scenario_definition(scenario_id))
    target_status = store.get_target_status(scenario_id)
    return simulator.create_run(scenario_id, target_status)  # type: ignore[arg-type]
