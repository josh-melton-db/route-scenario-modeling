from __future__ import annotations

import inspect
import threading
import time
from contextlib import contextmanager

from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import meta, rates, scenarios
from backend.services import lakebase_migrations


def test_health_is_live_and_propagates_request_id() -> None:
    response = TestClient(app).get("/api/health", headers={"x-request-id": "test-request-123"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"] == "test-request-123"


def test_blocking_store_routes_are_threadpool_handlers() -> None:
    assert not inspect.iscoroutinefunction(meta.depots)
    assert not inspect.iscoroutinefunction(rates.rate_contracts)
    assert not inspect.iscoroutinefunction(scenarios.recent_scenarios)


def test_slow_store_read_does_not_stall_liveness(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()

    class SlowStore:
        def list_depots(self):
            entered.set()
            release.wait(timeout=2)
            return []

    monkeypatch.setattr(meta, "get_store", lambda: SlowStore())
    client = TestClient(app)
    request = threading.Thread(target=lambda: client.get("/api/meta/depots"), daemon=True)
    request.start()
    assert entered.wait(timeout=1)
    started = time.perf_counter()
    response = client.get("/api/health")
    elapsed = time.perf_counter() - started
    release.set()
    request.join(timeout=1)
    assert response.status_code == 200
    assert elapsed < 0.5


def test_stub_readiness_is_healthy(monkeypatch) -> None:
    monkeypatch.setenv("DATA_BACKEND", "stub")
    monkeypatch.delenv("ROUTING_COVERAGE_MANIFEST", raising=False)
    response = TestClient(app).get("/api/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["routing_coverage"]["supported_depot_ids"] == []


def test_regional_readiness_requires_endpoint_and_validated_coverage(monkeypatch) -> None:
    from backend.services import platform_health

    monkeypatch.setenv("DATA_BACKEND", "stub")
    monkeypatch.setenv("ROUTE_EXECUTION_MODE", "serving_regional")
    monkeypatch.delenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", raising=False)
    monkeypatch.setattr(platform_health, "validated_routing_coverages", lambda _: [])
    ready, payload = platform_health.readiness_snapshot()
    assert not ready
    assert not payload["checks"]["route_solver"]["ready"]
    assert not payload["checks"]["routing_coverage"]["ready"]

    monkeypatch.setenv("DATABRICKS_ROUTE_SOLVER_ENDPOINT", "test-solver")
    monkeypatch.setattr(platform_health, "validated_routing_coverages", lambda _: [
        {"coverage_id": "texas", "depot_ids": ["DPT_TOLA_DALLAS"]},
    ])
    ready, payload = platform_health.readiness_snapshot()
    assert ready
    assert payload["checks"]["route_solver"]["matrix_policy"] == "validated_road_else_approximate"


class _MigrationService:
    schema = "test"

    def __init__(self) -> None:
        self.statements: list[str] = []

    def initialize(self) -> None:
        pass

    def qualified_table(self, name: str) -> str:
        return f'"test"."{name}"'

    @contextmanager
    def transaction(self):
        yield object()

    def execute(self, statement, params=None, *, connection=None):
        self.statements.append(" ".join(statement.split()))
        return 0

    def query_one(self, statement, params=None, *, connection=None):
        return {"applied": 1}


def test_migration_takes_transaction_scoped_advisory_lock() -> None:
    service = _MigrationService()
    lakebase_migrations.migrate_lakebase(service)  # type: ignore[arg-type]
    assert any("pg_advisory_xact_lock" in statement for statement in service.statements)
    assert lakebase_migrations.migration_status()["state"] == "ready"


def test_migration_expands_depot_plan_job_status_for_lazy_days() -> None:
    assert lakebase_migrations.MIGRATION_VERSION.endswith("_v16")
    service = _MigrationService()
    statements = list(lakebase_migrations._statements(service))  # type: ignore[attr-defined,arg-type]
    status_constraints = [
        statement for statement in statements
        if "depot_plan_jobs_status_check" in statement
    ]
    assert any("DROP CONSTRAINT IF EXISTS" in statement for statement in status_constraints)
    assert any("'not_requested'" in statement for statement in status_constraints)


def test_lazy_status_migration_runs_when_prior_version_is_already_recorded() -> None:
    class PriorVersionService(_MigrationService):
        def query_one(self, statement, params=None, *, connection=None):
            assert params == (lakebase_migrations.MIGRATION_VERSION,)
            return None

    service = PriorVersionService()
    lakebase_migrations.migrate_lakebase(service)  # type: ignore[arg-type]
    assert any(
        "ALTER TABLE" in statement
        and "depot_plan_jobs_status_check" in statement
        and "'not_requested'" in statement
        for statement in service.statements
    )
    assert any(
        "INSERT INTO" in statement
        and "schema_migrations" in statement
        for statement in service.statements
    )
