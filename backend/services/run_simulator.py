from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException

from ..config import get_run_queued_duration, get_run_running_duration
from ..models import RunStage, RunStartResponse, RunStatus, RunStatusResponse


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    scenario_id: str
    started_at: datetime
    target_status: RunStatus


class RunSimulator:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def create_run(self, scenario_id: str, target_status: RunStatus) -> RunStartResponse:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._runs[run_id] = RunRecord(
            run_id=run_id,
            scenario_id=scenario_id,
            started_at=datetime.now(timezone.utc),
            target_status=target_status,
        )
        return RunStartResponse(
            run_id=run_id,
            scenario_id=scenario_id,
            status="queued",
            message="Optimization job has been queued.",
        )

    def get_run_status(self, run_id: str) -> RunStatusResponse:
        run = self._runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")

        now = datetime.now(timezone.utc)
        elapsed = (now - run.started_at).total_seconds()
        queued_duration = get_run_queued_duration()
        running_duration = get_run_running_duration()
        terminal_after = queued_duration + running_duration

        if elapsed < queued_duration:
            status: RunStatus = "queued"
            progress_pct = max(5, int((elapsed / max(queued_duration, 0.1)) * 20))
            message = "Waiting for job resources."
            completed_at = None
        elif elapsed < terminal_after:
            status = "running"
            running_elapsed = elapsed - queued_duration
            progress_pct = 20 + int((running_elapsed / max(running_duration, 0.1)) * 70)
            message = "Building scenario inputs, travel matrix, and optimized routes."
            completed_at = None
        else:
            status = run.target_status
            progress_pct = 100
            message = {
                "succeeded": "Optimization completed successfully.",
                "infeasible": "Optimization completed with infeasible constraints.",
                "failed": "Optimization job failed.",
            }[status]
            completed_at = now.isoformat()

        return RunStatusResponse(
            run_id=run.run_id,
            scenario_id=run.scenario_id,
            status=status,
            progress_pct=min(progress_pct, 100),
            message=message,
            stages=self._stages(status, elapsed, queued_duration, terminal_after),
            started_at=run.started_at.isoformat(),
            completed_at=completed_at,
        )

    @staticmethod
    def _stages(
        status: RunStatus,
        elapsed: float,
        queued_duration: float,
        terminal_after: float,
    ) -> list[RunStage]:
        terminal = status in {"succeeded", "infeasible", "failed"}
        failed = status == "failed"
        return [
            RunStage(
                stage_id="queued",
                label="Queue Databricks job",
                status="completed" if elapsed >= queued_duration else "running",
                message="Run request accepted.",
            ),
            RunStage(
                stage_id="inputs",
                label="Materialize scenario inputs",
                status=_stage_status(elapsed, queued_duration, terminal_after, terminal, failed),
                message="Apply overrides to customers, depot, fleet, and delivery day.",
            ),
            RunStage(
                stage_id="matrix",
                label="Build travel matrix",
                status=_stage_status(elapsed, queued_duration + 1.0, terminal_after, terminal, failed),
                message="Compute haversine-circuity travel estimates.",
            ),
            RunStage(
                stage_id="solve",
                label="Solve CVRPTW routes",
                status=_stage_status(elapsed, queued_duration + 2.0, terminal_after, terminal, failed),
                message="Prioritize service windows, then cost.",
            ),
            RunStage(
                stage_id="compare",
                label="Compare KPIs",
                status=(
                    "failed"
                    if failed
                    else "completed"
                    if terminal
                    else "pending"
                ),
                message="Write scenario comparison results.",
            ),
        ]


def _stage_status(
    elapsed: float,
    starts_at: float,
    terminal_after: float,
    terminal: bool,
    failed: bool,
) -> str:
    if failed:
        return "failed"
    if terminal or elapsed >= terminal_after:
        return "completed"
    if elapsed >= starts_at:
        return "running"
    return "pending"


simulator = RunSimulator()
