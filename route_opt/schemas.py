from __future__ import annotations

from typing import Literal

ScenarioType = Literal[
    "baseline",
    "ma_new_customers",
    "new_customer_growth",
    "driver_count_change",
    "delivery_frequency_day_change",
    "facility_move",
]

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
BASELINE_SCENARIO_ID = "baseline"
MATRIX_SOURCE = "haversine_circuity"

RAW_TABLES = [
    "depot_master",
    "location_data",
    "fleet_assets",
    "drivers",
    "fact_customer_product_demand",
    "fact_delivery_orders",
    "cost_parameters",
]

GOLD_TABLES = [
    "dim_depots_augmented",
    "dim_customers_augmented",
    "dim_customer_constraints",
    "dim_fleet_assets",
    "dim_drivers",
    "fact_customer_product_demand",
    "fact_delivery_orders",
    "cost_parameters",
]

SCENARIO_TABLES = [
    "scenario_definitions",
    "scenario_parameters",
    "scenario_customer_overrides",
    "scenario_fleet_overrides",
    "scenario_depot_overrides",
    "scenario_frequency_overrides",
    "scenario_planning_customers",
    "scenario_planning_depots",
    "scenario_planning_fleet",
    "scenario_planning_stops",
]

OUTPUT_TABLES = [
    "baseline_routes",
    "baseline_route_stops",
    "baseline_route_kpis",
    "baseline_route_daily_summary",
    "matrix_nodes",
    "travel_time_matrix",
    "optimizer_runs",
    "optimized_routes",
    "optimized_route_stops",
    "optimized_route_metrics",
    "optimized_unassigned_stops",
    "optimization_solver_diagnostics",
    "scenario_comparison_summary",
    "scenario_kpis",
    "scenario_route_delta",
    "scenario_customer_impact",
    "scenario_constraint_violations",
    "scenario_cost_breakdown",
]

METRIC_VIEWS = [
    "mv_route_performance",
    "mv_scenario_comparison",
    "mv_customer_service_impact",
    "mv_fleet_capacity_utilization",
    "mv_depot_network_health",
]


def stable_id(prefix: str, number: int, width: int = 3) -> str:
    return f"{prefix}-{number:0{width}d}"
