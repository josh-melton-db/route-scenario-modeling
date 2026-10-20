from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.depot_plan_models import OverrideRequest
from backend.models import Route, Stop
from backend.services.depot_contracted_overflow import apply_contracted_overflow
from backend.tests.test_depot_contracted_overflow import DATE, contract, inputs
from route_opt.baseline import build_route_from_ordered_stops, summarize_kpis
from route_opt.cost import CostParameters


def fleet_input(count=2):
    solved, rows = inputs(count)
    if count == 2:
        rows["dim_network_customers"][1].update(lat=40, lng=-87)
    stops = [{**customer, "customer_name": customer["customer_id"], "demand_cases": 5}
             for customer in rows["dim_network_customers"]]
    route, sequence = build_route_from_ordered_stops(
        scenario_id="test", route_number=1, depot={**rows["dim_facilities"][0], "depot_id": "DPT"},
        ordered_stops=stops, delivery_day=DATE, params=CostParameters(), vehicle_id="V", driver_id="D")
    route["stops"] = [{**stop, "stop_id": stop["customer_id"],
                       "delivery_day": DATE, "location": {"lat": stop["lat"], "lng": stop["lng"]}}
                      for stop in sequence]
    route["total_revenue"] = count * 5 * 6.25
    solved.update(routes=[route], kpis=summarize_kpis([route]), routed_cases=count * 5,
                  unserved_cases=0, unserved_orders=[])
    solved["routes"] = [{key: value for key, value in route.items() if key in Route.model_fields}]
    solved["routes"][0]["stops"] = [{key: value for key, value in stop.items() if key in Stop.model_fields}
                                    for stop in route["stops"]]
    return solved, rows


def run(solved, rows, details, **kwargs):
    apply_contracted_overflow(solved, network_rows=rows, depot_id="DPT", service_date=DATE,
                              cost_parameters=CostParameters(), contract_details=details, enabled=True,
                              allow_cost_based_outsourcing=True, **kwargs)


@pytest.mark.parametrize("count,rate", [(2, 10), (7, 100)])
def test_whole_route_avoids_all_vehicle_shift_and_mileage_costs(count, rate):
    solved, rows = fleet_input(count)
    original_cost = solved["kpis"]["cost_breakdown"]["total_cost"]
    run(solved, rows, [contract(rate_per_stop=rate)])
    assert solved["routes"] == []
    assert solved["fleet_cost"] == 0
    assert solved["outsourcing_savings"] == pytest.approx(original_cost - count * rate)
    for field in ("route_count", "driver_count", "vehicle_count"):
        assert solved["kpis"][field] == 0


@pytest.mark.parametrize("matrix_miles", [0.1, 1000])
def test_existing_overflow_uses_consistent_basis_and_never_exceeds_off_path(matrix_miles):
    solved, rows = fleet_input()
    rows["dim_network_customers"].append({**rows["dim_network_customers"][0], "customer_id": "C2"})
    solved["unserved_orders"] = [{"customer_id": "C2", "demand_cases": 5, "reason": "no_vehicle_available"}]
    solved.update(assigned_cases=15, unserved_cases=5)
    nodes = ["DPT:DEPOT", "C0", "C1", "C2"]
    solved["_cost_based_matrix"] = [
        {"origin_id": origin, "destination_id": destination,
         "distance_miles": matrix_miles, "duration_minutes": 1}
        for origin in nodes for destination in nodes]
    before = deepcopy(solved)
    details = [contract(rate_per_stop=1000, rate_per_mile=100)]
    apply_contracted_overflow(before, network_rows=rows, depot_id="DPT", service_date=DATE,
                              cost_parameters=CostParameters(), contract_details=details, enabled=True)
    run(solved, rows, details)
    assert solved["outsourced_by_cost_deliveries"] == 0
    assert solved["outsourcing_savings"] == 0
    assert solved["kpis"]["cost_breakdown"]["total_cost"] <= before["kpis"]["cost_breakdown"]["total_cost"]
    if matrix_miles == 1000:
        assert solved["contracted_cost"] == before["contracted_cost"]


