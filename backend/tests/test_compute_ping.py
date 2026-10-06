from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.warehouse_warmup import WarehouseWarmupService


def execution(state, statement_id="ping-statement"):
    return SimpleNamespace(status=SimpleNamespace(state=state), statement_id=statement_id)


def test_warehouse_ping_waits_for_query_success_after_cold_start(monkeypatch):
    from backend.services import warehouse_warmup as module
    statements = SimpleNamespace(execute_statement=Mock(return_value=execution("PENDING")),
        get_statement=Mock(side_effect=[execution("RUNNING"), execution("SUCCEEDED")]))
    monkeypatch.setattr(module, "get_workspace_client", lambda: SimpleNamespace(statement_execution=statements))
    monkeypatch.setattr(module, "get_sql_warehouse_id", lambda: "configured-warehouse")
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    WarehouseWarmupService._ping()
    statements.execute_statement.assert_called_once_with(warehouse_id="configured-warehouse",
        statement="SELECT 1 AS ready", wait_timeout="0s")
    assert statements.get_statement.call_count == 2


def test_warehouse_ping_never_falls_back_to_an_unconfigured_warehouse(monkeypatch):
    from backend.services import warehouse_warmup as module
    query = Mock()
    client = SimpleNamespace(warehouses=SimpleNamespace(list=lambda: [SimpleNamespace(id="other", name="Other warehouse")]),
        statement_execution=SimpleNamespace(execute_statement=query))
    monkeypatch.setattr(module, "get_workspace_client", lambda: client)
    monkeypatch.setattr(module, "get_sql_warehouse_id", lambda: None)
    monkeypatch.setattr(module, "get_sql_warehouse_name", lambda: "Demo warehouse")
    with pytest.raises(ValueError, match="configured SQL warehouse"):
        WarehouseWarmupService._ping()
    query.assert_not_called()


def test_warehouse_ping_deduplicates_and_can_be_repeated_after_success(monkeypatch):
    from backend.services import warehouse_warmup as module
    threads = []
    class DeferredThread:
        def __init__(self, *, target, **kwargs):
            threads.append(target)
        def start(self):
            pass
    monkeypatch.setattr(module.threading, "Thread", DeferredThread)
    monkeypatch.setattr(module, "get_sql_warehouse_id", lambda: "configured")
    monkeypatch.setattr(module, "get_data_backend", lambda: "lakebase")
    service = WarehouseWarmupService()
    monkeypatch.setattr(service, "_ping", lambda: None)
    assert service.start()["state"] == "warming"
    assert service.start()["state"] == "warming"
    assert len(threads) == 1
    threads[0]()
    assert service.status()["state"] == "ready"
    assert service.start()["state"] == "warming"
    assert len(threads) == 2


def test_stub_ping_is_skipped_and_cannot_touch_remote_compute(monkeypatch):
    from backend.services import warehouse_warmup as module
    monkeypatch.setattr(module, "get_data_backend", lambda: "stub")
    monkeypatch.setattr(module, "get_sql_warehouse_id", lambda: "configured")
    client = Mock()
    monkeypatch.setattr(module, "get_workspace_client", client)
    assert WarehouseWarmupService().start()["state"] == "skipped"
    client.assert_not_called()


def test_warehouse_timeout_cancels_the_probe(monkeypatch):
    from backend.services import warehouse_warmup as module
    statements = SimpleNamespace(execute_statement=Mock(return_value=execution("PENDING")), cancel_execution=Mock())
    monkeypatch.setattr(module, "get_workspace_client", lambda: SimpleNamespace(statement_execution=statements))
    monkeypatch.setattr(module, "get_sql_warehouse_id", lambda: "configured")
    monkeypatch.setattr(module.time, "monotonic", Mock(side_effect=[0, 601]))
    with pytest.raises(TimeoutError):
        WarehouseWarmupService._ping()
    statements.cancel_execution.assert_called_once_with("ping-statement")


def test_ping_routes_are_explicit_and_readiness_does_not_start_warmup(monkeypatch):
    from backend.routes import compute
    from backend.services import platform_health
    warehouse = Mock(return_value={"state": "warming"})
    solver = Mock(return_value={"state": "warming"})
    monkeypatch.setattr(compute.warehouse_warmup_service, "start", warehouse)
    monkeypatch.setattr(compute.solver_warmup_service, "start", solver)
    monkeypatch.setenv("DATA_BACKEND", "stub")
    monkeypatch.setattr(platform_health, "validated_routing_coverages", lambda _: [])
    client = TestClient(app)
    client.get("/api/ready")
    warehouse.assert_not_called()
    solver.assert_not_called()
    assert client.post("/api/compute/sql-warehouse/ping").status_code == 202
    warehouse.assert_called_once()
    solver.assert_not_called()
    assert client.post("/api/compute/route-solver/ping").status_code == 202
    solver.assert_called_once()
    assert client.post("/api/compute/unknown/ping").status_code == 422
