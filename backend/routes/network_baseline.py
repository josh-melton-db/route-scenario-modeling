from __future__ import annotations

from fastapi import APIRouter
from datetime import date
from pydantic import BaseModel, ConfigDict

from ..baseline_models import BaselineProposalRequest, BaselineProposalResponse, BaselineState
from ..models import NetworkScenarioResult
from ..services.baseline_service import baseline_service
from ..services.demo_reset import demo_reset_service
from ..services.solver_warmup import solver_warmup_service

router = APIRouter(prefix="/network/baseline", tags=["network-baseline"])


class PrepareDepotRoutesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_date: date | None = None


@router.post("/depot-routes/prepare", status_code=202)
def prepare_depot_routes(request: PrepareDepotRoutesRequest) -> dict:
    from ..services.depot_route_preparation import depot_route_preparation_manager
    return depot_route_preparation_manager.start(
        request.service_date.isoformat() if request.service_date else None)


@router.get("/depot-routes/preparations/{preparation_id}")
def depot_route_preparation_status(preparation_id: str) -> dict:
    from ..services.depot_route_preparation import depot_route_preparation_manager
    return depot_route_preparation_manager.status(preparation_id)


@router.get("", response_model=BaselineState)
def baseline_state() -> BaselineState:
    return baseline_service.get_state()


@router.get("/plan-run", response_model=NetworkScenarioResult)
def baseline_plan_run(
    demand_plan_version_id: str | None = None,
    capacity_plan_version_id: str | None = None,
    horizon_start: str | None = None,
    horizon_end: str | None = None,
) -> NetworkScenarioResult:
    return baseline_service.get_plan_run(
        demand_plan_version_id=demand_plan_version_id,
        capacity_plan_version_id=capacity_plan_version_id,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
    ).result


@router.post("/proposals", response_model=BaselineProposalResponse)
def propose_baseline(payload: BaselineProposalRequest) -> BaselineProposalResponse:
    return baseline_service.propose(payload.run_id)


@router.post("/proposals/{proposal_id}/accept", response_model=BaselineState)
def accept_baseline(proposal_id: str) -> BaselineState:
    return baseline_service.accept(proposal_id)


@router.post("/reset")
def reset_baseline() -> dict[str, object]:
    return demo_reset_service.reset()


@router.get("/reset/status")
def reset_status() -> dict[str, object]:
    return {
        "reset": demo_reset_service.status(),
        "solver_warmup": solver_warmup_service.status(),
    }
