from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException

from ..config import get_data_backend
from ..models import NetworkDemandChange, NetworkDemandChangeCreateRequest, NetworkReleaseTarget
from .depot_plan_repository import depot_plan_repository
from .lakebase_store import lakebase_store


class DemandChangeRepository:
    """Immutable request log. Resolutions update status, never source snapshots."""

    def __init__(self) -> None:
        self._rows: dict[str, NetworkDemandChange] = {}
        self._claimed_runs: dict[str, set[str]] = {}
        self._lock = threading.RLock()

    @property
    def _uses_lakebase(self) -> bool:
        return get_data_backend() == "lakebase"

    def _table(self) -> str:
        return lakebase_store.postgres.qualified_table("network_demand_changes")

    def _ensure_table(self) -> None:
        lakebase_store.postgres.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._table()} (
              change_id TEXT PRIMARY KEY, parent_run_id TEXT NOT NULL,
              depot_plan_id TEXT NOT NULL, route_scenario_id TEXT NOT NULL,
              depot_id TEXT NOT NULL, service_date DATE NOT NULL,
              customer_id TEXT NOT NULL, cases INTEGER NOT NULL CHECK (cases > 0),
              kind TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
              resolved_run_id TEXT, processing_started_at TIMESTAMPTZ,
              UNIQUE (parent_run_id, depot_id, service_date, customer_id)
            )
        """)
        lakebase_store.postgres.execute(f"ALTER TABLE {self._table()} ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ")

    def recover_stale_claims(self, max_age_minutes: int = 15) -> int:
        if not self._uses_lakebase:
            return 0
        self._ensure_table()
        return int(lakebase_store.postgres.execute(f"UPDATE {self._table()} SET status = 'pending', processing_started_at = NULL WHERE status = 'processing' AND processing_started_at < NOW() - (%s * INTERVAL '1 minute')", (max_age_minutes,)) or 0)

    def list(self, run_id: str) -> list[NetworkDemandChange]:
        if self._uses_lakebase:
            self._ensure_table()
            rows = lakebase_store.postgres.query(
                f"SELECT * FROM {self._table()} WHERE parent_run_id = %s ORDER BY created_at",
                (run_id,),
            )
            return [NetworkDemandChange.model_validate({**{k: v for k, v in r.items() if k != "processing_started_at"}, "service_date": str(r["service_date"]), "created_at": str(r["created_at"]), "status": "pending" if r["status"] == "processing" else r["status"]}) for r in rows]
        with self._lock:
            return [r.model_copy(deep=True) for r in self._rows.values() if r.parent_run_id == run_id]

    def create(self, row: NetworkDemandChange) -> NetworkDemandChange:
        if self._uses_lakebase:
            self._ensure_table()
            try:
                with lakebase_store.postgres.transaction() as connection:
                    lakebase_store.postgres.query_one("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (row.parent_run_id,), connection=connection)
                    claimed = lakebase_store.postgres.query_one(f"SELECT change_id FROM {self._table()} WHERE parent_run_id = %s AND status = 'processing' LIMIT 1", (row.parent_run_id,), connection=connection)
                    if claimed is not None:
                        raise HTTPException(status_code=409, detail="Reassignment is already running for this run.")
                    lakebase_store.postgres.execute(
                    f"INSERT INTO {self._table()} (change_id,parent_run_id,depot_plan_id,route_scenario_id,depot_id,service_date,customer_id,cases,kind,status,created_at,resolved_run_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (row.change_id,row.parent_run_id,row.depot_plan_id,row.route_scenario_id,row.depot_id,row.service_date,row.customer_id,row.cases,row.kind,row.status,row.created_at,row.resolved_run_id),
                    connection=connection)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=409, detail="A release already exists for this customer/date/depot.") from exc
            return row.model_copy(deep=True)
        with self._lock:
            if row.parent_run_id in self._claimed_runs:
                raise HTTPException(status_code=409, detail="Reassignment is already running for this run.")
            if any(r.parent_run_id == row.parent_run_id and r.depot_id == row.depot_id and r.service_date == row.service_date and r.customer_id == row.customer_id for r in self._rows.values()):
                raise HTTPException(status_code=409, detail="A release already exists for this customer/date/depot.")
            self._rows[row.change_id] = row.model_copy(deep=True)
        return row.model_copy(deep=True)

    def resolve(self, run_id: str, resolved_run_id: str, change_ids: set[str]) -> None:
        if self._uses_lakebase:
            self._ensure_table()
            with lakebase_store.postgres.transaction() as connection:
                lakebase_store.postgres.query_one("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (run_id,), connection=connection)
                lakebase_store.postgres.execute(f"UPDATE {self._table()} SET status = 'resolved', resolved_run_id = %s, processing_started_at = NULL WHERE parent_run_id = %s AND status = 'processing' AND change_id = ANY(%s)", (resolved_run_id, run_id, list(change_ids)), connection=connection)
            return
        with self._lock:
            for key, row in list(self._rows.items()):
                if key in change_ids and row.parent_run_id == run_id and row.status == "pending":
                    self._rows[key] = row.model_copy(update={"status": "resolved", "resolved_run_id": resolved_run_id})
            self._claimed_runs.pop(run_id, None)

    def claim(self, run_id: str) -> list[NetworkDemandChange]:
        if self._uses_lakebase:
            self._ensure_table()
            with lakebase_store.postgres.transaction() as connection:
                lakebase_store.postgres.query_one("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (run_id,), connection=connection)
                lakebase_store.postgres.execute(f"UPDATE {self._table()} SET status = 'pending', processing_started_at = NULL WHERE parent_run_id = %s AND status = 'processing' AND processing_started_at < NOW() - INTERVAL '15 minutes'", (run_id,), connection=connection)
                rows = lakebase_store.postgres.query(f"SELECT * FROM {self._table()} WHERE parent_run_id = %s AND status = 'pending' FOR UPDATE", (run_id,), connection=connection)
                if not rows:
                    raise HTTPException(status_code=409, detail="No pending demand changes exist for this run.")
                lakebase_store.postgres.execute(f"UPDATE {self._table()} SET status = 'processing', processing_started_at = NOW() WHERE parent_run_id = %s AND status = 'pending'", (run_id,), connection=connection)
            return [NetworkDemandChange.model_validate({**{k: v for k, v in r.items() if k != "processing_started_at"}, "service_date": str(r["service_date"]), "created_at": str(r["created_at"])}) for r in rows]
        with self._lock:
            if run_id in self._claimed_runs:
                raise HTTPException(status_code=409, detail="Reassignment is already running for this run.")
            rows = [r.model_copy(deep=True) for r in self._rows.values() if r.parent_run_id == run_id and r.status == "pending"]
            if not rows:
                raise HTTPException(status_code=409, detail="No pending demand changes exist for this run.")
            self._claimed_runs[run_id] = {row.change_id for row in rows}
            return rows

    def release_claim(self, run_id: str) -> None:
        if self._uses_lakebase:
            self._ensure_table()
            with lakebase_store.postgres.transaction() as connection:
                lakebase_store.postgres.query_one("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (run_id,), connection=connection)
                lakebase_store.postgres.execute(f"UPDATE {self._table()} SET status = 'pending', processing_started_at = NULL WHERE parent_run_id = %s AND status = 'processing'", (run_id,), connection=connection)
            return
        with self._lock:
            self._claimed_runs.pop(run_id, None)


class DemandChangeService:
    def __init__(self, repository: DemandChangeRepository | None = None) -> None:
        self.repository = repository or DemandChangeRepository()

    def list(self, run_id: str) -> list[NetworkDemandChange]:
        from .network_scenarios import network_scenario_service
        network_scenario_service.get_run_snapshot(run_id)
        return self.repository.list(run_id)

    def has_pending(self, run_id: str) -> bool:
        return any(row.status == "pending" for row in self.repository.list(run_id))

    def release_targets(self, run_id: str, depot_id: str, service_date: str) -> list[NetworkReleaseTarget]:
        from route_opt.depot_planning import materialize_depot_targets
        from .network_scenarios import network_scenario_service
        snapshot = network_scenario_service.get_run_snapshot(run_id)
        if not snapshot.scenario.horizon_start <= service_date <= snapshot.scenario.horizon_end:
            raise HTTPException(status_code=422, detail="Service date is outside the parent run horizon.")
        try:
            targets = materialize_depot_targets(snapshot.network_rows, snapshot.flow_rows, depot_id, service_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        names = {str(r["customer_id"]): str(r.get("customer_name") or r["customer_id"]) for r in targets["planning_customers"]}
        return [NetworkReleaseTarget(customer_id=str(r["customer_id"]), customer_name=names[str(r["customer_id"])], assigned_cases=int(r["demand_cases"])) for r in targets["orders"]]

    def create(self, run_id: str, request: NetworkDemandChangeCreateRequest) -> NetworkDemandChange:
        from .network_scenarios import network_scenario_service
        snapshot = network_scenario_service.get_run_snapshot(run_id)
        try:
            service_date = date.fromisoformat(request.service_date).isoformat()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="service_date must use YYYY-MM-DD.") from exc
        if not snapshot.scenario.horizon_start <= service_date <= snapshot.scenario.horizon_end:
            raise HTTPException(status_code=422, detail="Release date is outside the parent run horizon.")
        plan = depot_plan_repository.get(request.depot_plan_id)
        depot = plan.get("depot", {})
        depot_id = str(depot.get("depot_id") if isinstance(depot, dict) else plan.get("depot_id", ""))
        if str(plan.get("parent_run_id")) != run_id:
            raise HTTPException(status_code=409, detail="Depot plan does not belong to the parent run.")
        scenarios = plan.get("scenarios", {})
        if request.route_scenario_id == "default" or request.route_scenario_id not in scenarios:
            raise HTTPException(status_code=422, detail="A named route scenario from the depot plan is required.")
        days = plan.get("days", {})
        if service_date not in days:
            raise HTTPException(status_code=409, detail="Service date does not belong to the depot plan.")
        lanes = {str(r["lane_id"]): r for r in snapshot.network_rows["dim_network_lanes"]}
        assigned = sum(int(r.get("assigned_units", 0)) for r in snapshot.flow_rows if str(r.get("service_date"))[:10] == service_date and str(r.get("lane_type")) == "DELIVERY" and str((lanes.get(str(r.get("lane_id"))) or {}).get("origin_endpoint_id")) == depot_id and str((lanes.get(str(r.get("lane_id"))) or {}).get("destination_endpoint_id")) == request.customer_id)
        if assigned <= 0:
            raise HTTPException(status_code=409, detail="Customer/date is not assigned to this depot in the parent run.")
        existing = [r for r in self.repository.list(run_id) if r.status == "pending" and r.depot_id == depot_id and r.service_date == service_date and r.customer_id == request.customer_id]
        if existing:
            raise HTTPException(status_code=409, detail="A pending release already exists for this customer/date/depot.")
        if request.cases > assigned:
            raise HTTPException(status_code=422, detail=f"Release exceeds the {assigned} assigned cases.")
        return self.repository.create(NetworkDemandChange(change_id=f"NDC_{uuid.uuid4().hex[:12].upper()}", parent_run_id=run_id, depot_plan_id=request.depot_plan_id, route_scenario_id=request.route_scenario_id, depot_id=depot_id, service_date=service_date, customer_id=request.customer_id, cases=request.cases, created_at=datetime.now(timezone.utc).isoformat()))

    def reassign(self, run_id: str):
        self.repository.recover_stale_claims()
        pending = self.repository.claim(run_id)
        from .network_scenarios import network_scenario_service
        from .network_run_jobs import network_run_manager
        try:
            scenario, key = network_scenario_service.prepare_reassignment(
                run_id, pending
            )
            return network_run_manager.launch(
                scenario,
                idempotency_key=key,
                run_kind="reassignment",
                parent_run_id=run_id,
                demand_change_ids=[row.change_id for row in pending],
            )
        except Exception:
            self.repository.release_claim(run_id)
            raise


demand_change_service = DemandChangeService()
