from copy import deepcopy
import json

import pytest

from backend.depot_plan_models import OverrideRequest
from backend.services.depot_contracted_overflow import apply_contracted_overflow
from route_opt.cost import CostParameters
from route_opt.pricing import revenue_for_cases
from route_opt.rates import contract_detail_from_legacy


DATE = "2026-10-06"


def contract(**lane_changes):
    detail = contract_detail_from_legacy({
        "contract_id": "DELIVERY", "carrier_id": "CARRIER", "contract_name": "Delivery",
        "rate_per_stop": 10, "rate_per_mile": 0, "minimum_charge": 0,
        "fuel_surcharge_pct": 0, "capacity_stops": 100,
        "effective_start": "2026-01-01", "effective_end": "2026-12-31",
    }, "Carrier")
    detail["lane_rates"] = [{
        **detail["lane_rates"][0], "rule_id": "DELIVERY_LANE", "lane_type": "DELIVERY",
        "origin": "DPT", "origin_endpoint_id": "DPT", "origin_endpoint_type": "facility",
        "destination": "*", "destination_endpoint_id": "*", "destination_endpoint_type": "customer",
        "flat_rate": 0, "included_stops": 0,
        **lane_changes,
    }]
    detail["capacity_commitments"] = []
    detail["volume_tiers"] = []
    return detail


def inputs(count=1):
    orders = [{"customer_id": f"C{index}", "demand_cases": 5, "reason": "no_vehicle_available"} for index in range(count)]
    rows = {
        "dim_facilities": [{"facility_id": "DPT", "lat": 39, "lng": -86}],
        "dim_network_customers": [{"customer_id": row["customer_id"], "lat": 39.1, "lng": -86.1,
                                   "market_id": "MARKET", "receiving_window_start": "06:30",
                                   "receiving_window_end": "18:00", "service_minutes": 10} for row in orders],
    }
    solved = {"routes": [], "kpis": {"cost_breakdown": {"total_cost": 25}, "profit": -25},
              "assigned_cases": count * 5, "routed_cases": 0, "unserved_cases": count * 5,
              "unserved_orders": orders, "execution": {"solver": "unchanged"}}
    return solved, rows


def apply(solved, rows, details, enabled=True):
    apply_contracted_overflow(solved, network_rows=rows, depot_id="DPT", service_date=DATE,
                              cost_parameters=CostParameters(), contract_details=details, enabled=enabled)


def test_request_defaults_off_and_accepts_on():
    assert OverrideRequest(route_scenario_id="named").allow_contracted_overflow is False
    assert OverrideRequest(route_scenario_id="named", allow_contracted_overflow=True).allow_contracted_overflow is True


def test_prices_overflow_and_preserves_fleet_with_auditable_quote():
    solved, rows = inputs()
    fleet = deepcopy(solved["routes"])
    apply(solved, rows, [contract()])
    assert solved["routes"] == fleet
    assert solved["unserved_orders"] == []
    assert solved["unserved_cases"] == 0
    assert solved["routed_cases"] == 0
    assert solved["contracted_cases"] == 5
    assert solved["contracted_deliveries"] == 1
    assert solved["fleet_cost"] == 25
    assert solved["contracted_cost"] == 10
    assert solved["kpis"]["cost_breakdown"]["total_cost"] == 35
    assert solved["contracted_revenue"] == revenue_for_cases(5)
    assert solved["kpis"]["total_revenue"] == revenue_for_cases(5)
    assert solved["kpis"]["profit"] == -3.75
    assert solved["kpis"]["cost_breakdown"]["carrier_stop_cost"] == 10
    delivery = solved["contracted_orders"][0]
    assert delivery["contract_id"] == "DELIVERY"
    assert delivery["matched_lane_rule_id"] == "DELIVERY_LANE"
    assert delivery["charge_lines"]
    assert solved["execution"]["contract_versions"] == [{"contract_id": "DELIVERY", "version_id": "DELIVERY_V1"}]


@pytest.mark.parametrize("details", [[], [contract(lane_type="LINEHAUL")],
    [contract(origin="OTHER", origin_endpoint_id="OTHER")], [contract(destination="OTHER")]])
def test_inapplicable_contract_stays_unserved(details):
    solved, rows = inputs()
    apply(solved, rows, details)
    assert solved["unserved_orders"][0]["reason"] == "no_contract_rate"
    assert solved["unserved_cases"] == 5
    assert solved["contracted_cost"] == 0
    assert solved["contracted_revenue"] == 0
    assert solved["kpis"]["total_revenue"] == 0
    assert solved["kpis"]["profit"] == -25


