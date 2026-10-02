from datetime import date, datetime, timezone

import pytest

from backend.services.network_scenarios import (
    NetworkScenarioRepository,
    lakebase_store,
)


@pytest.mark.parametrize("native_dates", [True, False])
def test_lakebase_scenario_list_and_detail_normalize_dates(monkeypatch, native_dates):
    timestamp = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    row = {
        "scenario_id": "date-regression",
        "scenario_name": "Date regression",
        "baseline_scenario_id": "baseline",
        "demand_plan_version_id": "demand",
        "capacity_plan_version_id": "capacity",
        "horizon_start": date(2026, 10, 2) if native_dates else "2026-10-02",
        "horizon_end": date(2026, 10, 29) if native_dates else "2026-10-29",
        "region_id": "ALL",
        "status": "draft",
        "revision": 1,
        "assumptions": '{"source_baseline_revision_id": "revision-1"}',
        "validation": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "solved_at": None,
    }
    monkeypatch.setattr(
        NetworkScenarioRepository, "_uses_lakebase", property(lambda self: True)
    )
    monkeypatch.setattr(NetworkScenarioRepository, "_table", lambda self, name: name)
    monkeypatch.setattr(lakebase_store.postgres, "query", lambda *args: [row])
    monkeypatch.setattr(lakebase_store.postgres, "query_one", lambda *args: row)
    repository = NetworkScenarioRepository()

    listed = repository.list()
    detail = repository.get("date-regression")

    assert listed == [detail]
    assert detail.horizon_start == "2026-10-02"
    assert detail.horizon_end == "2026-10-29"
    assert detail.source_baseline_revision_id == "revision-1"
    assert detail.created_at == str(timestamp)
    assert detail.solved_at is None
    assert row["horizon_start"] == (
        date(2026, 10, 2) if native_dates else "2026-10-02"
    )
