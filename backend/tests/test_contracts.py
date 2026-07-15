from backend.models import BaselineNetwork, ComparisonResult, Kpis
from backend.services.stub_store import store


def test_baseline_contracts_validate() -> None:
    network = store.get_baseline_network("DPT_NORTH", "Tuesday")
    kpis = store.get_baseline_kpis("DPT_NORTH", "Tuesday")

    assert isinstance(network, BaselineNetwork)
    assert isinstance(kpis, Kpis)
    assert len(network.routes) == 4
    assert sum(len(route.stops) for route in network.routes) == 24
    assert kpis.cost_breakdown.total_cost == 4920


def test_scenario_results_validate_after_hydration() -> None:
    for scenario_id in [
        "scn_baseline_identity",
        "scn_driver_minus_one",
        "scn_ma_newcustomers",
        "scn_day_change",
        "scn_facility_move",
    ]:
        result = store.get_scenario_result(scenario_id)
        assert isinstance(result, ComparisonResult)
        assert result.baseline_routes
        assert result.scenario_routes


def test_demo_data_uses_generic_labels() -> None:
    result = store.get_scenario_result("scn_ma_newcustomers")
    banned = ("kroger", "walmart", "sysco", "pepsi", "coca-cola", "kdp")
    for impact in result.customer_impacts:
        name = impact.customer_name.lower()
        assert impact.customer_name.strip()
        assert not any(token in name for token in banned)
        assert any(
            token in name
            for token in (
                "retailer",
                "account",
                "customer",
                "store",
                "location",
                "market",
                "grocery",
                "foods",
                "retail",
            )
        )
