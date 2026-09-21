export type ScenarioType =
  | 'baseline'
  | 'ma_new_customers'
  | 'new_customer_growth'
  | 'driver_count_change'
  | 'delivery_frequency_day_change'
  | 'facility_move'
  | 'custom'

export type ScenarioChangeKind =
  | 'add_deliveries'
  | 'driver_count_change'
  | 'delivery_frequency_day_change'
  | 'facility_move'

export type ScenarioLifecycleStatus =
  | 'draft'
  | 'validated'
  | 'running'
  | 'completed'
  | 'infeasible'
  | 'failed'

export type RunStatus =
  | 'queued'
  | 'precheck'
  | 'running'
  | 'succeeded'
  | 'infeasible'
  | 'failed'
export type ConstraintSeverity = 'hard' | 'soft'
export type ConstraintScope = 'route' | 'depot' | 'customer' | 'scenario'
export type WindowRisk = 'none' | 'at_risk' | 'missed'
export type MatrixSource = 'haversine_circuity' | 'valhalla'
export type ParameterFieldType =
  | 'number'
  | 'integer'
  | 'select'
  | 'multiselect'
  | 'text'
  | 'boolean'
  | 'latlng'

export interface LatLng {
  lat: number
  lng: number
}

export interface Depot {
  depot_id: string
  name: string
  region: string
  sales_territory: string
  location: LatLng
}

export type NetworkLaneType = 'ALL' | 'LINEHAUL' | 'MARKET' | 'DELIVERY'
export type NetworkMetric =
  | 'assigned_flow'
  | 'utilization'
  | 'cost'
  | 'cost_per_unit'

export interface NetworkRegionOption {
  region_id: string
  region_name: string
}

export interface NetworkFacilityOption {
  facility_id: string
  facility_name: string
  facility_type: 'distribution_center' | 'depot'
  region_id: string
  parent_facility_id: string | null
}

export interface NetworkPlanVersionOption {
  plan_version_id: string
  display_name: string
  as_of_date: string
  horizon_start: string
  horizon_end: string
  status: 'published'
  validation_status: 'passed'
}

export interface NetworkMetricOption {
  metric_id: NetworkMetric
  label: string
  unit: string
}

export interface NetworkOptions {
  regions: NetworkRegionOption[]
  facilities: NetworkFacilityOption[]
  demand_plans: NetworkPlanVersionOption[]
  capacity_plans: NetworkPlanVersionOption[]
  lane_types: NetworkLaneType[]
  metrics: NetworkMetricOption[]
  default_demand_plan_version_id: string
  default_capacity_plan_version_id: string
  default_horizon_start: string
  default_horizon_end: string
  default_region_id: string
  default_lane_type: NetworkLaneType
  default_metric: NetworkMetric
  source: string
  freshness_at: string
}

export interface NetworkOverviewParams {
  demand_plan_version_id: string
  capacity_plan_version_id: string
  horizon_start: string
  horizon_end: string
  region_id: string
  lane_type: NetworkLaneType
  metric: NetworkMetric
}

export interface NetworkOverviewContext extends NetworkOverviewParams {
  scenario_id: string
}

export interface NetworkOverviewKpis {
  demand_units: number
  assigned_units: number
  unmet_units: number
  total_cost: number
  cost_per_unit: number
  on_time_pct: number
  utilization_pct: number
}

export interface NetworkFacilityAggregate {
  facility_id: string
  facility_name: string
  facility_type: 'distribution_center' | 'depot'
  region_id: string
  parent_facility_id: string | null
  location: LatLng
  demand_units: number
  assigned_units: number
  capacity_units: number
  utilization_pct: number
  total_cost: number
  cost_per_unit: number
  on_time_pct: number
  connected_facility_count: number
  depot_count: number
  depot_analysis_available: boolean
}

export interface NetworkLaneAggregate {
  lane_id: string
  lane_name: string
  lane_type: Exclude<NetworkLaneType, 'ALL'>
  origin_endpoint_id: string
  origin_endpoint_name: string
  origin_endpoint_type: 'facility' | 'market' | 'customer'
  origin_location: LatLng
  destination_endpoint_id: string
  destination_endpoint_name: string
  destination_endpoint_type: 'facility' | 'market' | 'customer'
  destination_location: LatLng
  mode: string
  distance_miles: number
  transit_minutes: number
  assigned_units: number
  capacity_units: number
  utilization_pct: number
  total_cost: number
  cost_per_unit: number
  on_time_pct: number
  contract_coverage: 'covered' | 'partial' | 'not_required'
  contract_id: string | null
  contract_version_id: string | null
  included_in_network_cost: boolean
}

