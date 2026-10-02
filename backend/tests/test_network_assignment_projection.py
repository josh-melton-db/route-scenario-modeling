from copy import deepcopy

import pytest

from backend.services.network_assignment_projection import merge_assignment_overlays, projected_demand_rows


def _rows():
    return {
        'dim_facilities': [
            {'facility_id': 'A', 'facility_type': 'depot', 'region_id': 'R'},
            {'facility_id': 'B', 'facility_type': 'depot', 'region_id': 'R'},
        ],
        'demand_plan_daily': [{
            'demand_plan_version_id': 'D', 'service_date': '2026-09-30',
            'customer_id': 'C', 'depot_id': 'A', 'region_id': 'R', 'demand_units': 5,
        }],
        'network_customer_assignments_daily': [
            {'demand_plan_version_id': 'D', 'capacity_plan_version_id': 'P',
             'service_date': '2026-09-30', 'customer_id': 'C', 'depot_id': depot,
             'required_units': units, 'assigned_units': units, 'unmet_units': 0}
            for depot, units in [('A', 3), ('B', 2)]
        ],
    }


def test_projection_preserves_canonical_demand_and_alternate_capacity_context():
    rows = _rows()
    before = deepcopy(rows)
    assert [(row['depot_id'], row['demand_units']) for row in projected_demand_rows(rows, 'D', 'P')] == [('A', 3), ('B', 2)]
    assert projected_demand_rows(rows, 'D', 'OTHER') == rows['demand_plan_daily']
    assert rows == before


def test_projection_rejects_lost_required_cases():
    rows = _rows()
    rows['network_customer_assignments_daily'].pop()
    with pytest.raises(ValueError, match='required customer/date demand'):
        projected_demand_rows(rows, 'D', 'P')


def test_projection_preserves_explicit_unmet_responsibility():
    rows = _rows()
    rows['network_customer_assignments_daily'][1].update(assigned_units=0, unmet_units=2)
    assert sum(row['demand_units'] for row in projected_demand_rows(rows, 'D', 'P')) == 5


def test_partial_rerun_preserves_other_dates_and_capacity_variants():
    current = _rows()['network_customer_assignments_daily']
    other_date = [{**row, 'service_date': '2026-10-01'} for row in current]
    other_capacity = [{**row, 'capacity_plan_version_id': 'OTHER'} for row in current]
    replacement = [{**current[0], 'depot_id': 'B', 'required_units': 5, 'assigned_units': 5}]
    merged = merge_assignment_overlays(current + other_date + other_capacity, replacement)
    assert merged == other_date + other_capacity + replacement
    assert current == _rows()['network_customer_assignments_daily']


def test_legacy_aggregate_demand_is_preserved_without_matching_overlays():
    rows = _rows()
    del rows['demand_plan_daily'][0]['customer_id']
    before = deepcopy(rows)
    assert projected_demand_rows(rows, 'D', 'OTHER') == rows['demand_plan_daily']
    assert rows == before
    with pytest.raises(ValueError, match='requires customer-level demand'):
        projected_demand_rows(rows, 'D', 'P')
