from __future__ import annotations

from fastapi import APIRouter

from ..baseline_models import BaselineProposalRequest, BaselineProposalResponse, BaselineState
from ..models import NetworkScenarioResult
from ..services.baseline_service import baseline_service

router = APIRouter(prefix="/network/baseline", tags=["network-baseline"])


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


@router.post("/reset", response_model=BaselineState)
def reset_baseline() -> BaselineState:
    return baseline_service.reset()