def test_cheaper_carrier_is_deterministic_feasible_and_preserves_revenue():
    original, rows = fleet_input()
    first, second = deepcopy(original), deepcopy(original)
    details = [contract()]
    run(first, rows, details)
    run(second, rows, details)
    assert first == second
    assert first["outsourced_by_cost_deliveries"] > 0
    assert all(order["decision_reason"] == "outsourced_by_cost" for order in first["contracted_orders"])
    assert first["kpis"]["total_revenue"] == original["kpis"]["total_revenue"]
    assert first["kpis"]["cost_breakdown"]["total_cost"] < original["kpis"]["cost_breakdown"]["total_cost"]
    assert first["routed_cases"] + first["contracted_cases"] == 10
    assert sum(route["total_cost"] for route in first["routes"]) == pytest.approx(first["fleet_cost"])
    for route in first["routes"]:
        assert route["missed_windows"] == 0
        assert route["total_cases"] <= route["capacity_cases"]
        assert route["drive_minutes"] + route["service_minutes"] <= 600
    assert len({order["customer_id"] for order in first["contracted_orders"]}) == first["contracted_deliveries"]
    assert sum(quote["total_cost"] for quote in first["contracted_quotes"]) == first["contracted_cost"]
    assert sum(route["total_cost"] for route in first["contracted_routes"]) == first["contracted_cost"]
    assert not {route["route_id"] for route in first["routes"]} & {route["route_id"] for route in first["contracted_routes"]}
    for route in [*first["routes"], *first["contracted_routes"]]:
        Route.model_validate(route)


def test_expensive_carrier_stays_on_fleet():
    solved, rows = fleet_input()
    original = deepcopy(solved)
    run(solved, rows, [contract(rate_per_stop=10000)])
    assert solved["routes"] == original["routes"]
    assert solved["outsourced_by_cost_deliveries"] == 0
    assert solved["kpis"]["cost_breakdown"]["total_cost"] == original["kpis"]["cost_breakdown"]["total_cost"]


def test_capacity_prevents_outsourcing():
    solved, rows = fleet_input()
    detail = contract()
    detail["capacity_commitments"] = [{"name": "Capacity", "rule_id": "CAP", "capacity_quantity": 0, "current_utilization": 0,
                                        "unit": "stops", "period": "monthly"}]
    run(solved, rows, [detail])
    assert solved["outsourced_by_cost_deliveries"] == 0


def test_option_off_unchanged():
    solved, rows = fleet_input()
    arguments = dict(network_rows=rows, depot_id="DPT", service_date=DATE,
                     cost_parameters=CostParameters(), contract_details=[contract()], enabled=True)
    apply_contracted_overflow(solved, **arguments)
    golden = json.loads((Path(__file__).parent / "fixtures/carrier_choice_off.json").read_text())
    assert {field: solved[field] for field in golden} == golden
    assert "allow_cost_based_outsourcing" not in solved["execution"]


def test_requires_overflow():
    with pytest.raises(ValueError, match="requires.*overflow"):
        OverrideRequest(route_scenario_id="named", allow_cost_based_outsourcing=True)


def test_graduated_tiers_apply_to_choice_and_overflow_together():
    from backend.tests.test_overflow_volume_tiers import tiered

    solved, rows = fleet_input()
    run(solved, rows, [tiered()], projected_period_volume=49)
    assert solved["contracted_deliveries"] == 2
    assert solved["contracted_cost"] == 19
    assert [band["units"] for band in solved["contracted_quotes"][0]["tier_breakdown"]["bands"]] == [1, 1]


@pytest.mark.parametrize("rate", [0, 1, 20, 100, 1000, 10000])
def test_cost_never_increases_against_overflow_only(rate):
    solved, rows = fleet_input()
    baseline = deepcopy(solved)
    details = [contract(rate_per_stop=rate)]
    apply_contracted_overflow(baseline, network_rows=rows, depot_id="DPT", service_date=DATE,
                              cost_parameters=CostParameters(), contract_details=details, enabled=True)
    run(solved, rows, details)
    assert solved["kpis"]["cost_breakdown"]["total_cost"] <= baseline["kpis"]["cost_breakdown"]["total_cost"]
    assert solved["kpis"]["total_revenue"] == baseline["kpis"]["total_revenue"]