def test_toggle_off_is_byte_identical_even_with_rates():
    solved, rows = inputs()
    before = json.dumps(solved, sort_keys=True)
    apply(solved, rows, [contract()], enabled=False)
    assert json.dumps(solved, sort_keys=True) == before


def test_classic_six_stop_quote_chunks_and_minimum_charge():
    solved, rows = inputs(7)
    apply(solved, rows, [contract(minimum_charge=100)])
    assert [quote["stops"] for quote in solved["contracted_quotes"]] == [6, 1]
    assert solved["contracted_cost"] == 200
    assert solved["contracted_cases"] == 35


def test_two_chunks_against_capacity_six_leaves_second_chunk_unserved():
    solved, rows = inputs(12)
    detail = contract()
    detail["capacity_commitments"] = [{
        "rule_id": "CAPACITY", "name": "Reserved stops", "unit": "stops",
        "committed_quantity": 0, "capacity_quantity": 6, "current_utilization": 0,
        "overage_rate": 50,
    }]
    apply(solved, rows, [detail])
    assert solved["contracted_deliveries"] == 6
    assert solved["contracted_cost"] == 360
    assert solved["unserved_cases"] == 30
    assert [order["customer_id"] for order in solved["unserved_orders"]] == [f"C{index}" for index in range(6, 12)]
    assert all(order["reason"] == "no_contract_rate" for order in solved["unserved_orders"])
    assert detail["capacity_commitments"][0]["current_utilization"] == 0


def test_exhausted_contract_uses_another_contract_with_running_utilization():
    solved, rows = inputs(12)
    first = contract()
    first["capacity_commitments"] = [{
        "rule_id": "CAPACITY", "name": "Reserved stops", "unit": "stops",
        "committed_quantity": 0, "capacity_quantity": 8, "current_utilization": 2,
        "overage_rate": 50,
    }]
    second = deepcopy(first)
    second["contract_id"] = "ALTERNATE"
    second["version"]["version_id"] = "ALTERNATE_V1"
    second["lane_rates"][0]["rate_per_stop"] = 20
    apply(solved, rows, [first, second])
    assert [quote["contract_id"] for quote in solved["contracted_quotes"]] == ["DELIVERY", "ALTERNATE"]
    assert solved["contracted_deliveries"] == 12
    assert solved["contracted_cost"] == 780
    assert solved["unserved_cases"] == 0


def test_missing_customer_stays_unserved_instead_of_crashing():
    solved, rows = inputs()
    rows["dim_network_customers"] = []
    apply(solved, rows, [contract()])
    assert solved["unserved_orders"] == [{"customer_id": "C0", "demand_cases": 5, "reason": "no_contract_rate"}]
    assert solved["contracted_deliveries"] == 0


def test_failed_quotes_return_each_original_order_once(monkeypatch):
    import backend.services.depot_contracted_overflow as overflow

    solved, rows = inputs(12)
    rows["dim_network_customers"] = rows["dim_network_customers"][:1]
    for index, order in enumerate(solved["unserved_orders"]):
        order.update(customer_id="C0", order_id=f"ORDER-{index}")
    original = deepcopy(solved["unserved_orders"])
    quote_contract = overflow.quote_contract

    def reject_final_quote(detail, request):
        quote = quote_contract(detail, request)
        if request["miles"] > 0:
            quote["eligible"] = False
        return quote

    monkeypatch.setattr(overflow, "quote_contract", reject_final_quote)
    apply(solved, rows, [contract()])
    assert solved["unserved_orders"] == [{**order, "reason": "no_contract_rate"} for order in original]
    assert solved["unserved_cases"] == solved["assigned_cases"]


def test_contracted_deliveries_keep_original_order_identity():
    solved, rows = inputs(2)
    rows["dim_network_customers"] = rows["dim_network_customers"][:1]
    for index, order in enumerate(solved["unserved_orders"]):
        order.update(customer_id="C0", order_id=f"ORDER-{index}")
    apply(solved, rows, [contract()])
    assert [order["order_id"] for order in solved["contracted_orders"]] == ["ORDER-0", "ORDER-1"]


