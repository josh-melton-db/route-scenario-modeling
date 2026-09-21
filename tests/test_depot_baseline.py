from route_opt.depot_baseline import DELIVERY_DAY, generate_depot_baseline
from route_opt.network_synthetic import national_dataset_cached


def test_generated_depot_baseline_is_coherent_and_deterministic() -> None:
    rows = national_dataset_cached(seed=42)
    first = generate_depot_baseline(rows, "DPT_CHICAGO")
    second = generate_depot_baseline(rows, "DPT_CHICAGO")

    baseline = first["baseline"]
    assert baseline["depot"]["depot_id"] == "DPT_CHICAGO"
    assert baseline["delivery_day"] == DELIVERY_DAY
    assert baseline["matrix_source"] == "haversine_circuity"
    assert len(baseline["routes"]) >= 10
    stop_count = sum(len(route["stops"]) for route in baseline["routes"])
    assert stop_count == 100
    for route in baseline["routes"]:
        assert route["depot_id"] == "DPT_CHICAGO"
        assert route["total_miles"] > 0
        assert route["total_cost"] > 0
        for stop in route["stops"]:
            assert stop["demand_cases"] >= 1
            assert stop["service_minutes"] >= 15
            assert stop["arrival_time"] < stop["departure_time"]

    kpis = first["kpis"]
    assert kpis["route_count"] == len(baseline["routes"])
    assert kpis["total_cases"] == sum(
        route["total_cases"] for route in baseline["routes"]
    )
    assert kpis["cost_breakdown"]["total_cost"] == round(
        sum(route["total_cost"] for route in baseline["routes"]), 2
    )
    assert kpis["total_revenue"] == round(kpis["total_cases"] * 6.25, 2)
    assert kpis["profit"] == round(kpis["total_revenue"] - kpis["cost_breakdown"]["total_cost"], 2)

    first["baseline"].pop("generated_at")
    second["baseline"].pop("generated_at")
    assert first["baseline"] == second["baseline"]


def test_generated_depot_baseline_rejects_non_depot() -> None:
    rows = national_dataset_cached(seed=42)
    try:
        generate_depot_baseline(rows, "DC_GREAT_LAKES_WEST")
    except KeyError:
        pass
    else:
        raise AssertionError("Distribution centers cannot have depot baselines.")


def test_every_network_depot_gets_a_baseline() -> None:
    rows = national_dataset_cached(seed=42)
    depot_ids = [
        str(row["facility_id"])
        for row in rows["dim_facilities"]
        if row["facility_type"] == "depot"
    ]
    assert len(depot_ids) == 30
    for depot_id in depot_ids:
        result = generate_depot_baseline(rows, depot_id)
        assert result["baseline"]["depot"]["depot_id"] == depot_id
        assert result["kpis"]["route_count"] >= 10
