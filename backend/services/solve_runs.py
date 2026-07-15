from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException

from ..config import get_data_backend, get_route_solver_endpoint, get_workspace_client
from ..models import ComparisonResult, RunStage, RunStartResponse, RunStatus, RunStatusResponse, ScenarioDefinition
from .results_writer import results_writer
from .run_state import STAGE_DETAILS, STAGE_ORDER, TERMINAL_STATUSES, progress_for_stage
from .solver import solver_service
from .store_provider import get_store


@dataclass
class SolveRunRecord:
    run_id: str
    scenario: ScenarioDefinition
    status: RunStatus = "queued"
    stage_id: str = "queued"
    message: str = "Solver run has been queued."
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    result: ComparisonResult | None = None
    error: str | None = None


class SolveRunManager:
    def __init__(self) -> None:
        # Retained only for the temporary Unity Catalog fallback feature flag.
        self._runs: dict[str, SolveRunRecord] = {}
        self._results: dict[str, ComparisonResult] = {}
        self._lock = threading.Lock()
        self._lakebase_workers: set[str] = set()
        self._lakebase_worker_lock = threading.Lock()

    def create_run(self, scenario: ScenarioDefinition) -> RunStartResponse:
        if get_data_backend() == "lakebase":
            store = get_store()
            create = getattr(store, "create_solve_run", None)
            if not callable(create):
                raise RuntimeError("Lakebase store does not support durable solve runs.")
            started = create(scenario, self.endpoint_url())
            self._start_lakebase_worker(started.run_id)
            return started

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        record = SolveRunRecord(run_id=run_id, scenario=scenario)
        with self._lock:
            self._runs[run_id] = record
        thread = threading.Thread(target=self._execute_run, args=(run_id,), daemon=True)
        thread.start()
        return RunStartResponse(
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            status="queued",
            message=record.message,
            databricks_run_url=self.endpoint_url(),
        )

    def get_status(self, run_id: str) -> RunStatusResponse:
        if get_data_backend() == "lakebase":
            get_status = getattr(get_store(), "get_solve_run_status", None)
            if not callable(get_status):
                raise RuntimeError("Lakebase store does not support durable solve runs.")
            return get_status(run_id, self.endpoint_url())

        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise HTTPException(status_code=404, detail="Run not found.")
            snapshot = SolveRunRecord(**record.__dict__)
        return RunStatusResponse(
            run_id=snapshot.run_id,
            scenario_id=snapshot.scenario.scenario_id,
            status=snapshot.status,
            progress_pct=_progress(snapshot),
            message=snapshot.message,
            stages=_stages(snapshot),
            started_at=snapshot.started_at.isoformat(),
            completed_at=snapshot.completed_at.isoformat() if snapshot.completed_at else None,
            databricks_run_url=self.endpoint_url(),
        )

    def get_result(self, scenario_id: str) -> ComparisonResult | None:
        if get_data_backend() == "lakebase":
            try:
                return get_store().get_scenario_result(scenario_id)
            except HTTPException as exc:
                if exc.status_code == 404:
                    return None
                raise
        with self._lock:
            return self._results.get(scenario_id)

    def recover_pending_runs(self) -> None:
        """Resume unleased Lakebase runs after an app restart without double-claiming."""
        if get_data_backend() != "lakebase":
            return
        resumable = getattr(get_store(), "resumable_run_ids", None)
        if not callable(resumable):
            raise RuntimeError("Lakebase store does not support durable solve runs.")
        for run_id in resumable():
            self._start_lakebase_worker(run_id)

    def endpoint_url(self) -> str:
        host = str(get_workspace_client().config.host or "").rstrip("/")
        return f"{host}/ml/endpoints/{get_route_solver_endpoint()}"

    def _start_lakebase_worker(self, run_id: str) -> None:
        with self._lakebase_worker_lock:
            if run_id in self._lakebase_workers:
                return
            self._lakebase_workers.add(run_id)
        thread = threading.Thread(target=self._execute_lakebase_run, args=(run_id,), daemon=True)
        thread.start()

    def _execute_lakebase_run(self, run_id: str) -> None:
        worker_id = f"worker_{uuid.uuid4().hex[:12]}"
        current_stage = "queued"
        store = get_store()
        try:
            claim = getattr(store, "claim_solve_run", None)
            if not callable(claim):
                raise RuntimeError("Lakebase store does not support durable solve runs.")
            scenario = claim(run_id, worker_id)
            if scenario is None:
                return

            current_stage = "precheck"
            store.start_run_stage(
                run_id,
                current_stage,
                "Validating scenario inputs before solver invocation.",
                worker_id,
            )
            validation = store.validate_scenario(scenario.scenario_id)
            store.record_run_validation(run_id, validation, worker_id)
            if not validation.valid:
                message = "Precheck failed; correct the validation issues before retrying."
                store.fail_solve_run(
                    run_id,
                    current_stage,
                    message,
                    worker_id,
                    validation=validation,
                )
                store.set_scenario_status(scenario.scenario_id, "draft")
                return
            store.complete_run_stage(run_id, current_stage, worker_id)

            current_stage = "prepare"
            store.start_run_stage(
                run_id,
                current_stage,
                "Applying overrides and building planning inputs.",
                worker_id,
            )
            inputs = solver_service.prepare_scenario_inputs(scenario)
            store.complete_run_stage(run_id, current_stage, worker_id)

            current_stage = "solve"
            store.start_run_stage(
                run_id,
                current_stage,
                "Calling the Databricks Model Serving solver endpoint.",
                worker_id,
            )
            solved = solver_service.solve_prepared_scenario(scenario, inputs)
            store.complete_run_stage(run_id, current_stage, worker_id)

            current_stage = "compare"
            store.start_run_stage(
                run_id,
                current_stage,
                "Comparing optimized scenario KPIs with the baseline.",
                worker_id,
            )
            result = solver_service.compare_prepared_scenario(scenario, solved)
            store.complete_run_stage(run_id, current_stage, worker_id)

            current_stage = "persist"
            store.start_run_stage(
                run_id,
                current_stage,
                "Persisting comparison results in Lakebase.",
                worker_id,
            )
            results_writer.persist(scenario, result)
            store.complete_run_stage(run_id, current_stage, worker_id)

            final_status: RunStatus = "infeasible" if result.status == "infeasible" else "succeeded"
            final_message = (
                "Optimization completed successfully."
                if final_status == "succeeded"
                else "Optimization completed with infeasible constraints."
            )
            store.complete_solve_run(run_id, final_status, final_message, worker_id)
            store.set_scenario_status(
                scenario.scenario_id,
                "infeasible" if final_status == "infeasible" else "completed",
            )
        except Exception as exc:  # durable error state is observable after worker exit
            try:
                store.fail_solve_run(
                    run_id,
                    current_stage,
                    f"Optimization failed: {exc}",
                    worker_id,
                )
            except Exception:
                pass
        finally:
            with self._lakebase_worker_lock:
                self._lakebase_workers.discard(run_id)

    def _execute_run(self, run_id: str) -> None:
        try:
            self._set_stage(run_id, "prepare", "Preparing scenario inputs from Unity Catalog.")
            with self._lock:
                scenario = self._runs[run_id].scenario

            self._set_stage(run_id, "solve", "Calling the Databricks Model Serving solver endpoint.")
            result = solver_service.solve_and_compare(scenario)

            self._set_stage(run_id, "compare", "Comparison result is ready for the application.")
            with self._lock:
                self._runs[run_id].result = result
                self._results[scenario.scenario_id] = result

            self._set_stage(run_id, "persist", "Persisting scenario results to Unity Catalog.")
            results_writer.persist(scenario, result)

            final_status: RunStatus = "infeasible" if result.status == "infeasible" else "succeeded"
            self._complete(
                run_id,
                final_status,
                "Optimization completed successfully."
                if final_status == "succeeded"
                else "Optimization completed with infeasible constraints.",
            )
        except Exception as exc:  # pragma: no cover - exercised through integration-style tests
            self._fail(run_id, str(exc))

    def _set_stage(self, run_id: str, stage_id: str, message: str) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.status = "running"
            record.stage_id = stage_id
            record.message = message

    def _complete(self, run_id: str, status: RunStatus, message: str) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.status = status
            record.stage_id = "persist"
            record.message = message
            record.completed_at = datetime.now(timezone.utc)

    def _fail(self, run_id: str, message: str) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.status = "failed"
            record.message = f"Optimization failed: {message}"
            record.error = message
            record.completed_at = datetime.now(timezone.utc)


def _progress(record: SolveRunRecord) -> int:
    return progress_for_stage(record.status, record.stage_id)


def _stages(record: SolveRunRecord) -> list[RunStage]:
    current_idx = STAGE_ORDER.index(record.stage_id) if record.stage_id in STAGE_ORDER else 0
    failed = record.status == "failed"
    terminal = record.status in TERMINAL_STATUSES
    stages: list[RunStage] = []
    for idx, stage_id in enumerate(STAGE_ORDER):
        label, message = STAGE_DETAILS[stage_id]
        status: Literal["pending", "running", "completed", "failed"]
        if failed and idx >= current_idx:
            status = "failed"
        elif terminal or idx < current_idx:
            status = "completed"
        elif idx == current_idx:
            status = "running"
        else:
            status = "pending"
        stages.append(RunStage(stage_id=stage_id, label=label, status=status, message=message))
    return stages


solve_run_manager = SolveRunManager()