@pytest.mark.parametrize("has_rate", [True, False])
def test_diagnostics_describe_final_overflow_result(has_rate):
    solved, rows = inputs()
    solved["diagnostics"] = [{"status": "infeasible", "message": "Fleet could not serve delivery",
                              "dropped_stop_count": 1, "unserved_cases": 5}]
    apply(solved, rows, [contract()] if has_rate else [])
    diagnostic = solved["diagnostics"][0]
    assert diagnostic["status"] == ("succeeded" if has_rate else "infeasible")
    assert diagnostic["dropped_stop_count"] == (0 if has_rate else 1)
    assert diagnostic["unserved_cases"] == solved["unserved_cases"]
    assert diagnostic["contracted_cases"] == solved["contracted_cases"]
    assert diagnostic["message"] == (
        f"Assigned {int(has_rate)} overflow stops using eligible carrier rate rules; "
        f"{int(not has_rate)} remain unserved."
    )


@pytest.mark.parametrize("change", [{"status": "draft"}, {"effective_end": "2026-01-01"}, {"effective_start": "2027-01-01"}])
def test_contract_must_be_published_and_effective(change):
    detail = contract()
    detail["version"].update(change)
    solved, rows = inputs()
    apply(solved, rows, [detail])
    assert solved["unserved_orders"][0]["reason"] == "no_contract_rate"


def test_service_persists_overflow_and_reconciles_day_result(monkeypatch):
    from types import SimpleNamespace
    import backend.services.depot_plans as plans
    from backend.tests.test_depot_plan_service import _service, DEPOT_ID, DATE_ONE

    service, repository, jobs, _, solve_inputs = _service()
    fleet_provider = service.fleet_provider
    service.fleet_provider = lambda snapshot, depot_id: (
        [{**vehicle, "available_dates": [DATE_ONE]} for vehicle in fleet_provider(snapshot, depot_id)[0]],
        "test_fixed_fleet",
    )
    detail = contract(origin=DEPOT_ID, origin_endpoint_id=DEPOT_ID)
    monkeypatch.setattr(plans, "get_store", lambda: object())
    monkeypatch.setattr(plans, "list_rate_contract_details", lambda store: [SimpleNamespace(model_dump=lambda **kwargs: detail)])
    plan = service.get_or_create_plan("RUN", DEPOT_ID)
    while jobs.run_next():
        pass
    baseline = service.get_day(plan.plan_set_id, DATE_ONE).default_result.model_dump()
    scenario = service.create_scenario(plan.plan_set_id, "Overflow")
    service.optimize_day(plan.plan_set_id, DATE_ONE, OverrideRequest(
        route_scenario_id=scenario.route_scenario_id, driver_delta=-1, allow_contracted_overflow=True,
    ))
    while jobs.run_next():
        pass
    day = service.get_day(plan.plan_set_id, DATE_ONE, scenario.route_scenario_id)
    assert day.error is None
    result = day.selected_result
    assert result.status == "completed"
    assert result.contracted_cases == 100
    assert result.routed_cases == 0
    assert result.unserved_cases == 0
    assert result.contracted_orders[0]["contract_id"] == "DELIVERY"
    assert result.execution["contract_versions"]
    summary = next(day for day in service.get_plan(plan.plan_set_id, scenario.route_scenario_id).days if day.service_date == DATE_ONE)
    assert summary.contracted_cases == 100
    assert summary.contracted_deliveries == 1
    assert result.contracted_revenue == revenue_for_cases(100)
    assert result.kpis.total_revenue == result.contracted_revenue
    assert result.kpis.profit == round(result.kpis.total_revenue - result.kpis.cost_breakdown.total_cost, 2)
    assert summary.contracted_revenue == result.contracted_revenue
    assert summary.contracted_cost == result.contracted_cost
    assert summary.total_revenue == result.kpis.total_revenue
    assert summary.profit == result.kpis.profit
    horizon = service.get_plan(plan.plan_set_id, scenario.route_scenario_id)
    assert horizon.kpis.total_revenue == sum(day.total_revenue or 0 for day in horizon.days)
    assert horizon.kpis.profit == round(horizon.kpis.total_revenue - horizon.kpis.cost_breakdown.total_cost, 2)
    assert horizon.contracted_revenue == sum(day.contracted_revenue or 0 for day in horizon.days)
    assert horizon.contracted_cost == sum(day.contracted_cost or 0 for day in horizon.days)
    assert summary.routed_cases + summary.contracted_cases + summary.unserved_cases == summary.assigned_cases
    assert "rate_contract_details" not in solve_inputs[-1]["network_rows"]
    assert service.get_day(plan.plan_set_id, DATE_ONE).default_result.model_dump() == baseline


