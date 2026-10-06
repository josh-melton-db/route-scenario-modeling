from __future__ import annotations

from unittest.mock import MagicMock, Mock
from time import monotonic, sleep
from datetime import date

import pytest
from fastapi import HTTPException

from backend.services.demo_reset import DemoResetService
from backend.services.baseline_repository import BaselineRepository, BaselineRevision
from backend.services.baseline_service import BaselineService
from backend.services.depot_plan_repository import DepotPlanRepository
from backend.services.network_scenarios import NetworkScenarioRepository
from backend.services.solver_warmup import SolverWarmupService
from backend.services.lakebase_seed import LakebaseSeedService
from backend.services.sql import AnalyticsDataMissingError


def test_reset_rejects_active_network_work_before_deleting(monkeypatch) -> None:
    from backend.services import demo_reset as module

    monkeypatch.setattr(module.network_run_manager.repository, "has_active", lambda: True)
    canonical = Mock()
    monkeypatch.setattr(module.baseline_service, "canonical_revision", canonical)
    seeder = Mock()
    monkeypatch.setattr(module, "LakebaseSeedService", seeder)
    monkeypatch.setattr(module, "get_data_backend", lambda: "lakebase")
    clear = Mock()
    monkeypatch.setattr(module.network_run_manager.repository, "clear_all", clear)

    with pytest.raises(HTTPException, match="active network runs") as error:
        DemoResetService().reset()

    assert error.value.status_code == 409
    clear.assert_not_called()
    canonical.assert_not_called()
    seeder.assert_not_called()


def test_active_preflight_error_releases_reset_gate_and_lock(monkeypatch) -> None:
    from backend.services import demo_reset as module

    active = Mock(side_effect=[RuntimeError("database unavailable"), True])
    monkeypatch.setattr(module.network_run_manager.repository, "has_active", active)
    service = DemoResetService()

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.reset()
    with pytest.raises(HTTPException, match="active network runs") as retry:
        service.reset()

    assert retry.value.status_code == 409
    assert active.call_count == 2


def test_reset_clears_state_and_starts_async_warmup(monkeypatch) -> None:
    from backend.services import demo_reset as module

    monkeypatch.setattr(module.network_run_manager.repository, "has_active", lambda: False)
    monkeypatch.setattr(module.depot_plan_repository, "has_active", lambda: False)
    monkeypatch.setattr(module.network_run_manager.repository, "clear_all", lambda: 2)
    monkeypatch.setattr(module.demand_change_service.repository, "clear_all", lambda: 3)
    monkeypatch.setattr(module.depot_plan_repository, "clear_all", lambda: 4)
    monkeypatch.setattr(module.network_scenario_service.repository, "clear_all", lambda: 5)
    baseline = Mock()
    baseline.model_dump.return_value = {"active_revision_id": "original"}
    canonical = Mock()
    monkeypatch.setattr(module.baseline_service, "canonical_revision", lambda: canonical)
    monkeypatch.setattr(module.baseline_service, "install_canonical_revision", lambda revision: baseline)
    monkeypatch.setattr(module.solver_warmup_service, "start", lambda: {"state": "warming"})

    service = DemoResetService()
    response = service.reset()

    assert response["reset"]["state"] in {"resetting", "reset_complete"}
    deadline = monotonic() + 1
    while service.status()["state"] != "reset_complete" and monotonic() < deadline:
        sleep(0.01)
    assert service.status()["state"] == "reset_complete"


def test_lakebase_reset_always_runs_rate_seed_path(monkeypatch) -> None:
    from backend.services import demo_reset as module

    monkeypatch.setattr(module.network_run_manager.repository, "has_active", lambda: False)
    monkeypatch.setattr(module.depot_plan_repository, "has_active", lambda: False)
    monkeypatch.setattr(module, "get_data_backend", lambda: "lakebase")
    deferred: dict[str, object] = {}

    class DeferredThread:
        def __init__(self, *, target, **_: object) -> None:
            deferred["target"] = target

        def start(self) -> None:
            pass

    monkeypatch.setattr(module.threading, "Thread", DeferredThread)
    service = DemoResetService()
    try:
        response = service.reset()
        assert response["reset"]["state"] == "seeding_lakebase"
        assert deferred["target"] == service._seed_then_continue
    finally:
        module.demo_state_gate.end_reset()
        if service._lock.locked():
            service._lock.release()


def test_warmup_is_skipped_without_configured_endpoint(monkeypatch) -> None:
    from backend.services import solver_warmup as module

    monkeypatch.setattr(module, "get_route_solver_endpoint", lambda required=False: "")
    service = SolverWarmupService()

    assert service.start()["state"] == "skipped"
    assert service.status()["configured"] is False


