from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import HTTPException

from ..config import get_data_backend
from .lakebase_store import lakebase_store


DepotPlanRecord = dict[str, Any]
DepotPlanMutation = Callable[[DepotPlanRecord], None]


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _has_pending(record: DepotPlanRecord) -> bool:
    pending_statuses = {"queued", "running"}
    if str(record.get("status", "")) in pending_statuses:
        return True
    days = record.get("days", {})
    if isinstance(days, dict):
        day_records = days.values()
    elif isinstance(days, list):
        day_records = days
    else:
        day_records = []
    for day in day_records:
        if not isinstance(day, dict):
            continue
        if str(day.get("default_status", "")) in pending_statuses:
            return True
        if str(day.get("override_status", "")) in pending_statuses:
            return True
        override_statuses = day.get("override_statuses", {})
        if isinstance(override_statuses, dict) and any(
            str(status) in pending_statuses for status in override_statuses.values()
        ):
            return True
        jobs = day.get("jobs", {})
        if isinstance(jobs, dict) and any(
            isinstance(job, dict) and str(job.get("status", "")) in pending_statuses
            for job in jobs.values()
        ):
            return True
    return False


class DepotPlanRepository:
    def __init__(self) -> None:
        self._records: dict[str, DepotPlanRecord] = {}
        self._parent_index: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()

    @property
    def _uses_lakebase(self) -> bool:
        return get_data_backend() == "lakebase"

    def _table(self) -> str:
        return lakebase_store.postgres.qualified_table("depot_plan_sets")

    def _jobs_table(self) -> str:
        return lakebase_store.postgres.qualified_table("depot_plan_jobs")

    def _days_table(self) -> str:
        return lakebase_store.postgres.qualified_table("depot_plan_days")

    def _results_table(self) -> str:
        return lakebase_store.postgres.qualified_table("depot_plan_results")

    def _routes_table(self) -> str:
        return lakebase_store.postgres.qualified_table("depot_plan_routes")

    @staticmethod
    def _identity(record: DepotPlanRecord) -> tuple[str, str, str]:
        try:
            depot = record.get("depot")
            depot_id = record.get("depot_id")
            if depot_id is None and isinstance(depot, dict):
                depot_id = depot.get("depot_id")
            if not depot_id:
                raise KeyError("depot_id")
            return (
                str(record["plan_set_id"]),
                str(record["parent_run_id"]),
                str(depot_id),
            )
        except KeyError as exc:
            raise ValueError(
                "Depot plan records require plan_set_id, parent_run_id, and depot_id."
            ) from exc

    def find(self, parent_run_id: str, depot_id: str) -> DepotPlanRecord | None:
        if not self._uses_lakebase:
            with self._lock:
                plan_set_id = self._parent_index.get((parent_run_id, depot_id))
                record = self._records.get(plan_set_id) if plan_set_id else None
                return deepcopy(record) if record is not None else None
        row = lakebase_store.postgres.query_one(
            f"SELECT plan_set_id, payload FROM {self._table()} "
            "WHERE parent_run_id = %s AND depot_id = %s",
            (parent_run_id, depot_id),
        )
        return self.get(str(row["plan_set_id"])) if row is not None else None

    def create(self, record: DepotPlanRecord) -> DepotPlanRecord:
        from .demo_state_gate import demo_state_gate

        with demo_state_gate.admission():
            return self._create(record)

    def _create(self, record: DepotPlanRecord) -> DepotPlanRecord:
        plan_set_id, parent_run_id, depot_id = self._identity(record)
        detached = deepcopy(record)
        if not self._uses_lakebase:
            with self._lock:
                existing_id = self._parent_index.get((parent_run_id, depot_id))
                if existing_id is not None:
                    return deepcopy(self._records[existing_id])
                if plan_set_id in self._records:
                    raise ValueError(f"Depot plan {plan_set_id!r} already exists.")
                self._records[plan_set_id] = detached
                self._parent_index[(parent_run_id, depot_id)] = plan_set_id
                return deepcopy(detached)
        now = datetime.now(timezone.utc).isoformat()
        with lakebase_store.postgres.transaction() as connection:
            inserted = lakebase_store.postgres.query_one(
                f"""
                INSERT INTO {self._table()} (
                  plan_set_id, parent_run_id, depot_id, payload, has_pending,
                  created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (parent_run_id, depot_id) DO NOTHING
                RETURNING payload
                """,
                (
                    plan_set_id,
                    parent_run_id,
                    depot_id,
                    lakebase_store.postgres.jsonb(detached),
                    _has_pending(detached),
                    now,
                    now,
                ),
                connection=connection,
            )
            if inserted is not None:
                self._sync_normalized(detached, connection)
                return deepcopy(_json_value(inserted["payload"]))
            existing = lakebase_store.postgres.query_one(
                f"SELECT payload FROM {self._table()} "
                "WHERE parent_run_id = %s AND depot_id = %s",
                (parent_run_id, depot_id),
                connection=connection,
            )
            if existing is None:
                raise RuntimeError("Concurrent depot plan creation did not persist a row.")
            return deepcopy(_json_value(existing["payload"]))

    def get(self, plan_set_id: str) -> DepotPlanRecord:
        if not self._uses_lakebase:
            with self._lock:
                record = self._records.get(plan_set_id)
                if record is None:
                    raise HTTPException(status_code=404, detail="Depot plan not found.")
                return deepcopy(record)
        row = lakebase_store.postgres.query_one(
            f"SELECT payload FROM {self._table()} WHERE plan_set_id = %s",
            (plan_set_id,),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Depot plan not found.")
        record = deepcopy(_json_value(row["payload"]))
        day_rows = lakebase_store.postgres.query(
            f"SELECT service_date, payload FROM {self._days_table()} "
            "WHERE plan_set_id = %s ORDER BY service_date",
            (plan_set_id,),
        )
        if day_rows:
            record["days"] = {
                str(day_row["service_date"]): deepcopy(_json_value(day_row["payload"]))
                for day_row in day_rows
            }
            self._hydrate_selected_results(plan_set_id, record["days"])
        return record

    def _hydrate_selected_results(
        self, plan_set_id: str, days: dict[str, DepotPlanRecord]
    ) -> None:
        selected_ids = {
            str(result_id)
            for day in days.values()
            for result_id in [
                day.get("default_result_id"),
                *list(day.get("selected_result_ids", {}).values()),
            ]
            if result_id
        }
        if not selected_ids:
            return
        result_rows = lakebase_store.postgres.query(
            f"SELECT result_id, service_date, payload FROM {self._results_table()} "
            "WHERE plan_set_id = %s AND result_id = ANY(%s)",
            (plan_set_id, list(selected_ids)),
        )
        route_rows = lakebase_store.postgres.query(
            f"SELECT result_id, payload FROM {self._routes_table()} "
            "WHERE plan_set_id = %s AND result_id = ANY(%s) "
            "ORDER BY result_id, route_position, route_id",
            (plan_set_id, list(selected_ids)),
        )
        routes_by_result: dict[str, list[dict[str, object]]] = {}
        for route_row in route_rows:
            routes_by_result.setdefault(str(route_row["result_id"]), []).append(
                deepcopy(_json_value(route_row["payload"]))
            )
        for result_row in result_rows:
            result_id = str(result_row["result_id"])
            service_date = str(result_row["service_date"])
            if service_date not in days:
                continue
            result = deepcopy(_json_value(result_row["payload"]))
            result.pop("route_count", None)
            result["routes"] = routes_by_result.get(result_id, [])
            days[service_date].setdefault("results", {})[result_id] = result

    def mutate_day(
        self,
        plan_set_id: str,
        service_date: str,
        callback: Callable[[DepotPlanRecord], None],
    ) -> DepotPlanRecord:
        """Mutate one authoritative day row without locking the whole plan document."""
        if not self._uses_lakebase:
            with self._lock:
                record = self._records.get(plan_set_id)
                if record is None:
                    raise HTTPException(status_code=404, detail="Depot plan not found.")
                day = record.get("days", {}).get(service_date)
                if not isinstance(day, dict):
                    raise KeyError(f"Service date {service_date} is outside the plan horizon.")
                callback(day)
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                return deepcopy(record)
        with lakebase_store.postgres.transaction() as connection:
            row = lakebase_store.postgres.query_one(
                f"SELECT payload FROM {self._days_table()} "
                "WHERE plan_set_id = %s AND service_date = %s FOR UPDATE",
                (plan_set_id, service_date),
                connection=connection,
            )
            if row is None:
                legacy = lakebase_store.postgres.query_one(
                    f"SELECT payload FROM {self._table()} WHERE plan_set_id = %s",
                    (plan_set_id,),
                    connection=connection,
                )
                if legacy is None:
                    raise HTTPException(status_code=404, detail="Depot plan not found.")
                legacy_record = deepcopy(_json_value(legacy["payload"]))
                legacy_day = legacy_record.get("days", {}).get(service_date)
                if not isinstance(legacy_day, dict):
                    raise KeyError(f"Service date {service_date} is outside the plan horizon.")
                self._sync_normalized(legacy_record, connection)
                day = deepcopy(legacy_day)
            else:
                day = deepcopy(_json_value(row["payload"]))
            callback(day)
            self._sync_normalized(
                {"plan_set_id": plan_set_id, "days": {service_date: day}},
                connection,
            )
        return self.get(plan_set_id)

    def mutate(
        self, plan_set_id: str, callback: DepotPlanMutation
    ) -> DepotPlanRecord:
        if not self._uses_lakebase:
            with self._lock:
                record = self._records.get(plan_set_id)
                if record is None:
                    raise HTTPException(status_code=404, detail="Depot plan not found.")
                callback(record)
                return deepcopy(record)
        with lakebase_store.postgres.transaction() as connection:
            row = lakebase_store.postgres.query_one(
                f"SELECT payload FROM {self._table()} "
                "WHERE plan_set_id = %s FOR UPDATE",
                (plan_set_id,),
                connection=connection,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Depot plan not found.")
            record = deepcopy(_json_value(row["payload"]))
            authoritative_days = lakebase_store.postgres.query(
                f"SELECT service_date, payload FROM {self._days_table()} WHERE plan_set_id = %s",
                (plan_set_id,),
                connection=connection,
            )
            if authoritative_days:
                record["days"] = {
                    str(day_row["service_date"]): deepcopy(_json_value(day_row["payload"]))
                    for day_row in authoritative_days
                }
            callback(record)
            lakebase_store.postgres.execute(
                f"UPDATE {self._table()} "
                "SET payload = %s, has_pending = %s, updated_at = %s "
                "WHERE plan_set_id = %s",
                (
                    lakebase_store.postgres.jsonb(record),
                    _has_pending(record),
                    datetime.now(timezone.utc).isoformat(),
                    plan_set_id,
                ),
                connection=connection,
            )
            self._sync_normalized(record, connection)
            return deepcopy(record)

    def list_pending(self) -> list[DepotPlanRecord]:
        if not self._uses_lakebase:
            with self._lock:
                return [
                    deepcopy(record)
                    for record in self._records.values()
                    if _has_pending(record)
                ]
        rows = lakebase_store.postgres.query(
            f"""
            SELECT DISTINCT plans.plan_set_id
              FROM {self._table()} plans
              LEFT JOIN {self._jobs_table()} jobs
                ON jobs.plan_set_id = plans.plan_set_id
             WHERE jobs.status IN ('queued', 'running')
                OR (plans.has_pending = TRUE AND NOT EXISTS (
                    SELECT 1 FROM {self._jobs_table()} existing
                     WHERE existing.plan_set_id = plans.plan_set_id
                ))
             ORDER BY plans.plan_set_id
            """
        )
        return [self.get(str(row["plan_set_id"])) for row in rows]

    def clear_all(self) -> int:
        """Delete all plan state only when no queued/running plan can write back."""
        if not self._uses_lakebase:
            with self._lock:
                if any(_has_pending(record) for record in self._records.values()):
                    raise HTTPException(status_code=409, detail="Wait for active depot plans before resetting the demo.")
                count = len(self._records)
                self._records.clear()
                self._parent_index.clear()
                return count
        with lakebase_store.postgres.transaction() as connection:
            active = lakebase_store.postgres.query_one(
                f"SELECT COUNT(*) AS count FROM {self._jobs_table()} "
                "WHERE status IN ('queued','running')",
                connection=connection,
            )
            if int((active or {}).get("count", 0)):
                raise HTTPException(status_code=409, detail="Wait for active depot plans before resetting the demo.")
            count = lakebase_store.postgres.query_one(
                f"SELECT COUNT(*) AS count FROM {self._table()}", connection=connection
            )
            lakebase_store.postgres.execute(f"DELETE FROM {self._table()}", connection=connection)
        return int((count or {}).get("count", 0))

    def has_active(self) -> bool:
        if not self._uses_lakebase:
            with self._lock:
                return any(_has_pending(record) for record in self._records.values())
        row = lakebase_store.postgres.query_one(
            f"SELECT 1 AS active FROM {self._jobs_table()} "
            "WHERE status IN ('queued','running') LIMIT 1"
        )
        return row is not None

    def list_results(
        self,
        plan_set_id: str,
        service_date: str,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, object]:
        limit = min(max(int(limit), 1), 100)
        offset = max(int(offset), 0)
        if not self._uses_lakebase:
            record = self.get(plan_set_id)
            day = record.get("days", {}).get(service_date)
            if not isinstance(day, dict):
                raise KeyError(f"Service date {service_date} is outside the plan horizon.")
            values = sorted(
                (
                    {
                        **{key: value for key, value in result.items() if key != "routes"},
                        "route_count": len(result.get("routes", [])),
                    }
                    for result in day.get("results", {}).values()
                ),
                key=lambda result: str(result.get("created_at", "")),
                reverse=True,
            )
            return {"items": deepcopy(values[offset:offset + limit]), "total": len(values), "limit": limit, "offset": offset}
        day_exists = lakebase_store.postgres.query_one(
            f"SELECT 1 AS present FROM {self._days_table()} "
            "WHERE plan_set_id = %s AND service_date = %s",
            (plan_set_id, service_date),
        )
        if day_exists is None:
            raise KeyError(f"Service date {service_date} is outside the plan horizon.")
        count = lakebase_store.postgres.query_one(
            f"SELECT COUNT(*) AS total FROM {self._results_table()} "
            "WHERE plan_set_id = %s AND service_date = %s",
            (plan_set_id, service_date),
        )
        rows = lakebase_store.postgres.query(
            f"SELECT payload FROM {self._results_table()} "
            "WHERE plan_set_id = %s AND service_date = %s "
            "ORDER BY created_at DESC, result_id LIMIT %s OFFSET %s",
            (plan_set_id, service_date, limit, offset),
        )
        return {
            "items": [deepcopy(_json_value(row["payload"])) for row in rows],
            "total": int((count or {}).get("total", 0)),
            "limit": limit,
            "offset": offset,
        }

    def list_result_routes(
        self,
        plan_set_id: str,
        result_id: str,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, object]:
        limit = min(max(int(limit), 1), 100)
        offset = max(int(offset), 0)
        if not self._uses_lakebase:
            record = self.get(plan_set_id)
            result = next(
                (
                    result
                    for day in record.get("days", {}).values()
                    for candidate_id, result in day.get("results", {}).items()
                    if str(candidate_id) == result_id
                ),
                None,
            )
            if result is None:
                raise KeyError(f"Unknown depot result {result_id!r}.")
            routes = list(result.get("routes", []))
            return {"items": deepcopy(routes[offset:offset + limit]), "total": len(routes), "limit": limit, "offset": offset}
        result_exists = lakebase_store.postgres.query_one(
            f"SELECT 1 AS present FROM {self._results_table()} "
            "WHERE plan_set_id = %s AND result_id = %s",
            (plan_set_id, result_id),
        )
        if result_exists is None:
            raise KeyError(f"Unknown depot result {result_id!r}.")
        count = lakebase_store.postgres.query_one(
            f"SELECT COUNT(*) AS total FROM {self._routes_table()} "
            "WHERE plan_set_id = %s AND result_id = %s",
            (plan_set_id, result_id),
        )
        rows = lakebase_store.postgres.query(
            f"SELECT payload FROM {self._routes_table()} "
            "WHERE plan_set_id = %s AND result_id = %s "
            "ORDER BY route_position, route_id LIMIT %s OFFSET %s",
            (plan_set_id, result_id, limit, offset),
        )
        return {
            "items": [deepcopy(_json_value(row["payload"])) for row in rows],
            "total": int((count or {}).get("total", 0)),
            "limit": limit,
            "offset": offset,
        }

    def claim_job(
        self,
        plan_set_id: str,
        service_date: str,
        job_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 600,
        max_attempts: int = 3,
    ) -> int | None:
        """Atomically lease a queued or abandoned job; return the new attempt number."""
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=lease_seconds)
        if not self._uses_lakebase:
            with self._lock:
                record = self._records.get(plan_set_id)
                if record is None:
                    raise HTTPException(status_code=404, detail="Depot plan not found.")
                day = record.get("days", {}).get(service_date)
                job = day.get("jobs", {}).get(job_id) if isinstance(day, dict) else None
                if not isinstance(job, dict):
                    return None
                lease = job.get("lease_expires_at")
                lease_time = datetime.fromisoformat(str(lease).replace("Z", "+00:00")) if lease else None
                retry = job.get("retry_at")
                retry_time = datetime.fromisoformat(str(retry).replace("Z", "+00:00")) if retry else None
                claimable = (
                    job.get("status") == "queued"
                    and (retry_time is None or retry_time <= now)
                ) or (
                    job.get("status") == "running" and lease_time is not None and lease_time <= now
                )
                attempts = int(job.get("attempt_count", 0))
                if not claimable or attempts >= max_attempts:
                    return None
                attempts += 1
                job.update({
                    "status": "running",
                    "attempt_count": attempts,
                    "worker_id": worker_id,
                    "lease_expires_at": lease_expires.isoformat(),
                })
                return attempts
        existing_job = lakebase_store.postgres.query_one(
            f"SELECT 1 AS present FROM {self._jobs_table()} WHERE plan_set_id = %s AND job_id = %s",
            (plan_set_id, job_id),
        )
        if existing_job is None:
            # Backfill legacy monolithic plans lazily before their first durable claim.
            with lakebase_store.postgres.transaction() as connection:
                legacy = lakebase_store.postgres.query_one(
                    f"SELECT payload FROM {self._table()} WHERE plan_set_id = %s FOR UPDATE",
                    (plan_set_id,),
                    connection=connection,
                )
                if legacy is not None:
                    self._sync_normalized(
                        deepcopy(_json_value(legacy["payload"])), connection
                    )
        row = lakebase_store.postgres.query_one(
            f"""
            UPDATE {self._jobs_table()}
               SET status = 'running', attempt_count = attempt_count + 1,
                   worker_id = %s, lease_expires_at = %s, updated_at = %s
             WHERE plan_set_id = %s AND service_date = %s AND job_id = %s
               AND attempt_count < %s
               AND (
                 (status = 'queued' AND (retry_at IS NULL OR retry_at <= %s))
                 OR (status = 'running' AND lease_expires_at <= %s)
               )
            RETURNING attempt_count
            """,
            (
                worker_id, lease_expires, now, plan_set_id, service_date, job_id,
                max_attempts, now, now,
            ),
        )
        return int(row["attempt_count"]) if row is not None else None

    def heartbeat_job(
        self,
        plan_set_id: str,
        job_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 600,
    ) -> bool:
        lease_expires = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        if not self._uses_lakebase:
            with self._lock:
                record = self._records.get(plan_set_id)
                if record is None:
                    return False
                for day in record.get("days", {}).values():
                    job = day.get("jobs", {}).get(job_id)
                    if isinstance(job, dict) and job.get("status") == "running" and job.get("worker_id") == worker_id:
                        job["lease_expires_at"] = lease_expires.isoformat()
                        return True
                return False
        row = lakebase_store.postgres.query_one(
            f"""
            UPDATE {self._jobs_table()}
               SET lease_expires_at = %s, updated_at = %s
             WHERE plan_set_id = %s AND job_id = %s
               AND status = 'running' AND worker_id = %s
            RETURNING job_id
            """,
            (
                lease_expires, datetime.now(timezone.utc), plan_set_id, job_id,
                worker_id,
            ),
        )
        return row is not None

    def _sync_normalized(self, record: DepotPlanRecord, connection: Any) -> None:
        """Dual-write normalized depot rows while legacy payload reads remain supported."""
        plan_set_id = str(record["plan_set_id"])
        for service_date, day in record.get("days", {}).items():
            day_state = deepcopy(day)
            day_state["results"] = {}
            lakebase_store.postgres.execute(
                f"""
                INSERT INTO {self._days_table()}
                    (plan_set_id, service_date, default_status, assigned_cases, payload, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (plan_set_id, service_date) DO UPDATE SET
                    default_status = EXCLUDED.default_status,
                    assigned_cases = EXCLUDED.assigned_cases,
                    payload = EXCLUDED.payload,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    plan_set_id, service_date, str(day["default_status"]),
                    int(day["assigned_cases"]), lakebase_store.postgres.jsonb(day_state),
                    datetime.now(timezone.utc),
                ),
                connection=connection,
            )
            result_scenarios: dict[str, str] = {}
            for candidate_job_id, job in day.get("jobs", {}).items():
                scenario_id = str(job["route_scenario_id"])
                result_id = job.get("result_id")
                if result_id:
                    result_scenarios[str(result_id)] = scenario_id
                lakebase_store.postgres.execute(
                    f"""
                    INSERT INTO {self._jobs_table()} (
                        job_id, plan_set_id, service_date, route_scenario_id,
                        idempotency_key, status, request_payload, result_id,
                        attempt_count, worker_id, lease_expires_at, retry_at,
                        error_message, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (plan_set_id, job_id) DO UPDATE SET
                        status = CASE
                            WHEN {self._jobs_table()}.status = 'running'
                             AND {self._jobs_table()}.lease_expires_at > CURRENT_TIMESTAMP
                             AND EXCLUDED.attempt_count < {self._jobs_table()}.attempt_count
                            THEN {self._jobs_table()}.status ELSE EXCLUDED.status END,
                        request_payload = EXCLUDED.request_payload,
                        result_id = EXCLUDED.result_id,
                        attempt_count = GREATEST({self._jobs_table()}.attempt_count, EXCLUDED.attempt_count),
                        worker_id = CASE
                            WHEN EXCLUDED.attempt_count >= {self._jobs_table()}.attempt_count
                            THEN EXCLUDED.worker_id ELSE {self._jobs_table()}.worker_id END,
                        lease_expires_at = CASE
                            WHEN EXCLUDED.attempt_count >= {self._jobs_table()}.attempt_count
                            THEN EXCLUDED.lease_expires_at ELSE {self._jobs_table()}.lease_expires_at END,
                        retry_at = EXCLUDED.retry_at,
                        error_message = EXCLUDED.error_message, updated_at = EXCLUDED.updated_at
                    """,
                    (
                        str(candidate_job_id), plan_set_id, service_date, scenario_id,
                        f"{plan_set_id}:{service_date}:{scenario_id}:{candidate_job_id}",
                        str(job["status"]), lakebase_store.postgres.jsonb(job.get("request")),
                        result_id, int(job.get("attempt_count", 0)), job.get("worker_id"),
                        job.get("lease_expires_at"), job.get("retry_at"), job.get("error"),
                        datetime.now(timezone.utc),
                    ),
                    connection=connection,
                )
            for result_id, result in day.get("results", {}).items():
                result_summary = {
                    key: value for key, value in result.items() if key != "routes"
                }
                result_summary["route_count"] = len(result.get("routes", []))
                lakebase_store.postgres.execute(
                    f"""
                    INSERT INTO {self._results_table()}
                        (result_id, plan_set_id, service_date, route_scenario_id, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (result_id) DO NOTHING
                    """,
                    (
                        result_id, plan_set_id, service_date,
                        result_scenarios.get(str(result_id), "default"),
                        lakebase_store.postgres.jsonb(result_summary), result.get("created_at"),
                    ),
                    connection=connection,
                )
                for position, route in enumerate(result.get("routes", [])):
                    lakebase_store.postgres.execute(
                        f"""
                        INSERT INTO {self._routes_table()} (
                            result_id, route_id, plan_set_id, service_date,
                            route_position, payload
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (result_id, route_id) DO UPDATE SET
                            route_position = EXCLUDED.route_position,
                            payload = EXCLUDED.payload
                        """,
                        (
                            result_id, str(route["route_id"]), plan_set_id,
                            service_date, position,
                            lakebase_store.postgres.jsonb(route),
                        ),
                        connection=connection,
                    )


depot_plan_repository = DepotPlanRepository()
