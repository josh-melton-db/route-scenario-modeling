from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..config import get_data_backend
from .baseline_service import baseline_service
from .demand_changes import demand_change_service
from .demo_state_gate import demo_state_gate
from .depot_plan_repository import depot_plan_repository
from .network_run_jobs import network_run_manager
from .network_scenarios import network_scenario_service
from .lakebase_seed import LakebaseSeedService
from .lakebase_store import lakebase_store
from .solver_warmup import solver_warmup_service
from .sql import get_workspace_client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enum_text(value: object) -> str:
    return str(getattr(value, "value", value or "")).upper()


class DemoResetService:
    """Coordinates reset, optional UC bootstrap, and endpoint warm-up."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status_lock = threading.RLock()
        self._status: dict[str, Any] = {
            "state": "not_started", "started_at": None, "completed_at": None,
            "error": None, "bootstrap_run_id": None,
        }

    def status(self) -> dict[str, Any]:
        with self._status_lock:
            return dict(self._status)

    def reset(self) -> dict[str, object]:
        if not self._lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="A demo reset is already running.")
        try:
            demo_state_gate.begin_reset()
        except Exception:
            self._lock.release()
            raise
        delegated = False
        try:
            if (
                network_run_manager.repository.has_active()
                or depot_plan_repository.has_active()
                or self._route_preparation_running()
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Wait for active network runs and depot plans before resetting the demo.",
                )
            self._set_status(
                state="resetting", started_at=_now(), completed_at=None,
                error=None, bootstrap_run_id=None, lakebase_seeded=None,
                lakebase_reference_counts=None,
            )
            if get_data_backend() == "lakebase":
                # Always run the idempotent seed path. Reference tables may be
                # populated while a required published rate book is missing.
                self._set_status(state="seeding_lakebase")
                threading.Thread(
                    target=self._seed_then_continue,
                    name="demo-reset-lakebase-seed", daemon=True,
                ).start()
                delegated = True
                return self._response()
            threading.Thread(
                target=self._canonical_then_complete,
                name="demo-reset-canonical-snapshot", daemon=True,
            ).start()
            delegated = True
            return self._response()
        except Exception as exc:
            self._set_status(
                state="failed", completed_at=_now(),
                error=f"{type(exc).__name__}: {str(exc)[:500]}",
            )
            raise
        finally:
            if not delegated:
                demo_state_gate.end_reset()
                self._lock.release()

    @staticmethod
    def _route_preparation_running() -> bool:
        from .depot_route_preparation import depot_route_preparation_manager
        return depot_route_preparation_manager.is_running()

    def _canonical_then_complete(self) -> None:
        try:
            try:
                canonical = baseline_service.canonical_revision()
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                job_id = os.getenv("DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID", "").strip()
                if not job_id:
                    raise RuntimeError(
                        f"{exc.detail} DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID is not configured."
                    ) from exc
                self._set_status(state="bootstrapping")
                canonical = self._run_bootstrap(job_id)
            self._complete(canonical)
        except Exception as exc:
            self._set_status(
                state="failed", completed_at=_now(),
                error=f"{type(exc).__name__}: {str(exc)[:500]}",
            )
        finally:
            demo_state_gate.end_reset()
            self._lock.release()

    def _seed_then_continue(self) -> None:
        try:
            seeder = LakebaseSeedService(lakebase_store.postgres)
            report = seeder.ensure_synthetic_seeded()
            if report is not None:
                self._set_status(
                    lakebase_seeded=True,
                    lakebase_reference_counts=report.persisted_counts,
                )
                from .solver import solver_service

                solver_service.invalidate_base_cache()
            else:
                self._set_status(
                    lakebase_seeded=False,
                    lakebase_reference_counts=seeder.reference_counts(),
                )
            try:
                canonical = baseline_service.canonical_revision()
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                job_id = os.getenv("DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID", "").strip()
                if not job_id:
                    raise RuntimeError(
                        f"{exc.detail} DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID is not configured."
                    ) from exc
                self._set_status(state="bootstrapping")
                canonical = self._run_bootstrap(job_id)
            self._complete(canonical)
        except Exception as exc:
            self._set_status(
                state="failed", completed_at=_now(),
                error=f"{type(exc).__name__}: {str(exc)[:500]}",
            )
        finally:
            demo_state_gate.end_reset()
            self._lock.release()

    def _bootstrap_then_complete(self, job_id: str) -> None:
        try:
            self._complete(self._run_bootstrap(job_id))
        except Exception as exc:
            self._set_status(
                state="failed", completed_at=_now(),
                error=f"{type(exc).__name__}: {str(exc)[:500]}",
            )
        finally:
            demo_state_gate.end_reset()
            self._lock.release()

    def _run_bootstrap(self, job_id: str) -> Any:
        workspace = get_workspace_client()
        launched = workspace.jobs.run_now(job_id=int(job_id))
        run_id = int(getattr(launched, "run_id"))
        self._set_status(bootstrap_run_id=run_id)
        deadline = time.monotonic() + 15 * 60
        while time.monotonic() < deadline:
            run = workspace.jobs.get_run(run_id=run_id)
            state = getattr(run, "state", None)
            life_cycle = _enum_text(getattr(state, "life_cycle_state", None))
            result = _enum_text(getattr(state, "result_state", None))
            if life_cycle in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
                if life_cycle != "TERMINATED" or result not in {"SUCCESS", "SUCCEEDED"}:
                    raise RuntimeError(
                        f"Network bootstrap run {run_id} ended {life_cycle}/{result or 'UNKNOWN'}."
                    )
                return baseline_service.canonical_revision()
            time.sleep(2)
        raise TimeoutError("Network bootstrap did not finish within 15 minutes.")

    def _complete(self, canonical: Any) -> dict[str, object]:
        if network_run_manager.repository.has_active():
            raise HTTPException(status_code=409, detail="Wait for active network runs before resetting the demo.")
        if depot_plan_repository.has_active():
            raise HTTPException(status_code=409, detail="Wait for active depot plans before resetting the demo.")
        cleared_runs = network_run_manager.repository.clear_all()
        cleared_changes = demand_change_service.repository.clear_all()
        cleared_plans = depot_plan_repository.clear_all()
        cleared_scenarios = network_scenario_service.repository.clear_all()
        baseline = baseline_service.install_canonical_revision(canonical)
        warmup = solver_warmup_service.start()
        self._set_status(state="reset_complete", completed_at=_now(), error=None)
        return self._response(
            baseline=baseline.model_dump(mode="json"),
            cleared={
                "network_scenarios": cleared_scenarios,
                "network_runs": cleared_runs,
                "demand_changes": cleared_changes,
                "depot_plans": cleared_plans,
            },
            solver_warmup=warmup,
        )

    def _set_status(self, **updates: Any) -> None:
        with self._status_lock:
            self._status.update(updates)

    def _response(self, **extra: object) -> dict[str, object]:
        return {"reset": self.status(), "solver_warmup": solver_warmup_service.status(), **extra}


demo_reset_service = DemoResetService()
