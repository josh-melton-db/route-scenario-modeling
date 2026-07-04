# Databricks notebook source
import sys
from pathlib import PurePosixPath

try:
    notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()  # type: ignore[name-defined]
    bundle_root = str(PurePosixPath(notebook_path).parent.parent)
    candidates = [bundle_root]
    if not bundle_root.startswith("/Workspace/"):
        candidates.append(f"/Workspace{bundle_root}")
    for candidate in candidates:
        if candidate not in sys.path:
            sys.path.append(candidate)
except Exception:
    pass

import json

from route_opt.baseline import reconstruct_baseline, summarize_kpis
from route_opt.compare import compare_scenario
from route_opt.config import config_from_widgets, get_widget_value
from route_opt.spark_io import collect_dicts, write_rows_as_table

config = config_from_widgets()
scenario_filter = get_widget_value("scenario_id", "").strip()

def _rehydrate_route(row):
    route = dict(row)
    path = route.get("path")
    if isinstance(path, str):
        route["path"] = json.loads(path)
    return route

depots = collect_dicts(spark.table(config.table("dim_depots_augmented")))
customers = collect_dicts(spark.table(config.table("dim_customers_augmented")))
orders = collect_dicts(spark.table(config.table("fact_delivery_orders")))
fleet = collect_dicts(spark.table(config.table("dim_fleet_assets")))
baseline = reconstruct_baseline(depots, customers, orders, fleet)
baseline_depot = next(row for row in depots if row["depot_id"] == "DPT_NORTH")

scenarios = collect_dicts(spark.table(config.table("scenario_definitions")))
if scenario_filter:
    scenarios = [row for row in scenarios if row["scenario_id"] == scenario_filter]
planning_depots = collect_dicts(spark.table(config.table("scenario_planning_depots")))
routes = [_rehydrate_route(row) for row in collect_dicts(spark.table(config.table("optimized_routes")))]
stops = collect_dicts(spark.table(config.table("optimized_route_stops")))
diagnostics = collect_dicts(spark.table(config.table("optimization_solver_diagnostics")))
if scenario_filter:
    planning_depots = [row for row in planning_depots if row["scenario_id"] == scenario_filter]
    baseline_ids = {row["baseline_scenario_id"] for row in scenarios}
    routes = [row for row in routes if row["scenario_id"] == scenario_filter or row["scenario_id"] in baseline_ids]
    stops = [row for row in stops if row["scenario_id"] == scenario_filter or row["scenario_id"] in baseline_ids]
    diagnostics = [row for row in diagnostics if row["scenario_id"] == scenario_filter]

comparison_rows = []
kpi_rows = []
route_delta_rows = []
impact_rows = []
violation_rows = []
cost_rows = []
payload_rows = []

for scenario in scenarios:
    scenario_id = scenario["scenario_id"]
    baseline_id = scenario["baseline_scenario_id"]
    scenario_depot = next(
        row for row in planning_depots if row["scenario_id"] == scenario_id and row["depot_id"] == scenario["depot_id"]
    )
    baseline_routes = [row for row in routes if row["scenario_id"] == baseline_id]
    baseline_stops = [row for row in stops if row["scenario_id"] == baseline_id]
    baseline_result = (
        {"routes": baseline_routes, "route_stops": baseline_stops, "kpis": summarize_kpis(baseline_routes)}
        if baseline_routes
        else baseline
    )
    solution = {
        "routes": [row for row in routes if row["scenario_id"] == scenario_id],
        "route_stops": [row for row in stops if row["scenario_id"] == scenario_id],
        "diagnostics": [row for row in diagnostics if row["scenario_id"] == scenario_id],
    }
    result = compare_scenario(
        scenario=scenario,
        baseline_result=baseline_result,
        solution=solution,
        baseline_depot=baseline_depot,
        scenario_depot=scenario_depot,
    )
    payload_rows.append({"scenario_id": scenario_id, "payload_json": result})
    if result["scenario_kpis"]:
        kpis = result["scenario_kpis"]
        flat = {k: v for k, v in kpis.items() if k != "cost_breakdown"}
        flat.update(kpis["cost_breakdown"])
        kpi_rows.append(
            {
                "scenario_id": scenario_id,
                "scenario_type": scenario["scenario_type"],
                "depot_id": scenario["depot_id"],
                "delivery_day": scenario["delivery_day"],
                **flat,
            }
        )
        cost_rows.append(
            {
                "scenario_id": scenario_id,
                "depot_id": scenario["depot_id"],
                "delivery_day": scenario["delivery_day"],
                **kpis["cost_breakdown"],
            }
        )
    deltas = result["kpi_deltas"] or {}
    comparison_rows.append(
        {
            "scenario_id": scenario_id,
            "scenario_type": scenario["scenario_type"],
            "depot_id": scenario["depot_id"],
            "delivery_day": scenario["delivery_day"],
            "status": result["status"],
            "total_cost_delta": deltas.get("total_cost", 0),
            "total_miles_delta": deltas.get("total_miles", 0),
            "route_count_delta": deltas.get("route_count", 0),
            "impacted_customer_count": len(result["customer_impacts"]),
            "summary": result["summary"],
        }
    )
    for impact in result["customer_impacts"]:
        impact_rows.append({"scenario_id": scenario_id, **impact})
    for violation in result["constraint_violations"]:
        violation_rows.append({"scenario_id": scenario_id, **violation})
    for route in result["scenario_routes"]:
        route_delta_rows.append(
            {
                "scenario_id": scenario_id,
                "route_id": route["route_id"],
                "depot_id": route["depot_id"],
                "delivery_day": route["delivery_day"],
                "total_miles": route["total_miles"],
                "total_cost": route["total_cost"],
                "missed_windows": route["missed_windows"],
            }
        )

replace_where = f"scenario_id = '{scenario_filter}'" if scenario_filter else None
write_rows_as_table(spark, comparison_rows, config.table("scenario_comparison_summary"), replace_where=replace_where)
write_rows_as_table(spark, kpi_rows, config.table("scenario_kpis"), replace_where=replace_where)
write_rows_as_table(spark, route_delta_rows, config.table("scenario_route_delta"), replace_where=replace_where)
write_rows_as_table(spark, impact_rows, config.table("scenario_customer_impact"), replace_where=replace_where)
write_rows_as_table(spark, violation_rows, config.table("scenario_constraint_violations"), replace_where=replace_where)
write_rows_as_table(spark, cost_rows, config.table("scenario_cost_breakdown"), replace_where=replace_where)
write_rows_as_table(spark, payload_rows, config.table("app_scenario_results"), replace_where=replace_where)

print(f"Compared {len(comparison_rows)} scenarios for {scenario_filter or 'all scenarios'}.")
