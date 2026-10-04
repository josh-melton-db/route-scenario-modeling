from __future__ import annotations

from copy import deepcopy

import pytest

from backend.models import RateContractDetail
from backend.services import network_rating
from backend.services.network_rating import (
    linear_objective_cost, rate_network_flows, resolve_network_tariffs,
)
from route_opt.rates import contract_detail_from_legacy


def _rows() -> dict[str, list[dict[str, object]]]:
    return {
        "dim_facilities": [
            {"facility_id": "DC", "facility_type": "distribution_center", "region_id": "R", "country_code": "US"},
            {"facility_id": "DPT", "facility_type": "depot", "region_id": "R", "country_code": "CA"},
        ],
        "dim_network_lanes": [{
            "lane_id": "LANE", "lane_type": "LINEHAUL",
            "origin_endpoint_id": "DC", "destination_endpoint_id": "DPT",
            "distance_miles": 100,
        }],
    }


def test_identical_flows_have_zero_comparable_delta_despite_published_estimate() -> None:
    rows = _rows()
    rows["network_flow_cost_daily"] = [{"service_date": "2026-10-01", "lane_id": "LANE", "total_cost": 9999}]
    flows = [{"service_date": "2026-10-01", "lane_id": "LANE", "assigned_units": 901}]

    baseline = rate_network_flows(rows, flows, {}, contracts=[])
    scenario = rate_network_flows(deepcopy(rows), deepcopy(flows), {}, contracts=[])

    assert sum(r["total_cost"] for r in baseline.cost_rows) == sum(
        r["total_cost"] for r in scenario.cost_rows
    )
    assert baseline.charge_details[0].loads == 2
    assert baseline.charge_details[0].freight_total == 1008
    assert rows["network_flow_cost_daily"][0]["total_cost"] == 9999


def test_fallback_and_tariff_are_symmetric_and_zero_flow_is_zero() -> None:
    rows = _rows()
    tariffs = {("2026-10-01", "LANE"): (2.5, "TARIFF")}
    baseline = rate_network_flows(
        rows,
        [{"service_date": "2026-10-01", "lane_id": "LANE", "assigned_units": 1}],
        tariffs,
        contracts=[],
    )
    scenario = rate_network_flows(
        rows,
        [{"service_date": "2026-10-01", "lane_id": "LANE", "assigned_units": 1}],
        tariffs,
        contracts=[],
    )
    zero = rate_network_flows(
        rows,
        [{"service_date": "2026-10-01", "lane_id": "LANE", "assigned_units": 0}],
        tariffs,
        contracts=[],
    )

    assert baseline.cost_rows == scenario.cost_rows
    assert baseline.charge_details[0].tariff_total == 2.5
    assert baseline.charge_details[0].total_cost == 506.5
    assert baseline.charge_details[0].freight_total == sum(
        line.amount for line in baseline.charge_details[0].charge_lines
    )
    assert baseline.charge_details[0].total_cost == round(
        sum(line.amount for line in baseline.charge_details[0].charge_lines)
        + baseline.charge_details[0].tariff_total,
        2,
    )
    assert zero.cost_rows[0]["total_cost"] == 0
    assert zero.charge_details == []


def test_partial_loads_use_whole_load_contract_basis_and_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = RateContractDetail.model_validate(contract_detail_from_legacy(
        {
            "contract_id": "CONTRACT",
            "carrier_id": "CARRIER",
            "contract_name": "Contract",
            "capacity_stops": 100,
            "rate_per_mile": 1.237,
            "rate_per_stop": 0,
            "minimum_charge": 100,
            "fuel_surcharge_pct": 7.25,
            "effective_start": "2026-01-01",
            "effective_end": "2026-12-31",
        },
        "Carrier",
        freshness_at="2026-01-01T00:00:00+00:00",
    ))
    monkeypatch.setattr(
        network_rating, "governed_linehaul_contract", lambda _region: ("CONTRACT", "V1")
    )

    def charge(cases: int):
        result = rate_network_flows(
            _rows(),
            [{"service_date": "2026-10-01", "lane_id": "LANE", "assigned_units": cases}],
            {("2026-10-01", "LANE"): (0.13, "TARIFF")},
            contracts=[contract],
        )
        return result.charge_details[0]

    one_case = charge(1)
    full_load = charge(900)
    partial_second_load = charge(901)

    assert one_case.loads == full_load.loads == 1
    assert one_case.freight_total == full_load.freight_total
    assert partial_second_load.loads == 2
    assert partial_second_load.freight_total == round(full_load.freight_total * 2, 2)
    for detail in (one_case, full_load, partial_second_load):
        assert detail.freight_total == round(
            sum(line.amount for line in detail.charge_lines), 2
        )
        assert detail.total_cost == round(
            detail.freight_total + detail.tariff_total, 2
        )


def test_partial_load_billed_cost_discloses_linear_objective_gap() -> None:
    flows = [{
        "service_date": "2026-10-01", "lane_id": "LANE",
        "lane_type": "LINEHAUL", "assigned_units": 901,
    }]
    rated = rate_network_flows(_rows(), flows, {}, contracts=[])
    objective = linear_objective_cost(
        flows, {("2026-10-01", "LANE"): 504 / 900}, {}
    )

    assert objective == 504.56
    assert rated.charge_details[0].total_cost == 1008
    assert rated.charge_details[0].total_cost - objective == 503.44


def test_tariff_date_boundaries_are_inclusive() -> None:
    from backend.models import NetworkTariffRule

    resolved = resolve_network_tariffs(
        _rows(),
        [NetworkTariffRule(
            rule_id="BOUNDARY", origin_country="US", destination_country="CA",
            effective_start="2026-10-02", effective_end="2026-10-03",
            amount_per_case=1.25,
        )],
        "2026-10-01", "2026-10-04",
    )

    assert set(resolved) == {("2026-10-02", "LANE"), ("2026-10-03", "LANE")}
