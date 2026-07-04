from __future__ import annotations

from datetime import datetime


def solver_diagnostic(
    *,
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    status: str,
    message: str,
    objective_value: float | None = None,
    **metadata: object,
) -> dict[str, object]:
    row = {
        "solver_run_id": f"run-{scenario_id}-{depot_id}-{delivery_day}".lower(),
        "scenario_id": scenario_id,
        "depot_id": depot_id,
        "delivery_day": delivery_day,
        "solver": "ortools_cvrptw",
        "status": status,
        "objective_value": objective_value,
        "message": message,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    row.update(metadata)
    return row
