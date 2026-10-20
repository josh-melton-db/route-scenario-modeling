from copy import deepcopy
from datetime import date, timedelta
import json

import pytest

from backend.services.depot_contracted_overflow import apply_contracted_overflow
from backend.services.network_rating import rate_network_flows
from backend.services.rates import canonical_rate_contract_details
from backend.services.stub_store import StubStore
from route_opt.cost import CostParameters
from route_opt.depot_planning import solve_depot_plan
from route_opt.network_synthetic import national_dataset_cached
from route_opt.rates import contract_status, quote_contract
from route_opt.overrides import seed_scenario_definitions


DEPOT = "DPT_TOLA_SAN_ANTONIO"


@pytest.fixture
def demo(monkeypatch):
    from route_opt import demo_dates

    monkeypatch.setenv("DEMO_DATE_ANCHOR", "2026-10-06")
    demo_dates.demo_date_anchor.cache_clear()
    yield national_dataset_cached(), canonical_rate_contract_details()
    demo_dates.demo_date_anchor.cache_clear()


def test_every_demo_depot_has_two_dated_delivery_carriers(demo):
    rows, details = demo
    depots = [row["facility_id"] for row in rows["dim_facilities"] if row["facility_type"].lower() == "depot"]
    assert DEPOT in depots
    legacy = {row.contract_id: row for row in StubStore().list_carrier_contracts()}
    for depot in depots:
        eligible = [detail for detail in details if any(
            lane.lane_type == "DELIVERY" and lane.origin == depot for lane in detail.lane_rates
        )]
        assert len({detail.carrier_id for detail in eligible}) == 2
        for detail in eligible:
            assert detail.capacity_commitments[0].capacity_quantity == legacy[detail.contract_id].capacity_stops
            assert detail.capacity_commitments[0].current_utilization == 0
            assert all(lane.destination != "*" for lane in detail.lane_rates)
        for offset in range(28):
            service_date = (date(2026, 10, 6) + timedelta(days=offset)).isoformat()
            assert all(contract_status(detail.model_dump(mode="json"), service_date) == "published" for detail in eligible)
        quotes = [quote_contract(detail.model_dump(mode="json"), {
            "service_date": "2026-10-06", "origin": depot,
            "destination": next(lane.destination for lane in detail.lane_rates if lane.origin == depot),
            "miles": 50, "stops": 6, "cases": 600,
        }) for detail in eligible]
        assert all(quote["eligible"] for quote in quotes)
        assert len({quote["total_cost"] for quote in quotes}) == 2
        marginal = 50 * CostParameters().cost_per_mile + 3 * CostParameters().labor_regular_hour
        assert all(quote["total_cost"] > marginal for quote in quotes)


def test_san_antonio_no_fleet_overflow_is_priced_and_capacity_limited(demo):
    rows, details = demo
    flows = rows["baseline_network_flow_daily"]
    solved = solve_depot_plan(rows, flows, DEPOT, "2026-10-06", [])
    before = deepcopy(solved)
    assert before["unserved_orders"]
    apply_contracted_overflow(before, network_rows=rows, depot_id=DEPOT,
        service_date="2026-10-06", cost_parameters=CostParameters(),
        contract_details=[detail.model_dump(mode="json") for detail in details
            if not detail.contract_id.startswith("DEMO_DELIVERY_")], enabled=True)
    assert before["contracted_cost"] == 0
    assert {row["reason"] for row in before["unserved_orders"]} == {"no_contract_rate"}
    apply_contracted_overflow(solved, network_rows=rows, depot_id=DEPOT,
        service_date="2026-10-06", cost_parameters=CostParameters(),
        contract_details=[detail.model_dump(mode="json") for detail in details], enabled=True)
    assert solved["contracted_cost"] > 0
    assert solved["contracted_deliveries"] == 18
    assert solved["unserved_orders"]
    assert {row["reason"] for row in solved["unserved_orders"]} == {"no_contract_rate"}
    assert [quote["contract_id"] for quote in solved["contracted_quotes"]] == [
        "DEMO_DELIVERY_STANDARD_2026", "DEMO_DELIVERY_RESERVE_2026", "DEMO_DELIVERY_RESERVE_2026",
    ]
    assert solved["contracted_cases"] + solved["unserved_cases"] == before["assigned_cases"]
    print("SAN_ANTONIO_OVERFLOW", json.dumps({
        "before": {"contracted_cost": 0, "contracted_deliveries": 0, "unserved_cases": before["unserved_cases"], "unserved_deliveries": len(before["unserved_orders"])},
        "after": {"contracted_cost": solved["contracted_cost"], "contracted_deliveries": solved["contracted_deliveries"], "unserved_cases": solved["unserved_cases"], "unserved_deliveries": len(solved["unserved_orders"])},
    }))


