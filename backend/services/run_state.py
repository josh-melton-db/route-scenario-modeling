"""Shared durable solve-run state definitions."""

from __future__ import annotations

STAGE_ORDER = ("queued", "precheck", "prepare", "solve", "compare", "persist")
TERMINAL_STATUSES = frozenset({"succeeded", "infeasible", "failed"})
STAGE_DETAILS: dict[str, tuple[str, str]] = {
    "queued": ("Queue solver request", "Run request accepted by the application."),
    "precheck": ("Precheck inputs", "Validate scenario inputs before contacting the solver."),
    "prepare": ("Prepare inputs", "Apply overrides and build the travel matrix."),
    "solve": ("Call solver endpoint", "RouteScenarioSolverModel is solving the CVRPTW."),
    "compare": ("Compare KPIs", "Compare scenario routes against the baseline."),
    "persist": ("Persist results", "Write scenario comparison outputs to Lakebase."),
}


def progress_for_stage(status: str, stage_id: str) -> int:
    if status in TERMINAL_STATUSES:
        return 100
    try:
        index = STAGE_ORDER.index(stage_id)
    except ValueError:
        index = 0
    return max(5, min(95, int((index / (len(STAGE_ORDER) - 1)) * 90) + 5))
