from backend.services.network_overview import NetworkOverviewService, _local_network_rows
from route_opt.schemas import NETWORK_TABLES


def test_sql_snapshot_retains_complete_network_table_shape(monkeypatch):
    service = NetworkOverviewService()
    captured = {}
    monkeypatch.setattr(service, "_run_sql_queries", lambda sql, statements: captured.update(statements) or {})
    service._load_sql_rows(
        demand_plan_version_id=None, capacity_plan_version_id=None,
        horizon_start=None, horizon_end=None,
    )
    assert set(captured) == set(NETWORK_TABLES)
    assert all("SELECT *" in statement for statement in captured.values())
    assert all("GROUP BY" not in statement for statement in captured.values())


def test_legacy_options_metadata_does_not_rewrite_baseline(monkeypatch):
    from backend.services.baseline_service import baseline_service

    rows = _local_network_rows()
    legacy = {key: value for key, value in rows.items() if key != "dim_regions"}
    monkeypatch.setattr(baseline_service, "active_rows", lambda: legacy)
    service = NetworkOverviewService()
    monkeypatch.setattr(service, "_load_option_rows", lambda: rows)
    result = service.get_options()
    assert len(result.regions) == len(rows["dim_regions"]) + 1
    assert "dim_regions" not in legacy