@pytest.mark.parametrize("projected", [0, 40, 120])
def test_san_antonio_graduated_tier_before_after(demo, projected):
    rows, details = demo
    frozen = [detail.model_dump(mode="json") for detail in details]
    solved = solve_depot_plan(rows, rows["baseline_network_flow_daily"], DEPOT, "2026-10-06", [])
    before = deepcopy(solved)
    for result, volume in [(before, 0), (solved, projected)]:
        apply_contracted_overflow(result, network_rows=rows, depot_id=DEPOT,
            service_date="2026-10-06", cost_parameters=CostParameters(),
            contract_details=frozen, enabled=True, projected_period_volume=volume)
    assert solved["contracted_deliveries"] == before["contracted_deliveries"] == 18
    assert solved["contracted_revenue"] == before["contracted_revenue"]
    assert solved["contracted_cost"] <= before["contracted_cost"]
    for quote in before["contracted_quotes"]:
        detail = next(detail for detail in frozen if detail["contract_id"] == quote["contract_id"])
        old = quote_contract(detail, {"service_date": "2026-10-06", "origin": DEPOT,
            "destination": quote["destination"], "miles": quote["miles"], "stops": quote["stops"],
            "cases": quote["cases"], "period_volume": 0, "commitment_policy": "honor"})
        assert old["total_cost"] == quote["total_cost"]
    print("SAN_ANTONIO_TIERS", json.dumps({"projected": projected,
        "before_cost": before["contracted_cost"], "after_cost": solved["contracted_cost"],
        "tier_discount": -solved["kpis"]["cost_breakdown"]["volume_tier_adjustment"],
        "contracted_deliveries": solved["contracted_deliveries"],
        "contracted_revenue": solved["contracted_revenue"], "unserved_cases": solved["unserved_cases"],
        "quotes": [{"contract": quote["contract_id"], "cost": quote["total_cost"],
                    "tier_breakdown": quote["tier_breakdown"]} for quote in solved["contracted_quotes"]]}))


def test_delivery_contracts_do_not_change_network_ratings_when_option_off(demo):
    rows, details = demo
    flows = rows["baseline_network_flow_daily"]
    original = [detail for detail in details if not any(lane.lane_type == "DELIVERY" for lane in detail.lane_rates)]
    assert rate_network_flows(rows, flows, {}, contracts=details, use_delivery_contract_rates=False) == rate_network_flows(rows, flows, {}, contracts=original)


def test_stub_uses_same_delivery_books_as_seed(demo):
    _, details = demo
    expected = {detail.contract_id: detail.model_dump(exclude={"freshness_at"}) for detail in details}
    actual = {detail.contract_id: detail.model_dump(exclude={"freshness_at"}) for detail in StubStore().list_rate_contract_details()}
    assert actual == expected
    assert any(any(lane.lane_type == "DELIVERY" for lane in detail.lane_rates) for detail in details)


def test_delivery_dates_cover_anchor_horizon_across_year_boundary(monkeypatch):
    from backend.services import rates

    monkeypatch.setattr(rates, "demo_date_anchor", lambda: date(2027, 12, 20))
    details = [detail for detail in canonical_rate_contract_details() if detail.contract_id.startswith("DEMO_DELIVERY_")]
    assert len(details) == 2
    for offset in range(28):
        service_date = (date(2027, 12, 20) + timedelta(days=offset)).isoformat()
        assert all(contract_status(detail.model_dump(mode="json"), service_date) == "published" for detail in details)


@pytest.mark.parametrize("scenario", seed_scenario_definitions(), ids=lambda row: row["scenario_id"])
def test_classic_demo_scenario_impact(demo, scenario):
    from backend.services.rates import CANONICAL_RATE_CONTRACTS
    from route_opt.baseline import summarize_kpis
    from route_opt.overrides import apply_overrides, seed_override_tables, resolve_cost_override
    from route_opt.solver import solve_scenario_partition
    from route_opt.synthetic import generate_all
    from route_opt.transportation import add_carrier_fallback, resolve_transportation_choices

    _, details = demo
    data = generate_all(seed=42, customer_count=250)
    overrides = seed_override_tables(data["location_data"])
    planning = apply_overrides(scenario=scenario, customers=data["location_data"],
        depots=data["depot_master"], fleet=data["fleet_assets"],
        orders=data["fact_delivery_orders"], override_tables=overrides)
    params = CostParameters().merged(resolve_cost_override(overrides, scenario["scenario_id"]))
    solution = solve_scenario_partition(scenario_id=scenario["scenario_id"],
        depot_id=scenario["depot_id"], delivery_day=scenario["delivery_day"],
        planning_depots=planning["scenario_planning_depots"],
        planning_customers=planning["scenario_planning_customers"],
        planning_fleet=planning["scenario_planning_fleet"],
        planning_stops=planning["scenario_planning_stops"], params=params)
    measured = []
    for include_delivery in (False, True):
        contracts = [dict(row) for row in CANONICAL_RATE_CONTRACTS
            if include_delivery or not str(row["contract_id"]).startswith("DEMO_DELIVERY_")]
        carriers = [{"carrier_id": row["carrier_id"], "carrier_name": row["carrier_name"]} for row in contracts]
        choices = resolve_transportation_choices({"transportation_choices": {
            "allow_carrier": True, "contract_selection": "automatic"},
            "pricing_context": {"service_date": "2026-10-06"}}, carriers, contracts,
            [detail.model_dump(mode="json") for detail in details if include_delivery or not detail.contract_id.startswith("DEMO_DELIVERY_")])
        rated = deepcopy(solution)
        add_carrier_fallback(solution=rated, scenario_id=scenario["scenario_id"],
            depot=planning["scenario_planning_depots"][0],
            customers=planning["scenario_planning_customers"],
            planning_stops=planning["scenario_planning_stops"], delivery_day=scenario["delivery_day"],
            parameters={"transportation_choices": choices}, cost_parameters=params)
        measured.append({"total_cost": summarize_kpis(rated["routes"])["cost_breakdown"]["total_cost"],
            "carrier_stops": sum(route["stop_count"] for route in rated["routes"] if route.get("fulfillment_method") == "carrier"),
            "unassigned_stops": len(rated["unassigned_stops"])})
    print("CLASSIC_IMPACT", scenario["scenario_id"], json.dumps({"before": measured[0], "after": measured[1]}))
    assert measured[1]["unassigned_stops"] <= measured[0]["unassigned_stops"]
