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
    "custom",
]
ScenarioChangeKind = Literal[
    "add_deliveries",
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
EditorEntityType = Literal[
    "orders",
    "customers",
    "fleet",
    "depots",
    "cost_parameters",
]
EditorSessionStatus = Literal["open", "committed", "discarded", "expired"]
EditorRowState = Literal["unchanged", "inserted", "updated"]
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


class DeliveryDraft(StrictModel):
    customer_name: str
    lat: float
    lng: float
    demand_cases: int
    service_minutes: int = 30
    receiving_window_start: str = "08:00"
    receiving_window_end: str = "16:00"
    delivery_day: str | None = None
    customer_id: str | None = None


class CostOverride(StrictModel):
    cost_per_mile: float | None = None
    labor_regular_hour: float | None = None
    overtime_multiplier: float | None = None
    overtime_threshold_minutes: int | None = None
    fixed_truck_daily_cost: float | None = None
    late_delivery_penalty: float | None = None
    missed_delivery_penalty: float | None = None


class ScenarioChange(StrictModel):
    kind: ScenarioChangeKind
    deliveries: list[DeliveryDraft] = Field(default_factory=list)
    driver_delta: int | None = None
    allow_overtime: bool | None = None
    target_day: str | None = None
    target_customers: str | None = None
    new_depot_location: LatLng | None = None
    preserve_service_windows: bool | None = None


class DeliveryUploadError(StrictModel):
    row: int
    message: str


class DeliveryUploadResult(StrictModel):
    deliveries: list[DeliveryDraft]
    errors: list[DeliveryUploadError] = Field(default_factory=list)


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
    duration_ms: int | None = None


class RunStartResponse(StrictModel):
    run_id: str
    scenario_id: str
    status: RunStatus
    message: str
    databricks_run_url: str | None = None


class CreateScenarioResponse(StrictModel):
    scenario: ScenarioDefinition
    result_stub_id: str
    run: RunStartResponse | None = None


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
    validation: ValidationResponse | None = None
    stage_durations_ms: dict[str, int | None] = Field(default_factory=dict)


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


class EditorSession(StrictModel):
    """Authenticated user's isolated planning-data editing session."""

    session_id: str
    principal: str
    status: EditorSessionStatus
    created_at: str
    updated_at: str
    expires_at: str
    has_unsaved_changes: bool = False
    entity_counts: dict[EditorEntityType, int] = Field(default_factory=dict)


class EditorRow(StrictModel):
    entity_type: EditorEntityType
    row_id: str
    row_version: int = Field(ge=1)
    state: EditorRowState
    data: dict[str, Any]


class EditorPage(StrictModel):
    session: EditorSession
    entity_type: EditorEntityType
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    rows: list[EditorRow]


class EditorInsertRequest(StrictModel):
    data: dict[str, Any]


class EditorPatchRequest(StrictModel):
    row_version: int = Field(ge=1)
    changes: dict[str, Any]


class EditorDeleteRequest(StrictModel):
    row_version: int = Field(ge=1)


class EditorValidationIssue(StrictModel):
    entity_type: EditorEntityType
    row_id: str
    field: str | None = None
    code: str
    message: str


class EditorValidationResponse(StrictModel):
    session: EditorSession
    valid: bool
    issues: list[EditorValidationIssue] = Field(default_factory=list)


class EditorPreviewRequest(StrictModel):
    depot_id: str
    delivery_day: str


class EditorPreviewResponse(StrictModel):
    session: EditorSession
    network: BaselineNetwork
    kpis: Kpis


class EditorCommitResponse(StrictModel):
    session: EditorSession
    baseline_snapshot_count: int = Field(ge=0)
