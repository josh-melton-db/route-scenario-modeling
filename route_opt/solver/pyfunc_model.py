from __future__ import annotations

import json
from dataclasses import fields
from typing import Any

import mlflow.pyfunc
import pandas as pd

from .ortools_cvrptw import solve_scenario_partition
from .payload import OUTPUT_COLUMNS, PAYLOAD_COLUMNS, make_input_row
from ..cost import CostParameters


class RouteScenarioSolverModel(mlflow.pyfunc.PythonModel):
    """MLflow wrapper for batch scenario/depot/day route solves."""

    def predict(self, context: Any, model_input: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for _, row in model_input.iterrows():
            solution = solve_scenario_partition(
                scenario_id=str(row["scenario_id"]),
                depot_id=str(row["depot_id"]),
                delivery_day=str(row["delivery_day"]),
                planning_depots=_payload(row.get("planning_depots")),
                planning_customers=_payload(row.get("planning_customers")),
                planning_fleet=_payload(row.get("planning_fleet")),
                planning_stops=_payload(row.get("planning_stops")),
                travel_matrix=_payload(row.get("travel_matrix")),
                params=_cost_parameters(row.get("cost_parameters")),
                time_limit_seconds=int(row.get("time_limit_seconds", 5) or 5),
            )
            rows.append(
                {
                    "scenario_id": row["scenario_id"],
                    "depot_id": row["depot_id"],
                    "delivery_day": row["delivery_day"],
                    **{
                        column: json.dumps(solution[column], sort_keys=True)
                        for column in OUTPUT_COLUMNS
                    },
                }
            )
        return pd.DataFrame(rows)


def _payload(value: object) -> list[dict[str, object]]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        if not value:
            return []
        decoded = json.loads(value)
        if isinstance(decoded, list):
            return decoded
    raise TypeError(f"Expected JSON list payload, got {type(value).__name__}")


def _cost_parameters(value: object) -> CostParameters | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return None
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise TypeError("cost_parameters must be a JSON object when provided")
    allowed = {field.name for field in fields(CostParameters)}
    return CostParameters(**{key: decoded[key] for key in allowed & decoded.keys()})
