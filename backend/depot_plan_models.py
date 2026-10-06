from __future__ import annotations

import re

from datetime import date
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import DeliveryDraft, Depot, Kpis, LatLng, MatrixSource, Route, StrictModel


PlanStatus = Literal[
    "not_requested", "queued", "running", "completed", "infeasible", "failed"
]


def _validate_date(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD.") from exc
    return value


_TIME_PATTERN = re.compile(r"^(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d)$")


def _validate_hh_mm(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _TIME_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must use 24-hour HH:MM format.")
    return value


class Coverage(StrictModel):
    total_days: int = Field(ge=0)
    solved_days: int = Field(ge=0)
    queued_days: int = Field(ge=0)
    running_days: int = Field(ge=0)
    failed_days: int = Field(ge=0)
    not_requested_days: int = Field(default=0, ge=0)


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
    depot: Depot | None = None
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
    override_request: dict[str, Any] | None = None
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
    fleet_snapshot: dict[str, object] | None = None
    customer_constraint_snapshot: dict[str, object] | None = None

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
    scenario_name: str = Field(min_length=1, max_length=120)


class DailyPlanChange(StrictModel):
    kind: Literal["add_deliveries", "facility_move", "time_window_change"]
    deliveries: list[DeliveryDraft] = Field(default_factory=list, max_length=100)
    new_depot_location: LatLng | None = None
    preserve_service_windows: bool = True
    customer_id: str | None = None
    receiving_window_start: str | None = None
    receiving_window_end: str | None = None

    @model_validator(mode="after")
    def validate_change(self) -> "DailyPlanChange":
        if self.kind == "add_deliveries" and not self.deliveries:
            raise ValueError("add_deliveries requires at least one delivery.")
        if self.kind == "facility_move" and self.new_depot_location is None:
            raise ValueError("facility_move requires new_depot_location.")
        if self.kind == "time_window_change":
            if not self.customer_id or not self.customer_id.strip():
                raise ValueError("time_window_change requires customer_id.")
            start = _validate_hh_mm(self.receiving_window_start, "receiving_window_start")
            end = _validate_hh_mm(self.receiving_window_end, "receiving_window_end")
            if start is None or end is None:
                raise ValueError(
                    "time_window_change requires receiving_window_start and receiving_window_end."
                )
            if start >= end:
                raise ValueError(
                    "time_window_change receiving_window_end must be after its start."
                )
        return self


class OverrideRequest(StrictModel):
    route_scenario_id: str = Field(min_length=1)
    driver_delta: int = Field(default=0, ge=-64, le=64)
    allow_overtime: bool | None = None
    max_route_minutes: int | None = Field(default=None, ge=1, le=1_440)
    max_stops_per_route: int | None = Field(default=None, ge=1, le=149)
    new_depot_location: LatLng | None = None
    changes: list[DailyPlanChange] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_named_scenario(self) -> "OverrideRequest":
        if self.route_scenario_id == "default":
            raise ValueError("route_scenario_id must identify a named scenario.")
        return self