def test_shared_minimum_can_make_a_chunk_cheaper_when_no_single_stop_is():
    solved, rows = fleet_input()
    route = solved["routes"][0]
    route["stops"][1]["location"] = {"lat": 38.9, "lng": -85.9}
    rows["dim_network_customers"][1].update(lat=38.9, lng=-85.9)
    run(solved, rows, [contract(rate_per_stop=0, minimum_charge=100)])
    assert solved["outsourced_by_cost_deliveries"] == 2


def test_colocated_stops_can_be_cheaper_as_a_chunk_with_zero_individual_marginals():
    solved, rows = fleet_input()
    solved["routes"][0]["stops"][1]["location"] = deepcopy(solved["routes"][0]["stops"][0]["location"])
    rows["dim_network_customers"][1].update(lat=39.1, lng=-86.1)
    run(solved, rows, [contract()])
    assert solved["outsourced_by_cost_deliveries"] == 2


def test_overflow_off_ignores_choice_without_mutating_result():
    solved, rows = fleet_input()
    original = deepcopy(solved)
    apply_contracted_overflow(solved, network_rows=rows, depot_id="DPT", service_date=DATE,
                              cost_parameters=CostParameters(), contract_details=[contract()], enabled=False,
                              allow_cost_based_outsourcing=True)
    assert solved == original


def test_service_persists_and_rolls_up_choice_without_changing_default(monkeypatch):
    from backend.tests.test_depot_plan_service import _service, DEPOT_ID, DATE_ONE
    from backend.models import RateContractDetail

    detail = RateContractDetail.model_validate(contract(origin=DEPOT_ID, origin_endpoint_id=DEPOT_ID,
                                                       rate_per_stop=0))
    monkeypatch.setattr("backend.services.depot_plans.list_rate_contract_details", lambda store: [detail])
    service, _, jobs, _, _ = _service()
    plan = service.get_or_create_plan("RUN", DEPOT_ID)
    while jobs.run_next():
        pass
    baseline = service.get_day(plan.plan_set_id, DATE_ONE).default_result.model_dump(mode="json")
    scenario = service.create_scenario(plan.plan_set_id, "Choice")
    service.optimize_day(plan.plan_set_id, DATE_ONE, {
        "route_scenario_id": scenario.route_scenario_id,
        "allow_contracted_overflow": True, "allow_cost_based_outsourcing": True})
    while jobs.run_next():
        pass
    result = service.get_day(plan.plan_set_id, DATE_ONE, scenario.route_scenario_id).selected_result
    horizon = service.get_plan(plan.plan_set_id, scenario.route_scenario_id)
    summary = next(day for day in horizon.days if day.service_date == DATE_ONE)
    assert result.outsourced_by_cost_deliveries > 0
    assert summary.outsourced_by_cost_deliveries == result.outsourced_by_cost_deliveries
    assert summary.outsourcing_savings == result.outsourcing_savings
    assert horizon.outsourcing_savings == sum(day.outsourcing_savings for day in horizon.days)
    assert horizon.outsourced_by_cost_deliveries == sum(day.outsourced_by_cost_deliveries for day in horizon.days)
    assert result.kpis.total_revenue == baseline["kpis"]["total_revenue"]
    assert summary.total_cost == result.kpis.cost_breakdown.total_cost
    assert horizon.kpis.cost_breakdown.total_cost == pytest.approx(sum(day.total_cost or 0 for day in horizon.days))
    assert horizon.kpis.total_revenue == pytest.approx(sum(day.total_revenue or 0 for day in horizon.days))
    assert horizon.contracted_cost == pytest.approx(sum(day.contracted_cost or 0 for day in horizon.days))
    assert service.get_day(plan.plan_set_id, DATE_ONE).default_result.model_dump(mode="json") == baseline


