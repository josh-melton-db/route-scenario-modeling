from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class BaselineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BaselineRouteCoverage(BaselineModel):
    ready: bool
    covered_dates: int
    expected_dates: int
    covered_depots: int
    expected_depots: int
    message: str


class BaselineState(BaselineModel):
    original_revision_id: str
    active_revision_id: str
    active_run_id: str | None = None
    active_plan_run_id: str
    active_plan_scenario_id: str
    default_demand_plan_version_id: str | None = None
    default_capacity_plan_version_id: str | None = None
    accepted_at: str | None = None
    route_coverage: BaselineRouteCoverage


class BaselineProposalRequest(BaselineModel):
    run_id: str


class BaselineProposalResponse(BaselineModel):
    proposal_id: str
    status: Literal["proposed", "accepted", "rejected"]
    run_id: str
    source_revision_id: str
    route_coverage: BaselineRouteCoverage
