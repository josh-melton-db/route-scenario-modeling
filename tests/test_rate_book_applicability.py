"""Tests for rate-book contract applicability scoping.

Legacy contracts inherit MARKET lanes hardcoded to DPT_NORTH.  These must not
leak into ``applicable_depot_ids`` so that non-DPT_NORTH depots (e.g. San
Antonio) can still see and select published carrier contracts.
"""

from __future__ import annotations

from route_opt.rates import contract_detail_from_legacy, contract_summary
from backend.services.rates import (
    CANONICAL_RATE_CONTRACTS,
    canonical_rate_contract_details,
)
from route_opt.demo_dates import demo_date_anchor


def _summary(contract_row: dict) -> dict:
    detail = contract_detail_from_legacy(dict(contract_row), str(contract_row["carrier_name"]))
    return contract_summary(detail, demo_date_anchor().isoformat())


def test_legacy_market_lane_does_not_scope_contract_to_dpt_north() -> None:
    """Every canonical legacy contract must have empty applicable_depot_ids.

    Legacy contracts only carry MARKET and LAST_MILE lane types -- neither is a
    DELIVERY lane -- so they should not be scoped to any single depot.
    """
    for row in CANONICAL_RATE_CONTRACTS:
        summary = _summary(dict(row))
        assert summary["applicable_depot_ids"] == [], (
            f'{row["contract_id"]} was scoped to {summary["applicable_depot_ids"]} '
            "but has no DELIVERY lane rules"
        )


def test_applicable_region_ids_is_always_present() -> None:
    """The summary dict must include applicable_region_ids so the frontend
    can read it without a KeyError."""
    for row in CANONICAL_RATE_CONTRACTS:
        summary = _summary(dict(row))
        assert "applicable_region_ids" in summary
        assert summary["applicable_region_ids"] == []


def test_curated_linehaul_lanes_do_not_pollute_depot_scope() -> None:
    """The MX contract gets curated LINEHAUL lane rules appended.  LINEHAUL
    origins are distribution centers, not delivery depots, so they must not
    appear in applicable_depot_ids."""
    details = canonical_rate_contract_details()
    mx = next(d for d in details if d.contract_id == "MX_STANDARD_2026")
    summary = contract_summary(mx.model_dump(mode="json"), demo_date_anchor().isoformat())
    assert "DPT_TOLA_SAN_ANTONIO" not in summary["applicable_depot_ids"]
    assert "DC_MEXICO_MONTERREY" not in summary["applicable_depot_ids"]
    assert summary["applicable_depot_ids"] == []


def test_delivery_lane_origin_populates_depot_scope() -> None:
    """When a contract does have a DELIVERY lane rule with a facility origin,
    that origin should appear in applicable_depot_ids."""
    base = dict(CANONICAL_RATE_CONTRACTS[0])
    detail = contract_detail_from_legacy(base, str(base["carrier_name"]))
    detail["lane_rates"].append(
        {
            "rule_id": "TEST_DELIVERY_LANE",
            "lane_name": "Test delivery",
            "origin": "DPT_TEST",
            "destination": "MKT_TEST",
            "lane_type": "DELIVERY",
            "origin_endpoint_id": "DPT_TEST",
            "origin_endpoint_type": "facility",
            "destination_endpoint_id": "MKT_TEST",
            "destination_endpoint_type": "market",
            "priority": 100,
            "flat_rate": 50,
            "rate_per_mile": 0,
            "rate_per_stop": 0,
            "included_stops": 1,
            "minimum_charge": 0,
            "mileage_rounding": "exact",
        }
    )
    summary = contract_summary(detail, demo_date_anchor().isoformat())
    assert summary["applicable_depot_ids"] == ["DPT_TEST"]
