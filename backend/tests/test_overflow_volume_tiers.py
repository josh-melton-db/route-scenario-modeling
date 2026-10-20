from copy import deepcopy

import pytest

from backend.depot_plan_models import OverrideRequest
from backend.services.depot_contracted_overflow import apply_contracted_overflow
from backend.tests.test_depot_contracted_overflow import DATE, contract, inputs
from route_opt.cost import CostParameters
from route_opt.rates import quote_contract


def tiered(unit="stops", **lane):
    detail = contract(**lane)
    detail["volume_tiers"] = [
        {"rule_id": "BASE", "name": "Base", "unit": unit, "period": "month",
         "min_volume": 0, "max_volume": 49, "discount_pct": 0},
        {"rule_id": "MID", "name": "Middle", "unit": unit, "period": "month",
         "min_volume": 50, "max_volume": 99, "discount_pct": 10},
        {"rule_id": "TOP", "name": "Top", "unit": unit, "period": "month",
         "min_volume": 100, "max_volume": None, "discount_pct": 20},
    ]
    return detail


def run_overflow(detail, count=6, projected=None, enabled=True):
    solved, rows = inputs(count)
    apply_contracted_overflow(
        solved, network_rows=rows, depot_id="DPT", service_date=DATE,
        cost_parameters=CostParameters(), contract_details=[detail], enabled=enabled,
        projected_period_volume=projected,
    )
    return solved


@pytest.mark.parametrize("projected,expected,units", [
    (None, 60, [6]), (0, 60, [6]), (48, 56, [2, 4]), (120, 48, [6]),
    (49.5, 54.5, [.5, 5.5]),
])
def test_graduated_bands_and_reconciliation(projected, expected, units):
    solved = run_overflow(tiered(), projected=projected)
    assert solved["contracted_cost"] == expected
    quote = solved["contracted_quotes"][0]
    breakdown = quote["tier_breakdown"]
    assert breakdown["projected_period_volume"] == (projected or 0)
    assert breakdown["unit"] == "stops"
    assert [band["units"] for band in breakdown["bands"]] == units
    assert sum(band["discount_amount"] for band in breakdown["bands"]) == pytest.approx(60 - expected)
    assert all("discount_pct" in band for band in breakdown["bands"])
    assert solved["kpis"]["cost_breakdown"]["total_cost"] == 25 + expected
    assert solved["kpis"]["total_revenue"] == 187.5
    assert solved["kpis"]["profit"] == 187.5 - 25 - expected


def test_chunks_consume_contract_ladder_in_assignment_order():
    solved = run_overflow(tiered(), count=12, projected=48)
    assert [quote["total_cost"] for quote in solved["contracted_quotes"]] == [56, 54]
    assert [quote["tier_breakdown"]["starting_volume"] for quote in solved["contracted_quotes"]] == [48, 54]


def test_cases_use_cases_not_stops():
    solved = run_overflow(tiered("cases"), count=2, projected=45)
    assert solved["contracted_cost"] == 19
    line = next(line for line in solved["contracted_quotes"][0]["charge_lines"] if line["category"] == "volume_tier")
    assert line["quantity"] == 10
    assert line["unit"] == "cases"
    assert [band["units"] for band in solved["contracted_quotes"][0]["tier_breakdown"]["bands"]] == [5, 5]


@pytest.mark.parametrize("unit", ["routes", "miles"])
def test_unsupported_units_are_undiscounted_with_reason(unit):
    solved = run_overflow(tiered(unit), projected=120)
    assert solved["contracted_cost"] == 60
    assert unit in solved["contracted_quotes"][0]["tier_breakdown"]["reason"]


@pytest.mark.parametrize("basis,expected", [("transportation_subtotal", 55), ("linehaul_and_minimum", 50.2), ("linehaul", 50)])
def test_minimum_after_discount_and_existing_fuel_rules(basis, expected):
    detail = tiered(minimum_charge=50)
    detail["fuel_surcharges"][0].update(basis=basis, rate_pct=10)
    solved = run_overflow(detail, projected=120)
    assert solved["contracted_cost"] == expected
    assert next(line["amount"] for line in solved["contracted_quotes"][0]["charge_lines"] if line["category"] == "minimum") == 2


def test_classic_quote_keeps_whole_volume_discount_and_does_not_mutate_book():
    from route_opt.rates import quote_graduated_contract

    detail = tiered()
    original = deepcopy(detail)
    request = {"service_date": DATE, "origin": "DPT", "destination": "C0", "stops": 6, "period_volume": 52}
    assert quote_contract(detail, request)["total_cost"] == 54
    assert quote_graduated_contract(detail, request, projected_period_volume=48)["total_cost"] == 56
    assert quote_contract(detail, request)["total_cost"] == 54
    assert detail == original


def test_off_is_unchanged_even_with_projected_volume():
    solved, _ = inputs(6)
    assert run_overflow(tiered(), projected=120, enabled=False) == solved


def test_projected_volume_request_is_optional_finite_and_nonnegative():
    assert OverrideRequest(route_scenario_id="named").projected_period_volume is None
    assert OverrideRequest(route_scenario_id="named", projected_period_volume=40).projected_period_volume == 40
    for invalid in [-1, float("inf"), float("nan")]:
        with pytest.raises(ValueError):
            OverrideRequest(route_scenario_id="named", projected_period_volume=invalid)


def test_frozen_tiers_and_projected_request_survive_execution(monkeypatch):
    from backend.models import RateContractDetail
    from backend.tests.test_depot_plan_service import _service, DEPOT_ID, DATE_ONE

    live = tiered(origin=DEPOT_ID, origin_endpoint_id=DEPOT_ID)
    monkeypatch.setattr("backend.services.depot_plans.list_rate_contract_details",
                        lambda store: [RateContractDetail.model_validate(live)])
    service, repository, jobs, _, _ = _service()
    plan = service.get_or_create_plan("TIER-RUN", DEPOT_ID)
    while jobs.run_next():
        pass
    live["volume_tiers"][-1]["discount_pct"] = 90
    scenario = service.create_scenario(plan.plan_set_id, "Projected")
    service.optimize_day(plan.plan_set_id, DATE_ONE, {
        "route_scenario_id": scenario.route_scenario_id, "driver_delta": -1,
        "allow_contracted_overflow": True, "projected_period_volume": 120,
    })
    while jobs.run_next():
        pass
    result = service.get_day(plan.plan_set_id, DATE_ONE, scenario.route_scenario_id).selected_result
    assert result.contracted_cost == 8
    assert result.contracted_quotes[0]["tier_breakdown"]["projected_period_volume"] == 120
    assert result.execution["contract_snapshots"][0]["volume_tiers"][-1]["discount_pct"] == 20