def test_only_deliveries_with_matching_destination_leave_unserved():
    solved, rows = inputs(2)
    apply(solved, rows, [contract(destination="C0", destination_endpoint_id="C0")])
    assert [order["customer_id"] for order in solved["contracted_orders"]] == ["C0"]
    assert solved["unserved_orders"] == [{"customer_id": "C1", "demand_cases": 5, "reason": "no_contract_rate"}]
    assert solved["routed_cases"] + solved["contracted_cases"] + solved["unserved_cases"] == solved["assigned_cases"]
    assert solved["contracted_revenue"] == revenue_for_cases(5)
    assert solved["kpis"]["total_revenue"] == revenue_for_cases(5)
    assert solved["contracted_cost"] == 10


def test_contracted_revenue_adds_to_fleet_revenue_and_reconciles_profit():
    solved, rows = inputs(2)
    solved["kpis"].update(total_revenue=revenue_for_cases(10), profit=37.5)
    apply(solved, rows, [contract()])
    assert solved["contracted_revenue"] == revenue_for_cases(10)
    assert solved["kpis"]["total_revenue"] == 125
    assert solved["kpis"]["profit"] == 80
    assert solved["kpis"]["profit"] == solved["kpis"]["total_revenue"] - solved["kpis"]["cost_breakdown"]["total_cost"]


def test_market_scope_and_shared_quote_charge_lines_use_quote_engine():
    from route_opt.rates import quote_contract

    solved, rows = inputs(2)
    detail = contract(destination="MARKET", destination_endpoint_id="MARKET", destination_endpoint_type="market")
    apply(solved, rows, [detail])
    quote = solved["contracted_quotes"][0]
    expected = quote_contract(detail, {"service_date": DATE, "origin": "DPT", "destination": "MARKET",
                                       "miles": quote["miles"], "stops": 2, "cases": 10})
    assert quote["charge_lines"] == expected["charge_lines"]
    assert quote["total_cost"] == expected["total_cost"]
    assert len({order["quote_id"] for order in solved["contracted_orders"]}) == 1


def test_chooses_lowest_quote_after_mileage_and_inferred_accessorials():
    solved, rows = inputs()
    rows["dim_network_customers"][0]["special_handling"] = "liftgate inside delivery"
    expensive = contract(rate_per_mile=100)
    cheaper = deepcopy(expensive)
    cheaper["contract_id"] = "CHEAPER"
    cheaper["version"]["version_id"] = "CHEAPER_V1"
    cheaper["lane_rates"][0].update(rate_per_mile=0, flat_rate=20)
    apply(solved, rows, [expensive, cheaper])
    assert solved["contracted_orders"][0]["contract_id"] == "CHEAPER"
    categories = {line["category"] for line in solved["contracted_orders"][0]["charge_lines"]}
    assert "accessorial" in categories


@pytest.mark.parametrize("toggle", [None, False])
def test_service_off_does_not_read_rates_or_change_metrics_routes_unserved(monkeypatch, toggle):
    import backend.services.depot_plans as plans
    from backend.tests.test_depot_plan_service import _service, DEPOT_ID, DATE_ONE

    service, _, jobs, _, _ = _service()
    plan = service.get_or_create_plan("RUN", DEPOT_ID)
    monkeypatch.setattr(plans, "list_rate_contract_details", lambda store: pytest.fail("Off execution must not read rate books"))
    while jobs.run_next():
        pass
    baseline = service.get_day(plan.plan_set_id, DATE_ONE).default_result.model_dump(mode="json")
    service.solver = lambda **kwargs: deepcopy(baseline)
    scenario = service.create_scenario(plan.plan_set_id, "Off")
    request = {"route_scenario_id": scenario.route_scenario_id}
    if toggle is not None:
        request["allow_contracted_overflow"] = toggle
    service.optimize_day(plan.plan_set_id, DATE_ONE, request)
    while jobs.run_next():
        pass
    result = service.get_day(plan.plan_set_id, DATE_ONE, scenario.route_scenario_id).selected_result.model_dump(mode="json")
    for field in ("kpis", "routes", "unserved_orders", "unserved_cases", "routed_cases"):
        assert json.dumps(result[field], sort_keys=True) == json.dumps(baseline[field], sort_keys=True)
