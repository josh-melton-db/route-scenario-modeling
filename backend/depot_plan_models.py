from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import Depot, Kpis, LatLng, MatrixSource, Route, StrictModel


PlanStatus = Literal["queued", "running", "completed", "infeasible", "failed"]


def _validate_date(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD.") from exc
    return value


class Coverage(StrictModel):
    total_days: int = Field(ge=0)
    solved_days: int = Field(ge=0)
    queued_days: int = Field(ge=0)
    running_days: int = Field(ge=0)
    failed_days: int = Field(ge=0)


class RouteScenario(StrictModel):
    route_scenario_id: str = Field(min_length=1)
    scenario_name: str = Field(min_length=1)
    is_default: bool = False


class DaySummary(StrictModel):
    service_date: str
    status: PlanStatus
    default_status: PlanStatus
    assigned_cases: int = Field(ge=0)
    routed_cases: int | None = Field(default=None, ge=0)
    unserved_cases: int | None = Field(default=None, ge=0)
    total_cost: float | None = Field(default=None, ge=0)
    is_overridden: bool = False
    selected_result_id: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_service_date(self) -> "DaySummary":
        _validate_date(self.service_date, "service_date")
        return self


class DayResult(StrictModel):
    result_id: str = Field(min_length=1)
    service_date: str
    status: PlanStatus
    routes: list[Route] = Field(default_factory=list)
    kpis: Kpis
    assigned_cases: int = Field(ge=0)
    routed_cases: int = Field(ge=0)
    unserved_cases: int = Field(ge=0)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    matrix_source: MatrixSource
    execution: dict[str, Any] | None = None
    created_at: str

    @model_validator(mode="after")
    def validate_result(self) -> "DayResult":
        _validate_date(self.service_date, "service_date")
        if self.routed_cases + self.unserved_cases != self.assigned_cases:
            raise ValueError(
                "routed_cases plus unserved_cases must equal assigned_cases."
            )
        if self.status == "completed" and self.unserved_cases:
            raise ValueError(
                "A completed result cannot retain unserved cases; use infeasible."
            )
        return self


class DayDetail(StrictModel):
    plan_set_id: str
    service_date: str
    route_scenario_id: str
    default_status: PlanStatus
    override_status: PlanStatus | None = None
    default_result: DayResult | None = None
    selected_result: DayResult | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_service_date(self) -> "DayDetail":
        _validate_date(self.service_date, "service_date")
        return self


class PlanSet(StrictModel):
    plan_set_id: str
    parent_run_id: str
    depot: Depot
    horizon_start: str
    horizon_end: str
    route_scenario_id: str = "default"
    scenarios: list[RouteScenario]
    days: list[DaySummary]
    coverage: Coverage
    kpis: Kpis | None = None
    is_partial: bool
    resource_source: str

    @model_validator(mode="after")
    def validate_plan_set(self) -> "PlanSet":
        start = date.fromisoformat(
            _validate_date(self.horizon_start, "horizon_start") or ""
        )
        end = date.fromisoformat(_validate_date(self.horizon_end, "horizon_end") or "")
        if end < start:
            raise ValueError("horizon_end must not precede horizon_start.")
        scenario_ids = {row.route_scenario_id for row in self.scenarios}
        if "default" not in scenario_ids:
            raise ValueError("PlanSet scenarios must include the default scenario.")
        if self.route_scenario_id not in scenario_ids:
            raise ValueError("route_scenario_id must identify a scenario in scenarios.")
        return self


class CreatePlanRequest(StrictModel):
    priority_date: str | None = None

    @model_validator(mode="after")
    def validate_priority_date(self) -> "CreatePlanRequest":
        _validate_date(self.priority_date, "priority_date")
        return self


class CreateRouteScenarioRequest(StrictModel):
    scenario_name: str = Field(min_length=1)


class OverrideRequest(StrictModel):
    route_scenario_id: str = Field(min_length=1)
    driver_delta: int = 0
    allow_overtime: bool | None = None
    max_route_minutes: int | None = Field(default=None, gt=0)
    max_stops_per_route: int | None = Field(default=None, gt=0)
    new_depot_location: LatLng | None = None

    @model_validator(mode="after")
    def validate_named_scenario(self) -> "OverrideRequest":
        if self.route_scenario_id == "default":
            raise ValueError("route_scenario_id must identify a named scenario.")
        return self