def test_warmup_invokes_real_dataframe_contract(monkeypatch) -> None:
    from backend.services import solver_warmup as module
    from backend.services import solver as solver_module

    monkeypatch.setattr(module, "get_route_solver_endpoint", lambda required=False: "solver")
    invoke = Mock(return_value={"routes": [], "route_stops": [], "unassigned_stops": [], "diagnostics": []})
    monkeypatch.setattr(solver_module.solver_service, "invoke_endpoint", invoke)
    service = SolverWarmupService()

    service._invoke(0, "solver")

    call = invoke.call_args.kwargs
    assert call["scenario_id"] == "reset-warmup"
    assert len(call["planning_customers"]) == 1
    assert len(call["planning_fleet"]) == 1
    assert len(call["travel_matrix"]) == 4
    assert service.status()["state"] == "ready"


def test_baseline_reset_discards_non_original_history() -> None:
    repository = BaselineRepository()
    original = BaselineRevision("original", None, None, None, {"rows": [{"value": 1}]})
    repository.seed(original)
    repository._revisions["changed"] = BaselineRevision(
        "changed", "original", "run", "now", {"rows": [{"value": 2}]}
    )
    repository._active_id = "changed"

    repository.reset(clear_history=True)

    assert repository.ids() == ("original", "original")
    assert repository.revision("original").rows == original.rows
    assert set(repository._revisions) == {"original"}


def test_repository_clear_methods_remove_completed_demo_state() -> None:
    scenarios = NetworkScenarioRepository()
    scenarios._scenarios["scenario"] = Mock()
    scenarios._results["scenario"] = Mock()
    scenarios._run_snapshots["run"] = Mock()
    assert scenarios.clear_all() == 1
    assert not scenarios._scenarios and not scenarios._results and not scenarios._run_snapshots

    plans = DepotPlanRepository()
    plans.create({
        "plan_set_id": "plan", "parent_run_id": "run", "depot_id": "depot",
        "days": {"2026-01-01": {"default_status": "completed"}},
    })
    assert plans.clear_all() == 1
    assert plans.find("run", "depot") is None


def test_depot_plan_clear_rejects_pending_work() -> None:
    plans = DepotPlanRepository()
    plans.create({
        "plan_set_id": "plan", "parent_run_id": "run", "depot_id": "depot",
        "days": {"2026-01-01": {"default_status": "running"}},
    })

    with pytest.raises(HTTPException, match="active depot plans"):
        plans.clear_all()


def test_reset_reports_missing_bootstrap_configuration(monkeypatch) -> None:
    from backend.services import demo_reset as module

    monkeypatch.delenv("DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID", raising=False)
    monkeypatch.setattr(
        module.baseline_service,
        "canonical_revision",
        Mock(side_effect=HTTPException(status_code=409, detail="missing canonical tables")),
    )
    service = DemoResetService()
    service.reset()
    deadline = monotonic() + 1
    while service.status()["state"] != "failed" and monotonic() < deadline:
        sleep(0.01)
    assert service.status()["state"] == "failed"
    assert "DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID" in str(service.status()["error"])


def test_lakebase_seed_is_only_applied_when_a_reference_table_is_empty(monkeypatch) -> None:
    service = LakebaseSeedService(Mock())
    report = Mock()
    seed = Mock(return_value=report)
    rate_seed = Mock(return_value=9)
    monkeypatch.setattr(service, "seed_synthetic", seed)
    monkeypatch.setattr(service, "ensure_canonical_rate_books", rate_seed)
    monkeypatch.setattr(service, "reference_counts", lambda: {
        "depots": 1, "customers": 1, "fleet": 1, "orders": 1, "cost_parameters": 1,
    })
    assert service.ensure_synthetic_seeded() is None
    rate_seed.assert_called_once_with()
    seed.assert_not_called()

    monkeypatch.setattr(service, "reference_counts", lambda: {
        "depots": 0, "customers": 1, "fleet": 1, "orders": 1, "cost_parameters": 1,
    })
    assert service.ensure_synthetic_seeded() is report
    assert rate_seed.call_count == 2
    seed.assert_called_once_with(seed=42, customer_count=250)


def test_canonical_rate_seed_is_complete_and_preserves_published_versions(
    monkeypatch,
) -> None:
    from backend.services import lakebase_seed as module
    from backend.services import rates as rates_module

    postgres = MagicMock()
    postgres.qualified_table.side_effect = lambda name: f'"app"."{name}"'
    connection = object()
    postgres.transaction.return_value.__enter__.return_value = connection
    monkeypatch.setattr(module, "migrate_lakebase", Mock())
    monkeypatch.setattr(rates_module, "demo_date_anchor", lambda: date(2027, 11, 19))

    count = LakebaseSeedService(postgres).ensure_canonical_rate_books()

    assert count == 9
    statements = [call.args[0] for call in postgres.executemany.call_args_list]
    assert len(statements) == 8
    assert all("ON CONFLICT" in statement and "DO NOTHING" in statement for statement in statements)
    version_call = next(
        call
        for call in postgres.executemany.call_args_list
        if '"contract_versions"' in call.args[0]
    )
    versions = version_call.args[1]
    assert {row[0] for row in versions} >= {
        "GL_STANDARD_2026_V1_20271119_V1",
        "NE_STANDARD_2026_V1_20271119_V1",
        "SE_STANDARD_2026_V1_20271119_V1",
        "WEST_STANDARD_2026_V1_20271119_V1",
        "TOLA_STANDARD_2026_V1_20271119_V1",
        "CAN_STANDARD_2026_V1_20271119_V1",
        "MX_STANDARD_2026_V1_20271119_V1",
    }
    assert all(row[2] == 20271119 for row in versions)
    assert all(row[5:7] == ("2027-01-01", "2027-12-31") for row in versions)


