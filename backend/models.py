from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ScenarioType = Literal[
    "baseline",
    "ma_new_customers",
    "new_customer_growth",
    "driver_count_change",
    "delivery_frequency_day_change",
    "facility_move",
]
ScenarioLifecycleStatus = Literal[
    "draft",
    "validated",
    "running",
    "completed",
    "infeasible",
    "failed",
]
RunStatus = Literal["queued", "running", "succeeded", "infeasible", "failed"]
ConstraintSeverity = Literal["hard", "soft"]
ConstraintScope = Literal["route", "depot", "customer", "scenario"]
WindowRisk = Literal["none", "at_risk", "missed"]
MatrixSource = Literal["haversine_circuity"]
ParameterFieldType = Literal[
    "number",
    "integer",
    "select",
    "multiselect",
    "text",
    "boolean",
    "latlng",
]


class LatLng(StrictModel):
    lat: float
    lng: float


class Depot(StrictModel):
    depot_id: str
    name: str
    region: str
    sales_territory: str
    location: LatLng


class Stop(StrictModel):
    stop_id: str
    customer_id: str
    customer_name: str
    sequence: int
    location: LatLng
    demand_cases: int
    service_minutes: int
    time_window_start: str
    time_window_end: str
    arrival_time: str
    departure_time: str
    delivery_day: str
    window_risk: WindowRisk = "none"
    is_new_customer: bool = False


class Route(StrictModel):
    route_id: str
    scenario_id: str
    route_name: str
    depot_id: str
    driver_id: str
    driver_name: str
    vehicle_id: str
    delivery_day: str
    path: list[LatLng]
    stops: list[Stop]
    total_miles: float
    drive_minutes: int
    service_minutes: int
    total_cases: int
    capacity_cases: int
    capacity_utilization_pct: float
    driver_utilization_pct: float
    overtime_minutes: int
    missed_windows: int
    late_minutes: int
    total_cost: float


class CostBreakdown(StrictModel):
    mileage_cost: float
    labor_cost: float
    overtime_cost: float
    fixed_vehicle_cost: float
    sla_penalty_cost: float
    total_cost: float


class Kpis(StrictModel):
    route_count: int
    driver_count: int
    vehicle_count: int
    total_miles: float
    drive_minutes: int
    service_minutes: int
    total_cases: int
    avg_stops_per_route: float
    avg_capacity_utilization_pct: float
    avg_driver_utilization_pct: float
    overtime_minutes: int
    missed_windows: int
    late_minutes: int
    cost_breakdown: CostBreakdown


class KpiDeltas(StrictModel):
    route_count: int
    driver_count: int
    vehicle_count: int
    total_miles: float
    drive_minutes: int
    service_minutes: int
    total_cases: int
    avg_stops_per_route: float
    avg_capacity_utilization_pct: float
    avg_driver_utilization_pct: float
    overtime_minutes: int
    missed_windows: int
    late_minutes: int
    mileage_cost: float
    labor_cost: float
    overtime_cost: float
    fixed_vehicle_cost: float
    sla_penalty_cost: float
    total_cost: float


class CustomerImpact(StrictModel):
    customer_id: str
    customer_name: str
    is_new_customer: bool
    changed_route: bool
    changed_day: bool
    changed_depot: bool
    sequence_shift: int
    baseline_day: str | None
    scenario_day: str | None
    baseline_route_id: str | None
    scenario_route_id: str | None
    window_risk: WindowRisk
    disruption_score: float
    summary: str


class ConstraintViolation(StrictModel):
    violation_id: str
    severity: ConstraintSeverity
    scope: ConstraintScope
    ref_id: str | None = None
    route_id: str | None = None
    customer_id: str | None = None
    metric: str
    limit_value: float | None = None
    actual_value: float | None = None
    message: str
    recommendation: str


class ParameterOption(StrictModel):
    value: str
    label: str


class ParameterField(StrictModel):
    name: str
    label: str
    field_type: ParameterFieldType
    required: bool = False
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[ParameterOption] = Field(default_factory=list)
    placeholder: str | None = None
    help_text: str | None = None


class ScenarioTypeSpec(StrictModel):
    scenario_type: ScenarioType
    label: str
    description: str
    result_stub_id: str
    fields: list[ParameterField]


class ScenarioDefinition(StrictModel):
    scenario_id: str
    scenario_name: str
    scenario_type: ScenarioType
    baseline_scenario_id: str
    depot_id: str
    delivery_day: str
    parameters: dict[str, Any]
    status: ScenarioLifecycleStatus


class ScenarioCreateRequest(StrictModel):
    scenario_name: str
    scenario_type: ScenarioType
    baseline_scenario_id: str
    depot_id: str
    delivery_day: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class CreateScenarioResponse(StrictModel):
    scenario: ScenarioDefinition
    result_stub_id: str


class ValidationIssue(StrictModel):
    field: str | None = None
    scope: ConstraintScope
    ref_id: str | None = None
    severity: ConstraintSeverity
    message: str


class ValidationResponse(StrictModel):
    scenario_id: str
    valid: bool
    hard_constraints: list[ValidationIssue]
    soft_penalties: list[ValidationIssue]
    missing_fields: list[str]
    inferred_fields: list[str]
    estimated_affected_customers: int
    estimated_affected_routes: int
    summary: str


class BaselineNetwork(StrictModel):
    scenario_id: Literal["baseline"]
    depot: Depot
    delivery_day: str
    routes: list[Route]
    matrix_source: MatrixSource
    generated_at: str
    summary: str


class RunStage(StrictModel):
    stage_id: str
    label: str
    status: Literal["pending", "running", "completed", "failed"]
    message: str


class RunStartResponse(StrictModel):
    run_id: str
    scenario_id: str
    status: RunStatus
    message: str
    databricks_run_url: str | None = None


class RunStatusResponse(StrictModel):
    run_id: str
    scenario_id: str
    status: RunStatus
    progress_pct: int
    message: str
    stages: list[RunStage]
    started_at: str
    completed_at: str | None = None
    databricks_run_url: str | None = None


class ComparisonResult(StrictModel):
    scenario_id: str
    baseline_scenario_id: str
    scenario_name: str
    status: RunStatus
    matrix_source: MatrixSource
    generated_at: str
    summary: str
    baseline_depot: Depot
    scenario_depot: Depot
    baseline_routes: list[Route]
    scenario_routes: list[Route]
    baseline_kpis: Kpis
    scenario_kpis: Kpis | None
    kpi_deltas: KpiDeltas | None
    customer_impacts: list[CustomerImpact]
    constraint_violations: list[ConstraintViolation]
