from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from ..config import get_data_backend, get_sql_warehouse_id, get_sql_warehouse_name, get_workspace_client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WarehouseWarmupService:
    """Wake only the configured warehouse without blocking the App request."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status: dict[str, Any] = {
            "state": "not_started", "configured": False, "endpoint": None,
            "started_at": None, "completed_at": None, "error": None,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(self) -> dict[str, Any]:
        warehouse = get_sql_warehouse_id() or get_sql_warehouse_name()
        with self._lock:
            if self._status["state"] == "warming":
                return dict(self._status)
            configured = bool(warehouse) and get_data_backend() != "stub"
            self._status = {
                "state": "warming" if configured else "skipped",
                "configured": configured, "endpoint": warehouse,
                "started_at": _now(), "completed_at": None if configured else _now(),
                "error": None,
            }
            if not configured:
                return dict(self._status)
        threading.Thread(target=self._invoke, name="sql-warehouse-warmup", daemon=True).start()
        return self.status()

    def _invoke(self) -> None:
        try:
            self._ping()
        except Exception as exc:
            state, error = "failed", f"{type(exc).__name__}: {str(exc)[:500]}"
        else:
            state, error = "ready", None
        with self._lock:
            self._status.update(state=state, error=error, completed_at=_now())

    @staticmethod
    def _ping() -> None:
        client = get_workspace_client()
        warehouse_id = get_sql_warehouse_id()
        if not warehouse_id:
            name = get_sql_warehouse_name()
            matches = [row.id for row in client.warehouses.list() if row.id and row.name == name]
            if len(matches) != 1:
                raise ValueError("The configured SQL warehouse name must identify exactly one warehouse.")
            warehouse_id = matches[0]
        execution = client.statement_execution.execute_statement(
            warehouse_id=warehouse_id, statement="SELECT 1 AS ready", wait_timeout="0s",
        )
        deadline = time.monotonic() + 600
        while True:
            state = getattr(getattr(execution, "status", None), "state", None)
            state = str(getattr(state, "value", state))
            if state == "SUCCEEDED":
                return
            if state in {"FAILED", "CANCELED", "CLOSED"}:
                raise RuntimeError(f"SQL warehouse ping ended with {state}. Check warehouse status and access.")
            statement_id = execution.statement_id
            if not statement_id:
                raise RuntimeError("SQL warehouse ping did not return a statement ID.")
            if time.monotonic() >= deadline:
                try:
                    client.statement_execution.cancel_execution(statement_id)
                except Exception:
                    pass
                raise TimeoutError("SQL warehouse did not answer the ping within 10 minutes.")
            time.sleep(2)
            execution = client.statement_execution.get_statement(statement_id)


warehouse_warmup_service = WarehouseWarmupService()
