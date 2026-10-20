from copy import deepcopy
import json

from backend.services.depot_contracted_overflow import apply_contracted_overflow
from backend.services.depot_route_execution import DatedRouteExecutor
from backend.services.rates import canonical_rate_contract_details
from route_opt.cost import CostParameters
from route_opt.network_synthetic import national_dataset_cached


def test_san_antonio_full_fleet_horizon_before_after(monkeypatch):
    from route_opt import demo_dates

    monkeypatch.setenv("DEMO_DATE_ANCHOR", "2026-10-06")
    demo_dates.demo_date_anchor.cache_clear()
    try:
        rows = national_dataset_cached()
        depot_id = "DPT_TOLA_SAN_ANTONIO"
        fleet = [{"vehicle_id": f"SYN-{depot_id}-{index + 1:02d}", "depot_id": depot_id,
                  "capacity_cases": 720, "max_route_minutes": 600, "max_stops_per_route": 12,
                  "fixed_truck_daily_cost": 340} for index in range(16)]
        details = [detail.model_dump(mode="json") for detail in canonical_rate_contract_details()]
        days = sorted({str(row["service_date"])[:10] for row in rows["baseline_network_flow_daily"]})
        observations = []
        executor = DatedRouteExecutor(mode="approximate_development")
        for service_date in days:
            source = executor(network_rows=rows, flow_rows=rows["baseline_network_flow_daily"],
                              depot_id=depot_id, service_date=service_date, fleet=fleet,
                              scenario_id="carrier-choice-audit", cost_parameters=CostParameters())
            before, after = deepcopy(source), deepcopy(source)
            arguments = dict(network_rows=rows, depot_id=depot_id, service_date=service_date,
                             fleet=fleet, cost_parameters=CostParameters(), contract_details=details, enabled=True)
            apply_contracted_overflow(before, **arguments)
            apply_contracted_overflow(after, **arguments, allow_cost_based_outsourcing=True)
            assert after["kpis"]["cost_breakdown"]["total_cost"] <= before["kpis"]["cost_breakdown"]["total_cost"]
            assert after["kpis"]["total_revenue"] == before["kpis"]["total_revenue"]
            assert after["routed_cases"] + after["contracted_cases"] + after["unserved_cases"] == after["assigned_cases"]
            def metrics(result):
                return {"fleet_stops": sum(len(route["stops"]) for route in result["routes"]),
                        "contracted_stops": result["contracted_deliveries"],
                        "unserved_stops": len(result["unserved_orders"]),
                        "fleet_cost": result["fleet_cost"], "contracted_cost": result["contracted_cost"],
                        "total_cost": result["kpis"]["cost_breakdown"]["total_cost"],
                        "revenue": result["kpis"]["total_revenue"]}
            observations.append({"date": service_date, "before": metrics(before), "after": metrics(after),
                                 "outsourced_by_cost": after["outsourced_by_cost_deliveries"],
                                 "savings": after["outsourcing_savings"]})
        assert any(day["date"] == "2026-10-06" for day in observations)
        print("SAN_ANTONIO_CARRIER_CHOICE", json.dumps({
            "days": observations, "days_with_savings": sum(day["savings"] > 0 for day in observations),
            "days_tested": len(observations),
            "total_outsourced_by_cost": sum(day["outsourced_by_cost"] for day in observations),
            "total_savings": round(sum(day["savings"] for day in observations), 2)}))
    finally:
        demo_dates.demo_date_anchor.cache_clear()
