from __future__ import annotations

import json

import pytest

from backend.models import BaselineNetwork, ComparisonResult, Kpis
from route_opt.baseline import reconstruct_baseline, summarize_kpis
from route_opt.compare import compare_scenario
from route_opt.cost import CostParameters, route_cost, total_cost_is_consistent
from route_opt.dq import validate_kpi_contract
from route_opt.overrides import (
    apply_overrides,
    build_scenario_overrides,
    resolve_cost_override,
    seed_override_tables,
    seed_scenario_definitions,
)
from route_opt.solver import solve_scenario_partition
from route_opt.solver.payload import INPUT_SCHEMA, make_input_row
from route_opt.synthetic import generate_all


def _generated():
    return generate_all(seed=42, customer_count=250)


def test_synthetic_data_shape_and_narrative_anchor() -> None:
    data = _generated()
    assert len(data["depot_master"]) == 3
    assert len(data["location_data"]) == 250
    north_tuesday_orders = [
        row
        for row in data["fact_delivery_orders"]
        if row["depot_id"] == "DPT_NORTH" and row["delivery_day"] == "Tuesday"
    ]
    assert len(north_tuesday_orders) == 24
    assert sum(int(row["demand_cases"]) for row in north_tuesday_orders) == 2840
    assert all("confidence_level" in row for row in data["location_data"])
    customers = {row["customer_id"]: row for row in data["location_data"]}
    assert (customers["CUST-001"]["lat"], customers["CUST-001"]["lng"]) == (42.388, -82.934)
    assert (customers["CUST-002"]["lat"], customers["CUST-002"]["lng"]) == (42.456, -82.911)
    assert (customers["CUST-006"]["lat"], customers["CUST-006"]["lng"]) == (42.33, -82.95)


def test_baseline_reconstructs_contract_and_metric_ranges() -> None:
    data = _generated()
    baseline = reconstruct_baseline(
        data["depot_master"],
        data["location_data"],
        data["fact_delivery_orders"],
        data["fleet_assets"],
    )
    assert BaselineNetwork.model_validate(baseline["network"])
    assert Kpis.model_validate(baseline["kpis"])
    assert baseline["kpis"]["route_count"] == 4
    assert baseline["kpis"]["total_cases"] == 2840
    assert baseline["kpis"]["total_miles"] == 229.9
    assert baseline["kpis"]["drive_minutes"] == 363
    assert validate_kpi_contract(baseline["kpis"], baseline=True) == []


def test_cost_model_has_consistent_components() -> None:
    costs = route_cost(miles=286, route_minutes=515, late_stops=0, missed_stops=0)
    assert costs["total_cost"] > 0
    assert total_cost_is_consistent(costs)