def test_solve_matrix_prices_both_sides_and_avoids_empty_route_costs():
    from route_opt.matrix import build_travel_matrix

    solved, rows = fleet_input()
    depot = {**rows["dim_facilities"][0], "depot_id": "DPT"}
    _, matrix = build_travel_matrix("test", depot, rows["dim_network_customers"], DATE)
    for arc in matrix:
        arc["distance_miles"] *= 2
    solved["_cost_based_matrix"] = matrix
    original_cost = solved["kpis"]["cost_breakdown"]["total_cost"]
    run(solved, rows, [contract()])
    assert solved["execution"]["outsourcing_mileage_basis"] == "solve_matrix"
    assert solved["outsourced_by_cost_deliveries"] > 0
    assert all(quote["mileage_source"] == "solve_matrix" for quote in solved["contracted_quotes"])
    assert solved["fleet_cost"] == 0
    assert solved["kpis"]["cost_breakdown"]["total_cost"] <= original_cost


def test_removal_checks_windows_waiting_and_vehicle_duration():
    from backend.services.depot_carrier_choice import _rebuild

    solved, rows = fleet_input()
    route = solved["routes"][0]
    route["stops"][0].update(time_window_start="15:00", time_window_end="18:00")
    rebuilt = _rebuild(route, route["stops"][:1],
                       depot={**rows["dim_facilities"][0], "depot_id": "DPT"},
                       service_date=DATE, cost_parameters=CostParameters(), matrix={})
    assert rebuilt["waiting_minutes"] > 400
    assert rebuilt["route_minutes"] > 500
    assert rebuilt["stops"][0]["arrival_time"] == "15:00"
    original_routes = deepcopy(solved["routes"])
    run(solved, rows, [contract()], fleet=[{"vehicle_id": "V", "max_route_minutes": 30}])
    assert all(route == original_routes[index] or not route["stops"] or route["route_minutes"] <= 30
               for index, route in enumerate(solved["routes"]))


def test_capacity_allows_only_one_choice_stop():
    solved, rows = fleet_input()
    detail = contract()
    detail["capacity_commitments"] = [{"name": "Capacity", "rule_id": "CAP", "capacity_quantity": 1,
                                       "committed_quantity": 1, "current_utilization": 0,
                                       "unit": "stops", "period": "month"}]
    run(solved, rows, [detail])
    assert solved["outsourced_by_cost_deliveries"] == 1
    assert solved["routed_cases"] == 5
    assert solved["contracted_cases"] == 5
    remaining = solved["routes"][0]
    assert remaining["total_cases"] <= remaining["capacity_cases"]
    assert remaining["route_minutes"] <= 600
    assert remaining["missed_windows"] == 0
    for stop in remaining["stops"]:
        assert stop["time_window_start"] <= stop["arrival_time"] <= stop["time_window_end"]
    assert not {stop["customer_id"] for stop in remaining["stops"]} & {order["customer_id"] for order in solved["contracted_orders"]}


def test_nonmetric_matrix_shortcut_cannot_create_late_or_overlong_fleet_route():
    solved, rows = fleet_input()
    original_routes = deepcopy(solved["routes"])
    nodes = ["DPT:DEPOT", "C0", "C1"]
    solved["_cost_based_matrix"] = [
        {"origin_id": origin, "destination_id": destination,
         "distance_miles": 0 if origin == destination else 1,
         "duration_minutes": 800 if (origin, destination) == ("DPT:DEPOT", "C1") else
         0 if origin == destination else 1}
        for origin in nodes for destination in nodes]
    detail = contract()
    detail["capacity_commitments"] = [{"name": "Capacity", "rule_id": "CAP", "capacity_quantity": 1,
                                       "current_utilization": 0, "unit": "stops", "period": "month"}]
    run(solved, rows, [detail])
    assert solved["outsourced_by_cost_deliveries"] == 0
    assert solved["routes"] == original_routes


def test_api_rejects_choice_without_overflow_before_execution():
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as client:
        response = client.post("/api/depot-plans/any/days/2026-10-06/optimize", json={
            "route_scenario_id": "named", "allow_cost_based_outsourcing": True})
    assert response.status_code == 422
    assert "requires contracted overflow" in response.text