export interface NetworkInsight {
  insight_id: string
  insight_type:
    | 'bottleneck'
    | 'unmet_demand'
    | 'high_cost'
    | 'underutilized_capacity'
    | 'service_risk'
    | 'contract_gap'
  severity: 'info' | 'warning' | 'critical'
  title: string
  summary: string
  entity_type: 'facility' | 'lane' | 'network'
  entity_id: string | null
  metric_value: number | null
  metric_unit: string | null
}

export interface NetworkOverview {
  context: NetworkOverviewContext
  kpis: NetworkOverviewKpis
  facilities: NetworkFacilityAggregate[]
  lanes: NetworkLaneAggregate[]
  insights: NetworkInsight[]
  summary: string
  source: string
  freshness_at: string
  is_partial: boolean
}


export type NetworkScenarioStatus =
  | 'draft'
  | 'validated'
  | 'solving'
  | 'solved'
  | 'infeasible'
  | 'failed'
  | 'depot_plans_running'
  | 'reconciliation_required'
  | 'reconciled'
  | 'published'

export interface NetworkScenarioAssumptions {
  disabled_facility_ids: string[]
  disabled_lane_ids: string[]
  lane_cost_adjustments_pct: Record<string, number>
  unmet_penalty_per_case: number
}

export interface NetworkScenarioValidationIssue {
  severity: 'error' | 'warning' | 'info'
  code: string
  scope: 'scenario' | 'plan' | 'facility' | 'lane' | 'rate'
  entity_id?: string | null
  message: string
}

export interface NetworkScenarioValidation {
  valid: boolean
  issues: NetworkScenarioValidationIssue[]
  summary: string
  validated_at: string
}

export interface NetworkScenario {
  scenario_id: string
  scenario_name: string
  baseline_scenario_id: string
  demand_plan_version_id: string
  capacity_plan_version_id: string
  horizon_start: string
  horizon_end: string
  region_id: string
  status: NetworkScenarioStatus
  revision: number
  assumptions: NetworkScenarioAssumptions
  validation: NetworkScenarioValidation | null
  created_at: string
  updated_at: string
  solved_at: string | null
}

export interface NetworkScenarioCreateRequest {
  scenario_name: string
  baseline_scenario_id?: string
  demand_plan_version_id: string
  capacity_plan_version_id: string
  horizon_start: string
  horizon_end: string
  region_id?: string
  assumptions?: NetworkScenarioAssumptions
}

export interface NetworkScenarioUpdateRequest {
  scenario_name?: string
  assumptions?: NetworkScenarioAssumptions
}

export interface NetworkScenarioKpiDeltas {
  demand_units: number
  assigned_units: number
  unmet_units: number
  total_cost: number
  cost_per_unit: number
  on_time_pct: number
  utilization_pct: number
}

export interface NetworkScenarioException {
  exception_id: string
  exception_type: 'unmet_demand' | 'capacity_constraint' | 'missing_rate' | 'disconnected_node'
  severity: 'info' | 'warning' | 'critical'
  service_date: string | null
  entity_type: 'network' | 'facility' | 'lane'
  entity_id: string | null
  message: string
  demand_units?: number | null
  assigned_units?: number | null
  unmet_units?: number | null
}

export interface NetworkFlowChargeDetail {
  service_date: string
  lane_id: string
  assigned_units: number
  loads: number
  rate_source: 'governed_contract' | 'planning_fallback'
  contract_id: string | null
  contract_version_id: string | null
  rate_book_snapshot_id: string | null
  total_cost: number
  charge_lines: RateChargeLine[]
}

export interface NetworkScenarioResult {
  scenario_id: string
  revision: number
  generated_at: string
  overview: NetworkOverview
  baseline_overview: NetworkOverview
  kpi_deltas: NetworkScenarioKpiDeltas
  affected_depot_ids: string[]
  charge_details: NetworkFlowChargeDetail[]
  exceptions: NetworkScenarioException[]
}

export interface NetworkScenarioRunResponse {
  scenario: NetworkScenario
  result: NetworkScenarioResult
}

export interface Carrier {
  carrier_id: string
  carrier_name: string
  active: boolean
}