@pytest.mark.parametrize("code", ["TABLE_OR_VIEW_NOT_FOUND", "SCHEMA_NOT_FOUND"])
def test_missing_canonical_sql_objects_are_mapped_to_bootstrap_conflict(
    monkeypatch, code: str
) -> None:
    from backend.services import baseline_service as module

    original = AnalyticsDataMissingError(code)
    monkeypatch.setattr(module.network_overview_service, "_load_option_rows", Mock(side_effect=original))

    with pytest.raises(HTTPException) as error:
        BaselineService().canonical_revision()

    assert error.value.status_code == 409
    assert error.value is original
    assert error.value.error_type == code


def test_non_missing_canonical_sql_error_preserves_original_status(monkeypatch) -> None:
    from backend.services import baseline_service as module

    original = HTTPException(status_code=502, detail="PERMISSION_DENIED")
    monkeypatch.setattr(module.network_overview_service, "_load_option_rows", Mock(side_effect=original))

    with pytest.raises(HTTPException) as error:
        BaselineService().canonical_revision()

    assert error.value is original


def test_missing_canonical_sql_conflict_dispatches_bootstrap(monkeypatch) -> None:
    from backend.services import demo_reset as module

    monkeypatch.setenv("DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID", "123")
    monkeypatch.setattr(module.network_run_manager.repository, "has_active", lambda: False)
    monkeypatch.setattr(module.depot_plan_repository, "has_active", lambda: False)
    monkeypatch.setattr(module, "get_data_backend", lambda: "stub")
    monkeypatch.setattr(
        module.baseline_service,
        "canonical_revision",
        Mock(side_effect=HTTPException(
            status_code=409,
            detail="Canonical network data is not bootstrapped: TABLE_OR_VIEW_NOT_FOUND",
        )),
    )
    started = Mock()
    deferred: dict[str, object] = {}

    class DeferredThread:
        def __init__(self, *, target, **_: object) -> None:
            deferred["target"] = target

        def start(self) -> None:
            started()

    monkeypatch.setattr(module.threading, "Thread", DeferredThread)
    service = DemoResetService()
    bootstrap = Mock(return_value=Mock())
    complete = Mock()
    monkeypatch.setattr(service, "_run_bootstrap", bootstrap)
    monkeypatch.setattr(service, "_complete", complete)
    try:
        response = service.reset()
        assert response["reset"]["state"] == "resetting"
        started.assert_called_once_with()
        deferred["target"]()
        assert service.status()["state"] == "bootstrapping"
        bootstrap.assert_called_once_with("123")
        complete.assert_called_once()
    finally:
        module.demo_state_gate.end_reset()
        if service._lock.locked():
            service._lock.release()


def test_canonical_snapshot_query_is_scoped_to_default_plans_and_horizon(monkeypatch) -> None:
    from backend.services import baseline_service as module

    options = {
        "dim_regions": [{"region_id": "ALL"}],
        "dim_facilities": [{"facility_id": "D"}],
        "demand_plan_versions": [{
            "plan_version_id": "DEMAND", "horizon_start": "2026-10-01",
            "horizon_end": "2026-10-28", "published_at": "2026-10-01",
        }],
        "capacity_plan_versions": [{
            "plan_version_id": "CAPACITY", "horizon_start": "2026-10-03",
            "horizon_end": "2026-10-30", "published_at": "2026-10-01",
        }],
    }
    captured: dict[str, object] = {}

    def scoped_load(**kwargs: object):
        captured.update(kwargs)
        raise RuntimeError("stop after query contract")

    monkeypatch.setattr(module.network_overview_service, "_load_option_rows", lambda: options)
    monkeypatch.setattr(module.network_overview_service, "_load_rows", scoped_load)

    with pytest.raises(RuntimeError, match="query contract"):
        BaselineService().canonical_revision()

    assert captured == {
        "demand_plan_version_id": "DEMAND",
        "capacity_plan_version_id": "CAPACITY",
        "horizon_start": date(2026, 10, 3),
        "horizon_end": date(2026, 10, 28),
    }
