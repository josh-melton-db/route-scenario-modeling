from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException

from ..config import get_route_solver_endpoint, get_workspace_client
from ..models import ComparisonResult, RunStage, RunStartResponse, RunStatus, RunStatusResponse, ScenarioDefinition
from .results_writer import results_writer
from .solver import solver_service

STAGE_ORDER = ["queued", "prepare", "solve", "compare", "persist"]
TERMINAL_STATUSES = {"succeeded", "infeasible", "failed"}


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
        self._runs: dict[str, SolveRunRecord] = {}
        self._results: dict[str, ComparisonResult] = {}
        self._lock = threading.Lock()

    def create_run(self, scenario: ScenarioDefinition) -> RunStartResponse:
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
        with self._lock:
            return self._results.get(scenario_id)

    def endpoint_url(self) -> str:
        host = str(get_workspace_client().config.host or "").rstrip("/")
        return f"{host}/ml/endpoints/{get_route_solver_endpoint()}"

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
    if record.status in TERMINAL_STATUSES:
        return 100
    try:
        idx = STAGE_ORDER.index(record.stage_id)
    except ValueError:
        idx = 0
    return max(5, min(95, int((idx / (len(STAGE_ORDER) - 1)) * 90) + 5))


def _stages(record: SolveRunRecord) -> list[RunStage]:
    current_idx = STAGE_ORDER.index(record.stage_id) if record.stage_id in STAGE_ORDER else 0
    failed = record.status == "failed"
    terminal = record.status in TERMINAL_STATUSES
    labels = {
        "queued": ("Queue solver request", "Run request accepted by the app."),
        "prepare": ("Prepare inputs", "Apply scenario overrides and build the travel matrix."),
        "solve": ("Call solver endpoint", "RouteScenarioSolverModel is solving the CVRPTW."),
        "compare": ("Compare KPIs", "Compare scenario routes against the baseline."),
        "persist": ("Persist results", "Write scenario comparison outputs to Unity Catalog."),
    }
    stages: list[RunStage] = []
    for idx, stage_id in enumerate(STAGE_ORDER):
        label, message = labels[stage_id]
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
