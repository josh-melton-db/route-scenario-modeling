export type ScenarioType =
  | 'baseline'
  | 'ma_new_customers'
  | 'new_customer_growth'
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

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'infeasible' | 'failed'
export type ConstraintSeverity = 'hard' | 'soft'
export type ConstraintScope = 'route' | 'depot' | 'customer' | 'scenario'
export type WindowRisk = 'none' | 'at_risk' | 'missed'
export type MatrixSource = 'haversine_circuity'
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
}

export interface CostBreakdown {
  mileage_cost: number
  labor_cost: number
  overtime_cost: number
  fixed_vehicle_cost: number
  sla_penalty_cost: number
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
  mileage_cost: number
  labor_cost: number
  overtime_cost: number
  fixed_vehicle_cost: number
  sla_penalty_cost: number
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
  result_stub_id: string
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
  status: 'pending' | 'running' | 'completed' | 'failed'
  message: string
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
}