export interface CarrierContract {
  contract_id: string
  carrier_id: string
  contract_name: string
  capacity_stops: number
  rate_per_mile: number
  rate_per_stop: number
  minimum_charge: number
  fuel_surcharge_pct: number
  effective_start: string | null
  effective_end: string | null
  active: boolean
}

export type RateContractStatus = 'draft' | 'published' | 'expired'
export type MileageRounding = 'exact' | 'nearest_mile' | 'up_to_mile'
export type FuelBasis = 'linehaul' | 'linehaul_and_minimum' | 'transportation_subtotal'
export type AccessorialChargeType = 'flat' | 'per_stop' | 'per_hour' | 'per_case'
export type VolumePeriod = 'route' | 'week' | 'month' | 'quarter'

export interface ContractVersion {
  version_id: string
  version_number: number
  status: RateContractStatus
  currency: string
  effective_start: string | null
  effective_end: string | null
  published_at: string | null
  published_by: string | null
  change_reason: string | null
}

export interface LaneRateRule {
  rule_id: string
  lane_name: string
  origin: string
  destination: string
  lane_type?: 'LINEHAUL' | 'MARKET' | 'DELIVERY' | null
  origin_endpoint_id?: string | null
  origin_endpoint_type?: 'facility' | 'market' | 'customer' | null
  destination_endpoint_id?: string | null
  destination_endpoint_type?: 'facility' | 'market' | 'customer' | null
  priority: number
  flat_rate: number
  rate_per_mile: number
  rate_per_stop: number
  included_stops: number
  minimum_charge: number
  mileage_rounding: MileageRounding
}

export interface FuelSurchargeRule {
  rule_id: string
  name: string
  rate_pct: number
  basis: FuelBasis
  effective_start: string | null
  effective_end: string | null
}

export interface AccessorialRule {
  rule_id: string
  code: string
  name: string
  charge_type: AccessorialChargeType
  rate: number
  description: string
}

export interface VolumeTierRule {
  rule_id: string
  name: string
  period: VolumePeriod
  unit: 'stops' | 'routes' | 'cases' | 'miles'
  min_volume: number
  max_volume: number | null
  discount_pct: number
}

export interface CapacityCommitmentRule {
  rule_id: string
  name: string
  period: VolumePeriod
  unit: 'stops' | 'routes' | 'cases' | 'miles'
  committed_quantity: number
  capacity_quantity: number
  current_utilization: number
  shortfall_rate: number
  overage_rate: number
}

export interface RateContractSummary {
  contract_id: string
  carrier_id: string
  carrier_name: string
  contract_name: string
  version: ContractVersion
  draft_version: ContractVersion | null
  status: RateContractStatus
  lane_count: number
  accessorial_count: number
  volume_tier_count: number
  committed_quantity: number
  capacity_quantity: number
  current_utilization: number
  coverage_status: 'covered' | 'partial' | 'unavailable'
  freshness_at: string
}

export interface RateContractDetail {
  contract_id: string
  carrier_id: string
  carrier_name: string
  contract_name: string
  version: ContractVersion
  lane_rates: LaneRateRule[]
  fuel_surcharges: FuelSurchargeRule[]
  accessorials: AccessorialRule[]
  volume_tiers: VolumeTierRule[]
  capacity_commitments: CapacityCommitmentRule[]
  version_history: ContractVersion[]
  source: string
  freshness_at: string
}

export interface RateAccessorialTemplate {
  code: string
  name: string
  charge_type: AccessorialChargeType
  rate: number
  description: string
}

export interface RateAuthoringOptions {
  destinations: string[]
  accessorials: RateAccessorialTemplate[]
}

export interface RateContractCreateRequest {
  carrier_id: string
  contract_name: string
  currency: string
  effective_start: string
  effective_end: string
}

export interface RateVersionCreateRequest {
  source_version_id?: string | null
  effective_start: string
  effective_end: string
  change_reason: string
}

export interface RateDraftUpdateRequest {
  contract_name: string
  currency: string
  effective_start: string
  effective_end: string
  change_reason: string
  lane_rates: LaneRateRule[]
  fuel_surcharges: FuelSurchargeRule[]
  accessorials: AccessorialRule[]
  volume_tiers: VolumeTierRule[]
  capacity_commitments: CapacityCommitmentRule[]
}

export interface RateValidationIssue {
  severity: 'error' | 'warning'
  code: string
  field: string
  message: string
}

export interface RateValidationResponse {
  contract_id: string
  version_id: string
  valid: boolean
  issues: RateValidationIssue[]
  summary: string
}

