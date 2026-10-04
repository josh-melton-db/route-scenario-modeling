from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from ..config import get_data_backend
from ..models import NetworkRunDiagnostics, NetworkRunRecord, NetworkScenario
from .lakebase_store import lakebase_store


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def network_run_idempotency_key(scenario: NetworkScenario) -> str:
    payload = {
        "scenario_id": scenario.scenario_id,
        "revision": scenario.revision,
        "source_baseline_revision_id": scenario.source_baseline_revision_id,
        "demand_plan_version_id": scenario.demand_plan_version_id,
        "capacity_plan_version_id": scenario.capacity_plan_version_id,
        "horizon_start": scenario.horizon_start,
        "horizon_end": scenario.horizon_end,
        "region_id": scenario.region_id,
        "assumptions": scenario.assumptions.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"network:{scenario.scenario_id}:{scenario.revision}:{digest}"


class NetworkRunJobRepository:
    def __init__(self) -> None:
        self._rows: dict[str, NetworkRunRecord] = {}
        self._by_key: dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def _uses_lakebase(self) -> bool:
        return get_data_backend() == "lakebase"

    def _table(self) -> str:
        return lakebase_store.postgres.qualified_table("network_run_jobs")

    @staticmethod
    def _record(row: dict[str, Any]) -> NetworkRunRecord:
        diagnostics = row.get("diagnostics")
        if isinstance(diagnostics, str):
            diagnostics = json.loads(diagnostics)
        demand_change_ids = row.get("demand_change_ids") or []
        if isinstance(demand_change_ids, str):
            demand_change_ids = json.loads(demand_change_ids)
        return NetworkRunRecord.model_validate(
            {
                **row,
                "status_url": f"/api/network/run-requests/{row['run_id']}",
                "queued_at": str(row["queued_at"]),
                "started_at": str(row["started_at"]) if row.get("started_at") else None,
                "completed_at": str(row["completed_at"]) if row.get("completed_at") else None,
                "lease_expires_at": (
                    str(row["lease_expires_at"]) if row.get("lease_expires_at") else None
                ),
                "diagnostics": diagnostics,
                "demand_change_ids": demand_change_ids,
            }
        )

    def create(
        self, scenario: NetworkScenario, *, max_queued: int, max_attempts: int = 3,
        idempotency_key: str | None = None,
        run_kind: str = "scenario",
        parent_run_id: str | None = None,
        demand_change_ids: list[str] | None = None,
    ) -> tuple[NetworkRunRecord, bool]:
        key = idempotency_key or network_run_idempotency_key(scenario)
        frozen_change_ids = sorted(demand_change_ids or [])
        run_id = f"network-run-{uuid.uuid4()}"
        queued_at = _text()
        if not self._uses_lakebase:
            with self._lock:
                existing_id = self._by_key.get(key)
                if existing_id:
                    existing = self._rows[existing_id]
                    if (
                        existing.status == "failed" and existing.retryable
                        and existing.attempt_count < max_attempts
                    ):
                        existing = existing.model_copy(update={
                            "status": "queued", "completed_at": None,
                            "error_code": None, "error_message": None,
                        })
                        self._rows[existing_id] = existing
                        return existing.model_copy(deep=True), True
                    return existing.model_copy(deep=True), False
                active = sum(row.status in {"queued", "running"} for row in self._rows.values())
                if active >= max_queued:
                    raise HTTPException(status_code=429, detail="Network run queue is full.")
                record = NetworkRunRecord(
                    run_id=run_id,
                    scenario_id=scenario.scenario_id,
                    revision=scenario.revision,
                    idempotency_key=key,
                    status="queued",
                    status_url=f"/api/network/run-requests/{run_id}",
                    queued_at=queued_at,
                    run_kind=run_kind,
                    parent_run_id=parent_run_id,
                    demand_change_ids=frozen_change_ids,
                )
                self._rows[run_id] = record
                self._by_key[key] = run_id
                return record.model_copy(deep=True), True

        with lakebase_store.postgres.transaction() as connection:
            lakebase_store.postgres.query_one(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (key,), connection=connection,
            )
            existing = lakebase_store.postgres.query_one(
                f"SELECT * FROM {self._table()} WHERE idempotency_key = %s",
                (key,), connection=connection,
            )
            if existing:
                if (
                    existing["status"] == "failed" and existing.get("retryable")
                    and int(existing.get("attempt_count", 0)) < max_attempts
                ):
                    lakebase_store.postgres.execute(
                        f"UPDATE {self._table()} SET status='queued', completed_at=NULL, "
                        "error_code=NULL, error_message=NULL WHERE run_id=%s",
                        (existing["run_id"],), connection=connection,
                    )
                    existing = lakebase_store.postgres.query_one(
                        f"SELECT * FROM {self._table()} WHERE run_id=%s",
                        (existing["run_id"],), connection=connection,
                    )
                    return self._record(existing or {}), True
                return self._record(existing), False
            count = lakebase_store.postgres.query_one(
                f"SELECT COUNT(*) AS count FROM {self._table()} "
                "WHERE status IN ('queued','running')",
                connection=connection,
            )
            if int((count or {}).get("count", 0)) >= max_queued:
                raise HTTPException(status_code=429, detail="Network run queue is full.")
            lakebase_store.postgres.execute(
                f"""INSERT INTO {self._table()} (
                    run_id, scenario_id, revision, idempotency_key, status,
                    attempt_count, queued_at, retryable, run_kind,
                    parent_run_id, demand_change_ids
                ) VALUES (%s,%s,%s,%s,'queued',0,%s,FALSE,%s,%s,%s)""",
                (
                    run_id, scenario.scenario_id, scenario.revision, key, queued_at,
                    run_kind, parent_run_id,
                    lakebase_store.postgres.jsonb(frozen_change_ids),
                ),
                connection=connection,
            )
        return self.get(run_id), True

    def get(self, run_id: str) -> NetworkRunRecord:
        if not self._uses_lakebase:
            with self._lock:
                row = self._rows.get(run_id)
                if row is None:
                    raise HTTPException(status_code=404, detail="Network run request not found.")
                return row.model_copy(deep=True)
        row = lakebase_store.postgres.query_one(
            f"SELECT * FROM {self._table()} WHERE run_id = %s", (run_id,)
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Network run request not found.")
        return self._record(row)

    def record_api_response(
        self, run_id: str, *, encoding_seconds: float, payload_bytes: int
    ) -> None:
        """Record transport telemetry without mutating the immutable run snapshot."""

        if not self._uses_lakebase:
            with self._lock:
                row = self._rows.get(run_id)
                if row is None or row.diagnostics is None:
                    return
                diagnostics = row.diagnostics.model_copy(deep=True)
                diagnostics.stage_seconds["api_response_encoding"] = round(
                    encoding_seconds, 6
                )
                diagnostics.api_response_bytes = payload_bytes
                self._rows[run_id] = row.model_copy(
                    update={"diagnostics": diagnostics}
                )
            return
        row = lakebase_store.postgres.query_one(
            f"SELECT diagnostics FROM {self._table()} WHERE run_id=%s",
            (run_id,),
        )
        if row is None or not row.get("diagnostics"):
            return
        diagnostics = NetworkRunDiagnostics.model_validate(row["diagnostics"])
        diagnostics.stage_seconds["api_response_encoding"] = round(
            encoding_seconds, 6
        )
        diagnostics.api_response_bytes = payload_bytes
        lakebase_store.postgres.execute(
            f"UPDATE {self._table()} SET diagnostics=%s WHERE run_id=%s",
            (
                lakebase_store.postgres.jsonb(diagnostics.model_dump(mode="json")),
                run_id,
            ),
        )

    def claim(self, run_id: str, *, lease_seconds: int) -> bool:
        lease = _now() + timedelta(seconds=lease_seconds)
        if not self._uses_lakebase:
            with self._lock:
                row = self._rows.get(run_id)
                if row is None or row.status != "queued":
                    return False
                self._rows[run_id] = row.model_copy(update={
                    "status": "running", "attempt_count": row.attempt_count + 1,
                    "started_at": row.started_at or _text(),
                    "lease_expires_at": _text(lease),
                })
                return True
        changed = lakebase_store.postgres.execute(
            f"""UPDATE {self._table()} SET status='running',
                attempt_count=attempt_count+1, started_at=COALESCE(started_at,NOW()),
                lease_expires_at=%s
                WHERE run_id=%s AND (status='queued' OR
                  (status='running' AND lease_expires_at < NOW()))""",
            (_text(lease), run_id),
        )
        return changed == 1

    def heartbeat(self, run_id: str, *, lease_seconds: int) -> bool:
        lease = _now() + timedelta(seconds=lease_seconds)
        if not self._uses_lakebase:
            with self._lock:
                row = self._rows.get(run_id)
                if row is None or row.status != "running":
                    return False
                self._rows[run_id] = row.model_copy(update={"lease_expires_at": _text(lease)})
                return True
        return lakebase_store.postgres.execute(
            f"UPDATE {self._table()} SET lease_expires_at=%s "
            "WHERE run_id=%s AND status='running'",
            (_text(lease), run_id),
        ) == 1

    def recoverable_ids(self, *, limit: int, max_attempts: int = 3) -> list[str]:
        if not self._uses_lakebase:
            with self._lock:
                return [
                    row.run_id for row in self._rows.values()
                    if (
                        row.status == "completion_pending"
                        or (row.status == "queued" and row.attempt_count < max_attempts)
                    )
                ][:limit]
        rows = lakebase_store.postgres.query(
            f"SELECT run_id FROM {self._table()} WHERE (status='completion_pending' OR status='queued' OR "
            "(status='running' AND lease_expires_at < NOW())) "
            "AND (status='completion_pending' OR attempt_count < %s) ORDER BY queued_at LIMIT %s",
            (max_attempts, limit),
        )
        return [str(row["run_id"]) for row in rows]

    def finish(
        self, run_id: str, status: str, *, diagnostics: dict[str, Any] | None = None,
        error_code: str | None = None, error_message: str | None = None,
        retryable: bool = False,
    ) -> None:
        completed_at = None if status == "completion_pending" else _text()
        updates = {
            "status": status, "completed_at": completed_at, "lease_expires_at": None,
            "diagnostics": (
                NetworkRunDiagnostics.model_validate(diagnostics) if diagnostics else None
            ), "error_code": error_code,
            "error_message": error_message, "retryable": retryable,
        }
        if not self._uses_lakebase:
            with self._lock:
                row = self._rows[run_id]
                self._rows[run_id] = row.model_copy(update=updates)
            return
        lakebase_store.postgres.execute(
            f"""UPDATE {self._table()} SET status=%s, completed_at=%s,
                lease_expires_at=NULL, diagnostics=%s, error_code=%s,
                error_message=%s, retryable=%s WHERE run_id=%s""",
            (
                status, updates["completed_at"],
                lakebase_store.postgres.jsonb(diagnostics) if diagnostics else None,
                error_code, error_message, retryable, run_id,
            ),
        )

    def cancel(self, run_id: str) -> NetworkRunRecord:
        row = self.get(run_id)
        if row.status not in {"queued", "running"}:
            return row
        self.finish(run_id, "cancelled", error_code="cancelled", error_message="Cancelled by user.")
        return self.get(run_id)


class NetworkRunManager:
    def __init__(self, repository: NetworkRunJobRepository | None = None) -> None:
        self.repository = repository or NetworkRunJobRepository()
        self.max_workers = max(1, int(os.getenv("NETWORK_RUN_MAX_WORKERS", "2")))
        self.max_queued = max(self.max_workers, int(os.getenv("NETWORK_RUN_MAX_QUEUED", "20")))
        self.lease_seconds = max(30, int(os.getenv("NETWORK_RUN_LEASE_SECONDS", "900")))
        self.max_attempts = max(1, int(os.getenv("NETWORK_RUN_MAX_ATTEMPTS", "3")))
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="network-run"
        )

    def launch(
        self,
        scenario: NetworkScenario,
        *,
        idempotency_key: str | None = None,
        run_kind: str = "scenario",
        parent_run_id: str | None = None,
        demand_change_ids: list[str] | None = None,
    ) -> NetworkRunRecord:
        record, created = self.repository.create(
            scenario, max_queued=self.max_queued, max_attempts=self.max_attempts,
            idempotency_key=idempotency_key,
            run_kind=run_kind,
            parent_run_id=parent_run_id,
            demand_change_ids=demand_change_ids,
        )
        if created:
            self._executor.submit(self._execute, record.run_id)
        return record

    def _execute(self, run_id: str) -> None:
        if not self.repository.claim(run_id, lease_seconds=self.lease_seconds):
            return
        record = self.repository.get(run_id)
        stop_heartbeat = threading.Event()

        def maintain_lease() -> None:
            while not stop_heartbeat.wait(max(10, self.lease_seconds // 3)):
                if not self.repository.heartbeat(
                    run_id, lease_seconds=self.lease_seconds
                ):
                    return

        heartbeat = threading.Thread(
            target=maintain_lease, name=f"network-heartbeat-{run_id}", daemon=True
        )
        heartbeat.start()
        try:
            from .network_scenarios import network_scenario_service

            response = network_scenario_service.run(
                record.scenario_id,
                run_id=run_id,
                expected_revision=record.revision,
            )
            diagnostics = (
                response.result.diagnostics.model_dump(mode="json")
                if response.result.diagnostics else None
            )
            if response.scenario.revision != record.revision:
                self.repository.finish(run_id, "stale", diagnostics=diagnostics)
                self._release_reassignment(record)
            else:
                try:
                    self._apply_completion(record)
                except Exception:
                    # The solve is already committed. Preserve a recoverable
                    # callback state instead of rerunning with the same run ID.
                    self.repository.finish(
                        run_id, "completion_pending", diagnostics=diagnostics,
                        error_code="completion_callback_failed",
                        error_message="Committed run is awaiting reassignment completion.",
                        retryable=True,
                    )
                    return
                self.repository.finish(run_id, "succeeded", diagnostics=diagnostics)
        except HTTPException as exc:
            if self.repository.get(run_id).status == "cancelled":
                return
            code = (
                "stale_revision"
                if exc.status_code == 409 and "revision" in str(exc.detail).lower()
                else "request_error"
            )
            status = "stale" if code == "stale_revision" else "failed"
            self.repository.finish(
                run_id, status, error_code=code, error_message=str(exc.detail), retryable=False
            )
            self._release_reassignment(record)
        except Exception as exc:  # durable error envelope; details remain in diagnostics/logs
            self.repository.finish(
                run_id, "failed", error_code=type(exc).__name__,
                error_message=str(exc)[:1000], retryable=True,
            )
            self._release_reassignment(record)
        finally:
            stop_heartbeat.set()

    def recover(self) -> int:
        run_ids = self.repository.recoverable_ids(
            limit=self.max_queued, max_attempts=self.max_attempts
        )
        for run_id in run_ids:
            record = self.repository.get(run_id)
            if record.status == "completion_pending":
                self._executor.submit(self._finish_completion, record)
            else:
                self._executor.submit(self._execute, run_id)
        return len(run_ids)

    @staticmethod
    def _apply_completion(record: NetworkRunRecord) -> None:
        if record.run_kind != "reassignment":
            return
        if not record.parent_run_id or not record.demand_change_ids:
            raise RuntimeError("Reassignment run is missing frozen completion metadata.")
        from .demand_changes import demand_change_service

        demand_change_service.repository.resolve(
            record.parent_run_id, record.run_id, set(record.demand_change_ids)
        )

    @staticmethod
    def _release_reassignment(record: NetworkRunRecord) -> None:
        if record.run_kind != "reassignment" or not record.parent_run_id:
            return
        from .demand_changes import demand_change_service

        demand_change_service.repository.release_claim(record.parent_run_id)

    def _finish_completion(self, record: NetworkRunRecord) -> None:
        try:
            self._apply_completion(record)
        except Exception:
            return
        self.repository.finish(
            record.run_id,
            "succeeded",
            diagnostics=(
                record.diagnostics.model_dump(mode="json")
                if record.diagnostics else None
            ),
        )

    def cancel(self, run_id: str) -> NetworkRunRecord:
        record = self.repository.cancel(run_id)
        if record.status == "cancelled":
            self._release_reassignment(record)
        return record


network_run_manager = NetworkRunManager()
