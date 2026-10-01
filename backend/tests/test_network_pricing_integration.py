from datetime import date, timedelta

from backend.models import NetworkScenarioCreateRequest
from backend.services import network_scenarios
from backend.services.network_overview import network_overview_service
from backend.services.network_scenarios import NetworkScenarioService


def test_new_original_baseline_freezes_rates_for_cache_reconstruction(monkeypatch):
    from backend.services.baseline_service import BaselineService
    from backend.services import rates

    service = BaselineService()
    revision = service.get_revision()
    demand_id, capacity_id = service._plan_ids(revision.rows)
    start = next(row["horizon_start"] for row in revision.rows["demand_plan_versions"]
                 if row["plan_version_id"] == demand_id)
    first = service.get_plan_run(
        demand_plan_version_id=demand_id, capacity_plan_version_id=capacity_id,
        horizon_start=str(start)[:10], horizon_end=str(start)[:10],
    )
    with service._plan_cache_lock:
        service._plan_run_cache.clear()

    def reject_live_rates(_store):
        raise AssertionError("Reconstruct original planning runs from their frozen rates")

    monkeypatch.setattr(rates, "list_rate_contract_details", reject_live_rates)
    restored = service.resolve_plan_run(first.result.run_id)
    assert restored.result == first.result
    assert restored.cost_rows == first.cost_rows


def test_reassignment_preserves_parent_rates_tariffs_and_scoped_totals(monkeypatch):
    service = NetworkScenarioService()
    options = network_overview_service.get_options()
    start = options.default_horizon_start
    end = (date.fromisoformat(start) + timedelta(days=1)).isoformat()
    scenario = service.create(NetworkScenarioCreateRequest(
        scenario_name="Pinned dated pricing regression",
        demand_plan_version_id=options.default_demand_plan_version_id,
        capacity_plan_version_id=options.default_capacity_plan_version_id,
        horizon_start=start, horizon_end=end, region_id="REGION_TOLA",
        assumptions={"tariffs": [{
            "rule_id": "PARENT-TARIFF", "origin_country": "MX", "destination_country": "US",
            "effective_start": start, "effective_end": end, "amount_per_case": 0.01,
        }]},
    ))
    rated_dates = []
    original_objective = service._solver_lane_unit_costs

    def dated_objective(rows, service_date, contracts=None):
        rated_dates.append(service_date)
        return original_objective(rows, service_date, contracts)

    monkeypatch.setattr(service, "_solver_lane_unit_costs", dated_objective)
    first = service.run(scenario.scenario_id).result
    assert rated_dates == [start, end]
    assert first.tariff_total_cost > 0
    assert first.scenario_total_modeled_cost == first.overview.kpis.total_cost
    assert first.baseline_total_modeled_cost == first.baseline_overview.kpis.total_cost
    assert {row.lane_id for row in first.charge_details} <= {
        lane.lane_id for lane in first.overview.lanes
    }

    def reject_live_rates(_store):
        raise AssertionError("A reassignment must use its parent's pinned rate snapshot")

    monkeypatch.setattr(network_scenarios, "list_rate_contract_details", reject_live_rates)
    reassigned = service.reassign(first.run_id, []).result
    assert reassigned.pricing_context.contract_snapshots == first.pricing_context.contract_snapshots
    assert reassigned.pricing_context.baseline_tariffs == first.pricing_context.scenario_tariffs
    assert reassigned.baseline_tariff_total_cost == first.tariff_total_cost
    assert reassigned.baseline_total_modeled_cost == first.scenario_total_modeled_cost
    assert reassigned.kpi_deltas.total_cost == 0
    assert service.get_run_snapshot(first.run_id).result == first
