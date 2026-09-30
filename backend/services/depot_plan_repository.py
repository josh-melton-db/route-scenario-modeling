from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
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
            f"SELECT payload FROM {self._table()} "
            "WHERE parent_run_id = %s AND depot_id = %s",
            (parent_run_id, depot_id),
        )
        return deepcopy(_json_value(row["payload"])) if row is not None else None

    def create(self, record: DepotPlanRecord) -> DepotPlanRecord:
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
        return deepcopy(_json_value(row["payload"]))

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
            f"SELECT payload FROM {self._table()} "
            "WHERE has_pending = TRUE ORDER BY created_at"
        )
        return [deepcopy(_json_value(row["payload"])) for row in rows]


depot_plan_repository = DepotPlanRepository()
