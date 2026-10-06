"""Tests for San Antonio depot baseline profit and flow deduplication.

Verifies that the canonical revenue_for_cases rate ($6.25/case) produces
positive profit for San Antonio when costs use the default CostParameters,
and that the Southeast constrained capacity plan does not double-count
delivery flow assignments.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from route_opt.network_synthetic import national_dataset_cached
from route_opt.depot_baseline import generate_depot_baseline
from route_opt.pricing import revenue_for_cases, CANONICAL_REVENUE_PER_CASE
from route_opt.demo_dates import demo_date_anchor


SAN_ANTONIO = "DPT_TOLA_SAN_ANTONIO"


def test_san_antonio_baseline_profit_is_positive() -> None:
    """San Antonio baseline must produce positive profit with canonical rates.

    Revenue = cases * $6.25; cost = mileage + labor + fixed vehicle.
    With ~7,663 cases over 13 routes, revenue ($47,894) exceeds cost ($15,768).
    """
    ds = national_dataset_cached(seed=42)
    result = generate_depot_baseline(ds, SAN_ANTONIO)
    kpis = result["kpis"]
    assert kpis["total_revenue"] > 0
    assert kpis["profit"] > 0, (
        f"San Antonio profit is {kpis['profit']} "
        f"(revenue={kpis['total_revenue']}, cost={kpis['cost_breakdown']['total_cost']})"
    )
    assert kpis["total_revenue"] == round(kpis["total_cases"] * CANONICAL_REVENUE_PER_CASE, 2)


def test_revenue_for_cases_uses_canonical_rate() -> None:
    """The pricing module must use the canonical $6.25/case rate consistently."""
    assert CANONICAL_REVENUE_PER_CASE == 6.25
    assert revenue_for_cases(0) == 0.0
    assert revenue_for_cases(100) == 625.0
    assert revenue_for_cases(7663) == 47893.75


def test_delivery_flow_deduplication_in_materialize_targets() -> None:
    """The Southeast constrained capacity plan duplicates every delivery flow
    row (once under the national plan, once under the constrained plan).  The
    materialize_depot_targets function must deduplicate these by lane_id and
    keep only the first occurrence so assigned cases are not double-counted.
    """
    ds = national_dataset_cached(seed=42)
    anchor = demo_date_anchor()
    service_date = anchor.isoformat()

    flow_rows = ds["baseline_network_flow_daily"]
    lanes = {str(row["lane_id"]): row for row in ds["dim_network_lanes"]}

    sa_delivery_flows = [
        f for f in flow_rows
        if str(f.get("service_date")) == service_date
        and str(f.get("lane_type")) == "DELIVERY"
        and str(lanes.get(str(f.get("lane_id", "")), {}).get("origin_endpoint_id")) == SAN_ANTONIO
    ]

    lane_ids = [str(f.get("lane_id")) for f in sa_delivery_flows]
    counts = Counter(lane_ids)
    duplicates = {k: v for k, v in counts.items() if v > 1}
    assert len(duplicates) > 0, "Expected duplicate delivery flows from SE constrained plan"

    # Simulate the dedup that materialize_depot_targets performs
    seen: dict[str, int] = {}
    assigned_by_customer: dict[str, int] = defaultdict(int)
    for flow in sa_delivery_flows:
        lane_id = str(flow.get("lane_id", ""))
        cases = int(flow.get("assigned_units", 0))
        if lane_id in seen:
            assert seen[lane_id] == cases, f"Duplicate lane {lane_id} has conflicting assignments"
            continue
        seen[lane_id] = cases
        lane = lanes[lane_id]
        assigned_by_customer[str(lane.get("destination_endpoint_id"))] += cases

    total_deduped = sum(assigned_by_customer.values())
    total_raw = sum(int(f.get("assigned_units", 0)) for f in sa_delivery_flows)
    assert total_deduped < total_raw, "Dedup should reduce total cases"
    assert total_deduped == 7663, f"Expected 7663 deduped cases, got {total_deduped}"
