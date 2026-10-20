from copy import deepcopy

import pytest

from backend.services.network_rating import rate_network_flows
from backend.services.rates import canonical_rate_contract_details
from route_opt.network_synthetic import national_dataset_cached
from route_opt.rates import quote_contract


@pytest.fixture
def delivery():
    rows = deepcopy(national_dataset_cached())
    lane = next(row for row in rows['dim_network_lanes'] if row['lane_type'] == 'DELIVERY'
                and row['origin_endpoint_id'] == 'DPT_TOLA_SAN_ANTONIO')
    flow = next(row for row in rows['baseline_network_flow_daily']
                if row['lane_id'] == lane['lane_id'] and row['assigned_units'] > 0)
    return rows, lane, flow, canonical_rate_contract_details()


def test_off_is_identical(delivery):
    rows, _, flow, contracts = delivery
    assert rate_network_flows(rows, [flow], {}, contracts=contracts) == rate_network_flows(
        rows, [flow], {}, contracts=contracts, use_delivery_contract_rates=False)


@pytest.mark.parametrize('assigned_units', [None, 1, 17, 901])
def test_cheapest_seed_quote_and_reconciled_ledger(delivery, assigned_units):
    rows, lane, flow, contracts = delivery
    if assigned_units is not None:
        flow['assigned_units'] = assigned_units
    result = rate_network_flows(rows, [flow], {}, contracts=contracts, use_delivery_contract_rates=True)
    detail = result.charge_details[0]
    assert detail.rate_source == 'delivery_contract'
    assumptions = detail.synthetic_route_assumptions
    assert assumptions['stops'] == 6
    assert assumptions['miles'] == 40
    assert assumptions['cases_per_stop_source'] == 'lane_demand'
    lane_demand = next(row['demand_units'] for row in rows['demand_plan_daily']
                       if row['customer_id'] == lane['destination_endpoint_id']
                       and str(row['service_date']) == str(flow['service_date'])
                       and row['demand_plan_version_id'] == flow['demand_plan_version_id'])
    assert assumptions['cases'] == 6 * lane_demand
    quotes = [(contract, quote_contract(contract.model_dump(mode='json'), {
        'service_date': str(flow['service_date']), 'origin': lane['origin_endpoint_id'],
        'destination': assumptions['destination'], 'stops': 6, 'miles': 40,
        'cases': assumptions['cases'], 'period_volume': 1, 'commitment_policy': 'honor',
    })) for contract in contracts if any(rule.lane_type == 'DELIVERY' for rule in contract.lane_rates)]
    applicable = [(contract, quote) for contract, quote in quotes if quote['matched_lane_rule_id']]
    assert len(applicable) == 2
    cheapest, quote = min(applicable, key=lambda item: item[1]['total_cost'])
    assert detail.contract_id == cheapest.contract_id
    assert detail.matched_lane_rule_id == quote['matched_lane_rule_id']
    assert detail.cost_per_case == quote['total_cost'] / assumptions['cases']
    assert abs(detail.freight_total - flow['assigned_units'] * detail.cost_per_case) <= 0.01
    assert detail.total_cost == result.cost_rows[0]['total_cost']
    assert detail.freight_total == round(sum(line.amount for line in detail.charge_lines), 2)


def test_missing_contract_is_distinct_fallback(delivery):
    rows, _, flow, _ = delivery
    result = rate_network_flows(rows, [flow], {}, contracts=[], use_delivery_contract_rates=True)
    original = rate_network_flows(rows, [flow], {}, contracts=[])
    assert result.cost_rows[0]['total_cost'] == original.cost_rows[0]['total_cost']
    assert result.charge_details[0].rate_source == 'delivery_planning_fallback'
    assert result.missing_rate_lane_ids == (flow['lane_id'],)


def test_depot_average_fallback(delivery):
    rows, lane, flow, contracts = delivery
    rows['demand_plan_daily'] = [row for row in rows['demand_plan_daily']
                                 if row['customer_id'] != lane['destination_endpoint_id']]
    detail = rate_network_flows(rows, [flow], {}, contracts=contracts,
                               use_delivery_contract_rates=True).charge_details[0]
    assert detail.synthetic_route_assumptions['cases_per_stop_source'] == 'depot_average'
    quantities = [row['demand_units'] for row in rows['demand_plan_daily']
                  if row['depot_id'] == lane['origin_endpoint_id']
                  and str(row['service_date']) == str(flow['service_date'])
                  and row['demand_plan_version_id'] == flow['demand_plan_version_id']]
    assert detail.synthetic_route_assumptions['cases'] == round(6 * sum(quantities) / len(quantities))


def test_no_demand_does_not_invent_cases(delivery):
    rows, _, flow, contracts = delivery
    rows['demand_plan_daily'] = []
    detail = rate_network_flows(rows, [flow], {}, contracts=contracts,
                               use_delivery_contract_rates=True).charge_details[0]
    assert detail.rate_source == 'delivery_planning_fallback'


@pytest.mark.parametrize('status', ['expired', 'draft'])
def test_only_published_dated_delivery_contracts_apply(delivery, status):
    rows, _, flow, contracts = delivery
    for contract in contracts:
        contract.version.status = 'draft' if status == 'draft' else 'published'
        if status == 'expired':
            contract.version.effective_end = '2020-01-01'
    detail = rate_network_flows(rows, [flow], {}, contracts=contracts,
                               use_delivery_contract_rates=True).charge_details[0]
    assert detail.rate_source == 'delivery_planning_fallback'