export interface RatePublishRequest {
  published_by?: string
  change_reason?: string
}

export type RateChargeCategory =
  | 'lane'
  | 'mileage'
  | 'stops'
  | 'volume_tier'
  | 'minimum'
  | 'fuel'
  | 'accessorial'
  | 'commitment'

export interface RateChargeLine {
  category: RateChargeCategory
  label: string
  formula: string
  quantity: number
  unit: string
  rate: number
  amount: number
  rule_id: string
}

export interface RateQuoteRequest {
  contract_id: string
  version_id?: string | null
  service_date: string
  origin: string
  destination: string
  miles: number
  stops: number
  cases: number
  period_volume: number
  accessorial_codes: string[]
  accessorial_quantities: Record<string, number>
  period_close?: boolean
  commitment_policy?: 'honor' | 'ignore'
}

export interface RateQuote {
  quote_id: string
  contract_id: string
  contract_name: string
  carrier_id: string
  carrier_name: string
  contract_version_id: string
  service_date: string
  origin: string
  destination: string
  matched_lane: string | null
  matched_lane_rule_id: string | null
  matched_volume_tier: string | null
  eligible: boolean
  eligibility_message: string
  charge_lines: RateChargeLine[]
  transportation_subtotal: number
  total_cost: number
  commitment_remaining: number
  capacity_remaining: number
  rate_book_snapshot_id: string
  warnings: string[]
}

export interface OperatingParameterSet {
  parameter_set_id: string
  parameter_set_name: string
  private_vehicle_limit: number
  max_route_minutes: number
  max_stops_per_route: number
  allow_overtime: boolean
  active: boolean
}

export interface CostParameterSet extends Required<CostOverride> {
  parameter_set_id: string
  max_route_minutes: number
  avg_speed_mph: number
  circuity: number
}

export interface Stop {
  stop_id: string
  customer_id: string
  customer_name: string
  sequence: number
  location: LatLng
  demand_cases: number
  service_minutes: number
  time_window_start: string
  time_window_end: string
  arrival_time: string
  departure_time: string
  delivery_day: string
  window_risk: WindowRisk
  is_new_customer: boolean
}

export interface Route {
  route_id: string
  scenario_id: string
  route_name: string
  depot_id: string
  driver_id: string
  driver_name: string
  vehicle_id: string
  delivery_day: string
  path: LatLng[]
  stops: Stop[]
  total_miles: number
  drive_minutes: number
  service_minutes: number
  total_cases: number
  capacity_cases: number
  capacity_utilization_pct: number
  driver_utilization_pct: number
  overtime_minutes: number
  missed_windows: number
  late_minutes: number
  total_cost: number
  fulfillment_method: 'private_fleet' | 'private_overtime' | 'carrier'
  carrier_name: string | null
  contract_name: string | null
  contract_version_id: string | null
  rated_service_date: string | null
  rate_lane: string | null
  rate_book_snapshot_id: string | null
  carrier_charge_lines: RateChargeLine[]
  decision_reason: string
}

export interface CostBreakdown {
  mileage_cost: number
  labor_cost: number
  overtime_cost: number
  fixed_vehicle_cost: number
  sla_penalty_cost: number
  carrier_linehaul_cost: number
  carrier_lane_cost: number
  carrier_stop_cost: number
  carrier_minimum_adjustment: number
  fuel_surcharge_cost: number
  accessorial_cost: number
  volume_tier_adjustment: number
  commitment_adjustment: number
  total_cost: number
}

export interface Kpis {
  route_count: number
  driver_count: number
  vehicle_count: number
  total_miles: number
  drive_minutes: number
  service_minutes: number
  total_cases: number
  avg_stops_per_route: number
  avg_capacity_utilization_pct: number
  avg_driver_utilization_pct: number
  overtime_minutes: number
  missed_windows: number
  late_minutes: number
  total_revenue: number
  profit: number
  cost_breakdown: CostBreakdown
}

export interface KpiDeltas {
  route_count: number
  driver_count: number
  vehicle_count: number
  total_miles: number
  drive_minutes: number
  service_minutes: number
  total_cases: number
  avg_stops_per_route: number
  avg_capacity_utilization_pct: number
  avg_driver_utilization_pct: number
  overtime_minutes: number
  missed_windows: number
  late_minutes: number
  total_revenue: number
  profit: number
  mileage_cost: number
  labor_cost: number
  overtime_cost: number
  fixed_vehicle_cost: number
  sla_penalty_cost: number
  carrier_linehaul_cost: number
  carrier_lane_cost: number
  carrier_stop_cost: number
  carrier_minimum_adjustment: number
  fuel_surcharge_cost: number
  accessorial_cost: number
  volume_tier_adjustment: number
  commitment_adjustment: number
  total_cost: number
}

