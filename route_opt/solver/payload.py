from __future__ import annotations

import json

INPUT_SCHEMA = (
    ("scenario_id", "string"),
    ("depot_id", "string"),
    ("delivery_day", "string"),
    ("planning_depots", "string"),
    ("planning_customers", "string"),
    ("planning_fleet", "string"),
    ("planning_stops", "string"),
    ("travel_matrix", "string"),
    ("cost_parameters", "string"),
    ("time_limit_seconds", "long"),
)

PAYLOAD_COLUMNS = [
    "planning_depots",
    "planning_customers",
    "planning_fleet",
    "planning_stops",
    "travel_matrix",
    "cost_parameters",
]

OUTPUT_COLUMNS = [
    "routes",
    "route_stops",
    "unassigned_stops",
    "diagnostics",
]


def make_input_row(
    *,
    scenario_id: str,
    depot_id: str,
    delivery_day: str,
    planning_depots: list[dict[str, object]],
    planning_customers: list[dict[str, object]],
    planning_fleet: list[dict[str, object]],
    planning_stops: list[dict[str, object]],
    travel_matrix: list[dict[str, object]] | None = None,
    cost_parameters: dict[str, object] | None = None,
    time_limit_seconds: int = 5,
) -> dict[str, object]:
    return {
        "scenario_id": scenario_id,
        "depot_id": depot_id,
        "delivery_day": delivery_day,
        "planning_depots": json.dumps(planning_depots, sort_keys=True),
        "planning_customers": json.dumps(planning_customers, sort_keys=True),
        "planning_fleet": json.dumps(planning_fleet, sort_keys=True),
        "planning_stops": json.dumps(planning_stops, sort_keys=True),
        "travel_matrix": json.dumps(travel_matrix or [], sort_keys=True),
        "cost_parameters": json.dumps(cost_parameters or {}, sort_keys=True),
        "time_limit_seconds": time_limit_seconds,
    }
