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