export interface CustomerImpact {
  customer_id: string
  customer_name: string
  is_new_customer: boolean
  changed_route: boolean
  changed_day: boolean
  changed_depot: boolean
  sequence_shift: number
  baseline_day: string | null
  scenario_day: string | null
  baseline_route_id: string | null
  scenario_route_id: string | null
  window_risk: WindowRisk
  disruption_score: number
  summary: string
  fulfillment_method: 'private_fleet' | 'private_overtime' | 'carrier' | 'unserved'
  carrier_name: string | null
  decision_reason: string | null
}

export interface TransportationAllocation {
  fulfillment_method: 'private_fleet' | 'private_overtime' | 'carrier' | 'unserved'
  label: string
  deliveries: number
  cases: number
  miles: number
  cost: number
}

export interface DecisionExplanation {
  customer_id: string
  customer_name: string
  decision: string
  reason: string
}

export interface ConstraintViolation {
  violation_id: string
  severity: ConstraintSeverity
  scope: ConstraintScope
  ref_id: string | null
  route_id: string | null
  customer_id: string | null
  metric: string
  limit_value: number | null
  actual_value: number | null
  message: string
  recommendation: string
}

export interface ParameterOption {
  value: string
  label: string
}

export interface ParameterField {
  name: string
  label: string
  field_type: ParameterFieldType
  required: boolean
  default: unknown
  min: number | null
  max: number | null
  step: number | null
  options: ParameterOption[]
  placeholder: string | null
  help_text: string | null
}

export interface DeliveryDraft {
  customer_name: string
  lat: number
  lng: number
  demand_cases: number
  service_minutes: number
  receiving_window_start: string
  receiving_window_end: string
  delivery_day?: string | null
  customer_id?: string | null
}

export interface CostOverride {
  cost_per_mile?: number | null
  labor_regular_hour?: number | null
  overtime_multiplier?: number | null
  overtime_threshold_minutes?: number | null
  fixed_truck_daily_cost?: number | null
  late_delivery_penalty?: number | null
  missed_delivery_penalty?: number | null
}

export interface ScenarioChange {
  kind: ScenarioChangeKind
  deliveries?: DeliveryDraft[]
  driver_delta?: number | null
  allow_overtime?: boolean | null
  target_day?: string | null
  target_customers?: string | null
  new_depot_location?: LatLng | null
  preserve_service_windows?: boolean | null
}

/**
 * Browser-only identity for a stacked-change card. It must never cross the API
 * boundary because scenario changes are validated by a strict backend model.
 */
export interface DraftScenarioChange extends ScenarioChange {
  clientId: string
}

export interface DeliveryUploadError {
  row: number
  message: string
}

export interface DeliveryUploadResult {
  deliveries: DeliveryDraft[]
  errors: DeliveryUploadError[]
}

export interface ScenarioTypeSpec {
  scenario_type: ScenarioType
  label: string
  description: string
  result_stub_id: string
  fields: ParameterField[]
}

export interface ScenarioDefinition {
  scenario_id: string
  scenario_name: string
  scenario_type: ScenarioType
  baseline_scenario_id: string
  depot_id: string
  delivery_day: string
  parameters: Record<string, unknown>
  status: ScenarioLifecycleStatus
}

export interface ScenarioHistoryItem extends ScenarioDefinition {
  created_at: string
  has_results: boolean
}

export interface ScenarioCreateRequest {
  scenario_name: string
  scenario_type: ScenarioType
  baseline_scenario_id: string
  depot_id: string
  delivery_day: string
  parameters: Record<string, unknown>
}

export interface CreateScenarioResponse {
  scenario: ScenarioDefinition
  result_stub_id?: string
  /**
   * Returned by the durable-run API once the server owns validation and run
   * creation. Older deployments omit it, which the client handles by using
   * the validate-then-run endpoint sequence.
   */
  run?: RunStartResponse | null
  run_id?: string
  status?: RunStatus
  message?: string
  databricks_run_url?: string | null
}

export interface ValidationIssue {
  field?: string | null
  scope: ConstraintScope
  ref_id?: string | null
  severity: ConstraintSeverity
  message: string
}

