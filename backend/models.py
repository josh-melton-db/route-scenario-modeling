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
MatrixSource = Literal["haversine_circuity", "valhalla"]
RateContractStatus = Literal["draft", "published", "expired"]
MileageRounding = Literal["exact", "nearest_mile", "up_to_mile"]
FuelBasis = Literal["linehaul", "linehaul_and_minimum", "transportation_subtotal"]
AccessorialChargeType = Literal["flat", "per_stop", "per_hour", "per_case"]
VolumePeriod = Literal["route", "week", "month", "quarter"]
EditorEntityType = Literal[
    "orders",
    "customers",
    "fleet",
    "depots",
    "cost_parameters",
    "carriers",
    "carrier_contracts",
    "operating_parameters",
    "revenue_parameters",
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


class Carrier(StrictModel):
    carrier_id: str
    carrier_name: str
    active: bool = True


class CarrierContract(StrictModel):
    contract_id: str
    carrier_id: str
    contract_name: str
    capacity_stops: int
    rate_per_mile: float
    rate_per_stop: float
    minimum_charge: float
    fuel_surcharge_pct: float
    effective_start: str | None = None
    effective_end: str | None = None
    active: bool = True


class ContractVersion(StrictModel):
    version_id: str
    version_number: int
    status: RateContractStatus
    currency: str = "USD"
    effective_start: str | None = None
    effective_end: str | None = None
    published_at: str | None = None
    published_by: str | None = None
    change_reason: str | None = None


class LaneRateRule(StrictModel):
    rule_id: str
    lane_name: str
    origin: str
    destination: str
    lane_type: Literal["LINEHAUL", "MARKET", "DELIVERY"] | None = None
    origin_endpoint_id: str | None = None
    origin_endpoint_type: Literal["facility", "market", "customer"] | None = None
    destination_endpoint_id: str | None = None
    destination_endpoint_type: Literal["facility", "market", "customer"] | None = None
    priority: int = 100
    flat_rate: float = 0
    rate_per_mile: float = 0
    rate_per_stop: float = 0
    included_stops: int = 0
    minimum_charge: float = 0
    mileage_rounding: MileageRounding = "exact"


class FuelSurchargeRule(StrictModel):
    rule_id: str
    name: str
    rate_pct: float
    basis: FuelBasis = "linehaul_and_minimum"
    effective_start: str | None = None
    effective_end: str | None = None


class AccessorialRule(StrictModel):
    rule_id: str
    code: str
    name: str
    charge_type: AccessorialChargeType
    rate: float
    description: str


class VolumeTierRule(StrictModel):
    rule_id: str
    name: str
    period: VolumePeriod
    unit: Literal["stops", "routes", "cases", "miles"]
    min_volume: float
    max_volume: float | None = None
    discount_pct: float = 0


class CapacityCommitmentRule(StrictModel):
    rule_id: str
    name: str
    period: VolumePeriod
    unit: Literal["stops", "routes", "cases", "miles"]
    committed_quantity: float
    capacity_quantity: float
    current_utilization: float = 0
    shortfall_rate: float = 0
    overage_rate: float = 0


class RateContractSummary(StrictModel):
    contract_id: str
    carrier_id: str
    carrier_name: str
    contract_name: str
    version: ContractVersion
    draft_version: ContractVersion | None = None
    status: RateContractStatus
    lane_count: int
    accessorial_count: int
    volume_tier_count: int
    committed_quantity: float
    capacity_quantity: float
    current_utilization: float
    coverage_status: Literal["covered", "partial", "unavailable"]
    freshness_at: str


class RateContractDetail(StrictModel):
    contract_id: str
    carrier_id: str
    carrier_name: str
    contract_name: str
    version: ContractVersion
    lane_rates: list[LaneRateRule]
    fuel_surcharges: list[FuelSurchargeRule]
    accessorials: list[AccessorialRule]
    volume_tiers: list[VolumeTierRule]
    capacity_commitments: list[CapacityCommitmentRule]
    version_history: list[ContractVersion] = Field(default_factory=list)
    source: str = "Lakebase rate book"
    freshness_at: str


class RateAccessorialTemplate(StrictModel):
    code: str
    name: str
    charge_type: AccessorialChargeType
    rate: float
    description: str


class RateAuthoringOptions(StrictModel):
    destinations: list[str] = Field(default_factory=list)
    accessorials: list[RateAccessorialTemplate] = Field(default_factory=list)


class RateContractCreateRequest(StrictModel):
    carrier_id: str
    contract_name: str
    currency: str = "USD"
    effective_start: str
    effective_end: str


class RateVersionCreateRequest(StrictModel):
    source_version_id: str | None = None
    effective_start: str
    effective_end: str
    change_reason: str = ""


class RateDraftUpdateRequest(StrictModel):
    contract_name: str
    currency: str = "USD"
    effective_start: str
    effective_end: str
    change_reason: str = ""
    lane_rates: list[LaneRateRule] = Field(default_factory=list)
    fuel_surcharges: list[FuelSurchargeRule] = Field(default_factory=list)
    accessorials: list[AccessorialRule] = Field(default_factory=list)
    volume_tiers: list[VolumeTierRule] = Field(default_factory=list)
    capacity_commitments: list[CapacityCommitmentRule] = Field(default_factory=list)


class RateValidationIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    field: str
    message: str


class RateValidationResponse(StrictModel):
    contract_id: str
    version_id: str
    valid: bool
    issues: list[RateValidationIssue] = Field(default_factory=list)
    summary: str


class RatePublishRequest(StrictModel):
    published_by: str = "Rate manager"
    change_reason: str = ""


class RateQuoteRequest(StrictModel):
    contract_id: str
    version_id: str | None = None
    service_date: str
    origin: str
    destination: str
    miles: float = Field(ge=0)
    stops: int = Field(ge=0)
    cases: int = Field(default=0, ge=0)
    period_volume: float = Field(default=0, ge=0)
    accessorial_codes: list[str] = Field(default_factory=list)
    accessorial_quantities: dict[str, float] = Field(default_factory=dict)
    period_close: bool = False
    commitment_policy: Literal["honor", "ignore"] = "honor"


class RateChargeLine(StrictModel):
    category: Literal[
        "lane",
        "mileage",
        "stops",
        "volume_tier",
        "minimum",
        "fuel",
        "accessorial",
        "commitment",
    ]
    label: str
    formula: str
    quantity: float
    unit: str
    rate: float
    amount: float
    rule_id: str


class RateQuote(StrictModel):
    quote_id: str
    contract_id: str
    contract_name: str
    carrier_id: str
    carrier_name: str
    contract_version_id: str
    service_date: str
    origin: str
    destination: str
    matched_lane: str | None = None
    matched_lane_rule_id: str | None = None
    matched_volume_tier: str | None = None
    eligible: bool
    eligibility_message: str
    charge_lines: list[RateChargeLine] = Field(default_factory=list)
    transportation_subtotal: float = 0
    total_cost: float = 0
    commitment_remaining: float = 0
    capacity_remaining: float = 0
    rate_book_snapshot_id: str
    warnings: list[str] = Field(default_factory=list)


class OperatingParameterSet(StrictModel):
    parameter_set_id: str
    parameter_set_name: str
    private_vehicle_limit: int
    max_route_minutes: int
    max_stops_per_route: int
    allow_overtime: bool = True
    active: bool = True


class CostParameterSet(StrictModel):
    parameter_set_id: str
    cost_per_mile: float
    labor_regular_hour: float
    overtime_multiplier: float
    overtime_threshold_minutes: int
    fixed_truck_daily_cost: float
    max_route_minutes: int
    late_delivery_penalty: float
    missed_delivery_penalty: float
    avg_speed_mph: float
    circuity: float


class RevenueParameterSet(StrictModel):
    product_family: str
    revenue_per_case: float
    active: bool = True


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
    fulfillment_method: Literal["private_fleet", "private_overtime", "carrier"] = "private_fleet"
    carrier_name: str | None = None
    contract_name: str | None = None
    contract_version_id: str | None = None
    rated_service_date: str | None = None
    rate_lane: str | None = None
    rate_book_snapshot_id: str | None = None
    carrier_charge_lines: list[RateChargeLine] = Field(default_factory=list)
    decision_reason: str = "Assigned to available private-fleet capacity."


class CostBreakdown(StrictModel):
    mileage_cost: float
    labor_cost: float
    overtime_cost: float
    fixed_vehicle_cost: float
    sla_penalty_cost: float
    carrier_linehaul_cost: float = 0
    carrier_lane_cost: float = 0
    carrier_stop_cost: float = 0
    carrier_minimum_adjustment: float = 0
    fuel_surcharge_cost: float = 0
    accessorial_cost: float = 0
    volume_tier_adjustment: float = 0
    commitment_adjustment: float = 0
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
    total_revenue: float = 0
    profit: float = 0
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
    total_revenue: float = 0
    profit: float = 0
    mileage_cost: float
    labor_cost: float
    overtime_cost: float
    fixed_vehicle_cost: float
    sla_penalty_cost: float
    carrier_linehaul_cost: float = 0
    carrier_lane_cost: float = 0
    carrier_stop_cost: float = 0
    carrier_minimum_adjustment: float = 0
    fuel_surcharge_cost: float = 0
    accessorial_cost: float = 0
    volume_tier_adjustment: float = 0
    commitment_adjustment: float = 0
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
    fulfillment_method: Literal["private_fleet", "private_overtime", "carrier", "unserved"] = "private_fleet"
    carrier_name: str | None = None
    decision_reason: str | None = None


class TransportationAllocation(StrictModel):
    fulfillment_method: Literal["private_fleet", "private_overtime", "carrier", "unserved"]
    label: str
    deliveries: int
    cases: int
    miles: float
    cost: float


class DecisionExplanation(StrictModel):
    customer_id: str
    customer_name: str
    decision: str
    reason: str


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


class ScenarioHistoryItem(ScenarioDefinition):
    created_at: str
    has_results: bool


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
    transportation_allocation: list[TransportationAllocation] = Field(default_factory=list)
    decision_explanations: list[DecisionExplanation] = Field(default_factory=list)
    rate_book_snapshot_id: str | None = None


NetworkLaneType = Literal["ALL", "LINEHAUL", "MARKET", "DELIVERY"]
NetworkMetric = Literal["assigned_flow", "utilization", "cost", "cost_per_unit"]
NetworkScenarioStatus = Literal[
    "draft",
    "validated",
    "solving",
    "solved",
    "infeasible",
    "failed",
    "depot_plans_running",
    "reconciliation_required",
    "reconciled",
    "published",
]


class NetworkRegionOption(StrictModel):
    region_id: str
    region_name: str


class NetworkFacilityOption(StrictModel):
    facility_id: str
    facility_name: str
    facility_type: Literal["distribution_center", "depot"]
    region_id: str
    parent_facility_id: str | None = None


class NetworkPlanVersionOption(StrictModel):
    plan_version_id: str
    display_name: str
    as_of_date: str
    horizon_start: str
    horizon_end: str
    status: Literal["published"] = "published"
    validation_status: Literal["passed"] = "passed"


class NetworkMetricOption(StrictModel):
    metric_id: NetworkMetric
    label: str
    unit: str


class NetworkOptions(StrictModel):
    regions: list[NetworkRegionOption]
    facilities: list[NetworkFacilityOption]
    demand_plans: list[NetworkPlanVersionOption]
    capacity_plans: list[NetworkPlanVersionOption]
    lane_types: list[NetworkLaneType]
    metrics: list[NetworkMetricOption]
    default_demand_plan_version_id: str
    default_capacity_plan_version_id: str
    default_horizon_start: str
    default_horizon_end: str
    default_region_id: str
    default_lane_type: NetworkLaneType = "LINEHAUL"
    default_metric: NetworkMetric = "assigned_flow"
    source: str
    freshness_at: str


class NetworkOverviewContext(StrictModel):
    scenario_id: str = "baseline"
    demand_plan_version_id: str
    capacity_plan_version_id: str
    horizon_start: str
    horizon_end: str
    region_id: str
    lane_type: NetworkLaneType
    metric: NetworkMetric


class NetworkOverviewKpis(StrictModel):
    demand_units: int = Field(ge=0)
    assigned_units: int = Field(ge=0)
    unmet_units: int = Field(ge=0)
    total_cost: float = Field(ge=0)
    cost_per_unit: float = Field(ge=0)
    on_time_pct: float = Field(ge=0, le=100)
    utilization_pct: float = Field(ge=0)


class NetworkFacilityAggregate(StrictModel):
    facility_id: str
    facility_name: str
    facility_type: Literal["distribution_center", "depot"]
    region_id: str
    parent_facility_id: str | None = None
    location: LatLng
    demand_units: int = Field(ge=0)
    assigned_units: int = Field(ge=0)
    capacity_units: int = Field(ge=0)
    utilization_pct: float = Field(ge=0)
    total_cost: float = Field(ge=0)
    cost_per_unit: float = Field(ge=0)
    on_time_pct: float = Field(ge=0, le=100)
    connected_facility_count: int = Field(ge=0)
    depot_count: int = Field(ge=0)
    depot_analysis_available: bool = False


class NetworkLaneAggregate(StrictModel):
    lane_id: str
    lane_name: str
    lane_type: Literal["LINEHAUL", "MARKET", "DELIVERY"]
    origin_endpoint_id: str
    origin_endpoint_name: str
    origin_endpoint_type: Literal["facility", "market", "customer"]
    origin_location: LatLng
    destination_endpoint_id: str
    destination_endpoint_name: str
    destination_endpoint_type: Literal["facility", "market", "customer"]
    destination_location: LatLng
    mode: str
    distance_miles: float = Field(ge=0)
    transit_minutes: int = Field(ge=0)
    assigned_units: int = Field(ge=0)
    capacity_units: int = Field(ge=0)
    utilization_pct: float = Field(ge=0)
    total_cost: float = Field(ge=0)
    cost_per_unit: float = Field(ge=0)
    on_time_pct: float = Field(ge=0, le=100)
    contract_coverage: Literal["covered", "partial", "not_required"]
    contract_id: str | None = None
    contract_version_id: str | None = None
    included_in_network_cost: bool


class NetworkInsight(StrictModel):
    insight_id: str
    insight_type: Literal[
        "bottleneck",
        "unmet_demand",
        "high_cost",
        "underutilized_capacity",
        "service_risk",
        "contract_gap",
    ]
    severity: Literal["info", "warning", "critical"]
    title: str
    summary: str
    entity_type: Literal["facility", "lane", "network"]
    entity_id: str | None = None
    metric_value: float | None = None
    metric_unit: str | None = None


class NetworkOverview(StrictModel):
    context: NetworkOverviewContext
    kpis: NetworkOverviewKpis
    facilities: list[NetworkFacilityAggregate]
    lanes: list[NetworkLaneAggregate]
    insights: list[NetworkInsight]
    summary: str
    source: str
    freshness_at: str
    is_partial: bool = False


class NetworkScenarioAssumptions(StrictModel):
    disabled_facility_ids: list[str] = Field(default_factory=list)
    disabled_lane_ids: list[str] = Field(default_factory=list)
    lane_cost_adjustments_pct: dict[str, float] = Field(default_factory=dict)
    unmet_penalty_per_case: float = Field(default=250.0, ge=0)


class NetworkScenarioValidationIssue(StrictModel):
    severity: Literal["error", "warning", "info"]
    code: str
    scope: Literal["scenario", "plan", "facility", "lane", "rate"]
    entity_id: str | None = None
    message: str


class NetworkScenarioValidation(StrictModel):
    valid: bool
    issues: list[NetworkScenarioValidationIssue] = Field(default_factory=list)
    summary: str
    validated_at: str


class NetworkScenario(StrictModel):
    scenario_id: str
    scenario_name: str
    baseline_scenario_id: str = "baseline"
    demand_plan_version_id: str
    capacity_plan_version_id: str
    horizon_start: str
    horizon_end: str
    region_id: str
    status: NetworkScenarioStatus = "draft"
    revision: int = Field(default=1, ge=1)
    assumptions: NetworkScenarioAssumptions = Field(
        default_factory=NetworkScenarioAssumptions
    )
    validation: NetworkScenarioValidation | None = None
    created_at: str
    updated_at: str
    solved_at: str | None = None


class NetworkScenarioCreateRequest(StrictModel):
    scenario_name: str
    baseline_scenario_id: str = "baseline"
    demand_plan_version_id: str
    capacity_plan_version_id: str
    horizon_start: str
    horizon_end: str
    region_id: str = "ALL"
    assumptions: NetworkScenarioAssumptions = Field(
        default_factory=NetworkScenarioAssumptions
    )


class NetworkScenarioUpdateRequest(StrictModel):
    scenario_name: str | None = None
    assumptions: NetworkScenarioAssumptions | None = None


class NetworkScenarioKpiDeltas(StrictModel):
    demand_units: int
    assigned_units: int
    unmet_units: int
    total_cost: float
    cost_per_unit: float
    on_time_pct: float
    utilization_pct: float


class NetworkScenarioException(StrictModel):
    exception_id: str
    exception_type: Literal[
        "unmet_demand",
        "capacity_constraint",
        "missing_rate",
        "disconnected_node",
    ]
    severity: Literal["info", "warning", "critical"]
    service_date: str | None = None
    entity_type: Literal["network", "facility", "lane"]
    entity_id: str | None = None
    message: str
    demand_units: int | None = None
    assigned_units: int | None = None
    unmet_units: int | None = None


class NetworkFlowChargeDetail(StrictModel):
    service_date: str
    lane_id: str
    assigned_units: int = Field(ge=0)
    loads: int = Field(ge=0)
    rate_source: Literal["governed_contract", "planning_fallback"]
    contract_id: str | None = None
    contract_version_id: str | None = None
    rate_book_snapshot_id: str | None = None
    total_cost: float = Field(ge=0)
    charge_lines: list[RateChargeLine] = Field(default_factory=list)


class NetworkScenarioResult(StrictModel):
    scenario_id: str
    revision: int = Field(ge=1)
    generated_at: str
    overview: NetworkOverview
    baseline_overview: NetworkOverview
    kpi_deltas: NetworkScenarioKpiDeltas
    affected_depot_ids: list[str] = Field(default_factory=list)
    charge_details: list[NetworkFlowChargeDetail] = Field(default_factory=list)
    exceptions: list[NetworkScenarioException] = Field(default_factory=list)


class NetworkScenarioRunResponse(StrictModel):
    scenario: NetworkScenario
    result: NetworkScenarioResult


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