def test_apply_overrides_materializes_every_scenario_type() -> None:
    data = _generated()
    scenarios = {row["scenario_id"]: row for row in seed_scenario_definitions()}
    overrides = seed_override_tables(data["location_data"])

    baseline = apply_overrides(
        scenario=scenarios["baseline"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    assert len(baseline["scenario_planning_stops"]) == 24

    ma = apply_overrides(
        scenario=scenarios["scn_ma_newcustomers"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    assert any(row["customer_id"] == "NEW-MA-001" for row in ma["scenario_planning_customers"])

    growth = apply_overrides(
        scenario=scenarios["scn_new_customer_growth"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    assert any(row["customer_id"] == "NEW-GROWTH-001" for row in growth["scenario_planning_customers"])

    driver = apply_overrides(
        scenario=scenarios["scn_driver_minus_one"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    assert len(driver["scenario_planning_fleet"]) == 3

    day_change = apply_overrides(
        scenario=scenarios["scn_day_change"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    assert len(day_change["scenario_planning_stops"]) < len(baseline["scenario_planning_stops"])

    facility = apply_overrides(
        scenario=scenarios["scn_facility_move"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    assert facility["scenario_planning_depots"][0]["lng"] == -84.8000

    custom = apply_overrides(
        scenario=scenarios["scn_custom_composite"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    assert any(row["customer_id"] == "NEW-CUSTOM-001" for row in custom["scenario_planning_customers"])
    assert len(custom["scenario_planning_fleet"]) == 3
    assert resolve_cost_override(overrides, "scn_custom_composite")["cost_per_mile"] == 4.5


def test_custom_build_and_apply_composes_driver_and_delivery_changes() -> None:
    data = _generated()
    depot = next(row for row in data["depot_master"] if row["depot_id"] == "DPT_NORTH")
    overrides = build_scenario_overrides(
        scenario_id="scn_test_custom",
        scenario_type="custom",
        depot_id="DPT_NORTH",
        delivery_day="Tuesday",
        parameters={
            "changes": [
                {
                    "kind": "driver_count_change",
                    "driver_delta": -1,
                    "allow_overtime": True,
                },
                {
                    "kind": "add_deliveries",
                    "deliveries": [
                        {
                            "customer_name": "Pinned Market",
                            "lat": 42.4,
                            "lng": -83.1,
                            "demand_cases": 70,
                            "service_minutes": 25,
                            "receiving_window_start": "09:00",
                            "receiving_window_end": "15:00",
                        }
                    ],
                },
            ],
            "cost": {"cost_per_mile": 4.5},
        },
        depot=depot,
    )
    assert len(overrides["scenario_customer_overrides"]) == 1
    assert overrides["scenario_fleet_overrides"][0]["driver_delta"] == -1
    assert overrides["scenario_cost_overrides"][0]["cost_per_mile"] == 4.5

    planning = apply_overrides(
        scenario={
            "scenario_id": "scn_test_custom",
            "scenario_type": "custom",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
        },
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    assert any(row["customer_name"] == "Pinned Market" for row in planning["scenario_planning_customers"])
    assert len(planning["scenario_planning_fleet"]) == 3


def test_cost_parameter_merge_raises_mileage_cost() -> None:
    base = CostParameters()
    raised = base.merged({"cost_per_mile": 4.5})
    base_cost = route_cost(miles=100, route_minutes=60, params=base)
    raised_cost = route_cost(miles=100, route_minutes=60, params=raised)
    assert raised_cost["mileage_cost"] > base_cost["mileage_cost"]
    assert total_cost_is_consistent(raised_cost)
    assert raised.cost_per_mile == 4.5
    assert raised.labor_regular_hour == base.labor_regular_hour


def test_make_input_row_includes_cost_parameters() -> None:
    row = make_input_row(
        scenario_id="scn_x",
        depot_id="DPT_NORTH",
        delivery_day="Tuesday",
        planning_depots=[],
        planning_customers=[],
        planning_fleet=[],
        planning_stops=[],
        cost_parameters={"cost_per_mile": 4.5, "labor_regular_hour": 80.0},
    )
    assert "cost_parameters" in row
    decoded = json.loads(str(row["cost_parameters"]))
    assert decoded["cost_per_mile"] == 4.5


def test_route_solver_model_signature_includes_cost_parameters() -> None:
    assert dict(INPUT_SCHEMA)["cost_parameters"] == "string"


def test_solver_and_comparison_contracts_for_feasible_and_infeasible_scenarios() -> None:
    data = _generated()
    scenarios = {row["scenario_id"]: row for row in seed_scenario_definitions()}
    overrides = seed_override_tables(data["location_data"])
    baseline_result = reconstruct_baseline(
        data["depot_master"],
        data["location_data"],
        data["fact_delivery_orders"],
        data["fleet_assets"],
    )
    baseline_depot = next(row for row in data["depot_master"] if row["depot_id"] == "DPT_NORTH")

    driver = apply_overrides(
        scenario=scenarios["scn_driver_minus_one"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    driver_solution = solve_scenario_partition(
        scenario_id="scn_driver_minus_one",
        depot_id="DPT_NORTH",
        delivery_day="Tuesday",
        planning_depots=driver["scenario_planning_depots"],
        planning_customers=driver["scenario_planning_customers"],
        planning_fleet=driver["scenario_planning_fleet"],
        planning_stops=driver["scenario_planning_stops"],
    )
    assert len(driver_solution["routes"]) == 3
    driver_comparison = compare_scenario(
        scenario=scenarios["scn_driver_minus_one"],
        baseline_result=baseline_result,
        solution=driver_solution,
        baseline_depot=baseline_depot,
        scenario_depot=driver["scenario_planning_depots"][0],
    )
    assert ComparisonResult.model_validate(driver_comparison)
    assert driver_comparison["kpi_deltas"]["driver_count"] == -1

    facility = apply_overrides(
        scenario=scenarios["scn_facility_move"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    facility_solution = solve_scenario_partition(
        scenario_id="scn_facility_move",
        depot_id="DPT_NORTH",
        delivery_day="Tuesday",
        planning_depots=facility["scenario_planning_depots"],
        planning_customers=facility["scenario_planning_customers"],
        planning_fleet=facility["scenario_planning_fleet"],
        planning_stops=facility["scenario_planning_stops"],
    )
    facility_comparison = compare_scenario(
        scenario=scenarios["scn_facility_move"],
        baseline_result=baseline_result,
        solution=facility_solution,
        baseline_depot=baseline_depot,
        scenario_depot=facility["scenario_planning_depots"][0],
    )
    assert ComparisonResult.model_validate(facility_comparison)
    assert facility_comparison["status"] == "infeasible"
    assert facility_comparison["constraint_violations"]
    assert facility_solution["unassigned_stops"]


def test_real_solver_constraints_and_metric_ranges_across_scenarios() -> None:
    data = _generated()
    scenarios = {row["scenario_id"]: row for row in seed_scenario_definitions()}
    overrides = seed_override_tables(data["location_data"])

    expected_route_counts = {
        "scn_ma_newcustomers": 4,
        "scn_new_customer_growth": 4,
        "scn_driver_minus_one": 3,
        "scn_day_change": 3,
    }
    for scenario_id, expected_route_count in expected_route_counts.items():
        planning = apply_overrides(
            scenario=scenarios[scenario_id],
            customers=data["location_data"],
            depots=data["depot_master"],
            fleet=data["fleet_assets"],
            orders=data["fact_delivery_orders"],
            override_tables=overrides,
        )
        solution = solve_scenario_partition(
            scenario_id=scenario_id,
            depot_id="DPT_NORTH",
            delivery_day="Tuesday",
            planning_depots=planning["scenario_planning_depots"],
            planning_customers=planning["scenario_planning_customers"],
            planning_fleet=planning["scenario_planning_fleet"],
            planning_stops=planning["scenario_planning_stops"],
        )
        assert len(solution["routes"]) == expected_route_count
        assert solution["unassigned_stops"] == []
        assert all(
            int(route["drive_minutes"]) + int(route["service_minutes"]) <= 600
            for route in solution["routes"]
        )
        assert sum(int(route["missed_windows"]) for route in solution["routes"]) == 0
        assert validate_kpi_contract(summarize_kpis(solution["routes"])) == []

    day_change = apply_overrides(
        scenario=scenarios["scn_day_change"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    baseline = apply_overrides(
        scenario=scenarios["baseline"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    assert len(day_change["scenario_planning_stops"]) < len(baseline["scenario_planning_stops"])


def test_pyfunc_model_log_load_and_predict_when_mlflow_runtime_is_available(tmp_path) -> None:
    mlflow = pytest.importorskip("mlflow")
    pytest.importorskip("mlflow.pyfunc")
    pd = pytest.importorskip("pandas")

    from route_opt.solver.pyfunc_model import (
        RouteScenarioSolverModel,
        make_input_row,
        route_solver_model_signature,
    )

    data = _generated()
    scenarios = {row["scenario_id"]: row for row in seed_scenario_definitions()}
    overrides = seed_override_tables(data["location_data"])
    planning = apply_overrides(
        scenario=scenarios["scn_driver_minus_one"],
        customers=data["location_data"],
        depots=data["depot_master"],
        fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"],
        override_tables=overrides,
    )
    model_input = pd.DataFrame(
        [
            make_input_row(
                scenario_id="scn_driver_minus_one",
                depot_id="DPT_NORTH",
                delivery_day="Tuesday",
                planning_depots=planning["scenario_planning_depots"],
                planning_customers=planning["scenario_planning_customers"],
                planning_fleet=planning["scenario_planning_fleet"],
                planning_stops=planning["scenario_planning_stops"],
                time_limit_seconds=1,
            )
        ]
    )
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    mlflow.set_experiment("route-solver-pyfunc-test")
    with mlflow.start_run():
        model_info = mlflow.pyfunc.log_model(
            artifact_path="route_solver",
            python_model=RouteScenarioSolverModel(),
            pip_requirements=[],
            signature=route_solver_model_signature(),
            input_example=model_input,
        )
    loaded = mlflow.pyfunc.load_model(model_info.model_uri)
    assert "cost_parameters" in str(loaded.metadata.signature.inputs)
    prediction = loaded.predict(model_input)
    routes = json.loads(prediction.loc[0, "routes"])
    assert len(routes) == 3

    overridden_input = model_input.copy()
    overridden_input.loc[0, "cost_parameters"] = json.dumps({"cost_per_mile": 9.0})
    overridden_prediction = loaded.predict(overridden_input)
    overridden_routes = json.loads(overridden_prediction.loc[0, "routes"])
    assert sum(float(route["total_cost"]) for route in overridden_routes) > sum(
        float(route["total_cost"]) for route in routes
    )