export interface ValidationResponse {
  scenario_id: string
  valid: boolean
  hard_constraints: ValidationIssue[]
  soft_penalties: ValidationIssue[]
  missing_fields: string[]
  inferred_fields: string[]
  estimated_affected_customers: number
  estimated_affected_routes: number
  summary: string
}

export interface BaselineNetwork {
  scenario_id: 'baseline'
  depot: Depot
  delivery_day: string
  routes: Route[]
  matrix_source: MatrixSource
  generated_at: string
  summary: string
}

export interface RunStage {
  stage_id: string
  label: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  message: string
  duration_ms?: number | null
}

export interface RunStartResponse {
  run_id: string
  scenario_id: string
  status: RunStatus
  message: string
  databricks_run_url?: string | null
}

export interface RunStatusResponse {
  run_id: string
  scenario_id: string
  status: RunStatus
  progress_pct: number
  message: string
  stages: RunStage[]
  started_at: string
  completed_at: string | null
  databricks_run_url?: string | null
  /**
   * Present when the server-owned precheck has a validation result. It is
   * optional so current deployments that only expose stages remain supported.
   */
  validation?: ValidationResponse | null
  /**
   * New durable runs expose per-stage timing, including the synchronous create
   * phase. Older run endpoints can omit this during the cutover.
   */
  stage_durations_ms?: Record<string, number | null>
}

export interface ComparisonResult {
  scenario_id: string
  baseline_scenario_id: string
  scenario_name: string
  status: RunStatus
  matrix_source: MatrixSource
  generated_at: string
  summary: string
  baseline_depot: Depot
  scenario_depot: Depot
  baseline_routes: Route[]
  scenario_routes: Route[]
  baseline_kpis: Kpis
  scenario_kpis: Kpis | null
  kpi_deltas: KpiDeltas | null
  customer_impacts: CustomerImpact[]
  constraint_violations: ConstraintViolation[]
  transportation_allocation: TransportationAllocation[]
  decision_explanations: DecisionExplanation[]
  rate_book_snapshot_id?: string | null
}

export interface OperatingConstraints {
  parameter_set_id: string
  private_vehicle_limit: number
  max_route_minutes: number
  max_stops_per_route: number
  allow_overtime: boolean
}

export interface TransportationChoices {
  allow_private_fleet: boolean
  allow_carrier: boolean
  carrier_id: string
  contract_id: string
  contract_selection: 'automatic' | 'locked'
  eligible_carrier_ids: string[]
  commitment_policy: 'honor' | 'ignore'
  accessorial_codes: string[]
}

export interface PricingContext {
  service_date: string
  horizon_end: string
  projected_period_stops: number
}

export type EditorEntityType =
  | 'orders'
  | 'customers'
  | 'fleet'
  | 'depots'
  | 'cost_parameters'
  | 'carriers'
  | 'carrier_contracts'
  | 'operating_parameters'
  | 'revenue_parameters'

export type EditorSessionStatus =
  | 'open'
  | 'committed'
  | 'discarded'
  | 'expired'

export type EditorRowState = 'unchanged' | 'inserted' | 'updated'

export interface EditorSession {
  session_id: string
  principal: string
  status: EditorSessionStatus
  created_at: string
  updated_at: string
  expires_at: string
  has_unsaved_changes: boolean
  entity_counts: Record<EditorEntityType, number>
}

export interface EditorRow {
  entity_type: EditorEntityType
  row_id: string
  row_version: number
  state: EditorRowState
  data: Record<string, unknown>
}

export interface EditorPage {
  session: EditorSession
  entity_type: EditorEntityType
  page: number
  page_size: number
  total: number
  rows: EditorRow[]
}

export interface EditorInsertRequest {
  data: Record<string, unknown>
}

export interface EditorPatchRequest {
  row_version: number
  changes: Record<string, unknown>
}

export interface EditorDeleteRequest {
  row_version: number
}

export interface EditorValidationIssue {
  entity_type: EditorEntityType
  row_id: string
  field: string | null
  code: string
  message: string
}

export interface EditorValidationResponse {
  session: EditorSession
  valid: boolean
  issues: EditorValidationIssue[]
}

export interface EditorPreviewRequest {
  depot_id: string
  delivery_day: string
}

export interface EditorPreviewResponse {
  session: EditorSession
  network: BaselineNetwork
  kpis: Kpis
}

export interface EditorCommitResponse {
  session: EditorSession
  baseline_snapshot_count: number
}
