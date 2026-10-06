from __future__ import annotations

import json
from collections.abc import Mapping, Sequence


SOLVER_PAYLOAD_VERSION = 2
from route_opt.solver_limits import MAX_SOLVER_POINTS
MAX_SOLVER_PAYLOAD_BYTES = 8 * 1024 * 1024

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
    if len(planning_customers) + 1 > MAX_SOLVER_POINTS:
        raise ValueError(
            f"Route solve has {len(planning_customers) + 1} matrix points; "
            f"the supported limit is {MAX_SOLVER_POINTS}. Partition the route problem first."
        )
    compact_matrix = compact_travel_matrix(travel_matrix or [])
    row = {
        "scenario_id": scenario_id,
        "depot_id": depot_id,
        "delivery_day": delivery_day,
        "planning_depots": json.dumps(planning_depots, sort_keys=True),
        "planning_customers": json.dumps(planning_customers, sort_keys=True),
        "planning_fleet": json.dumps(planning_fleet, sort_keys=True),
        "planning_stops": json.dumps(planning_stops, sort_keys=True),
        "travel_matrix": json.dumps(compact_matrix, separators=(",", ":"), sort_keys=True),
        "cost_parameters": json.dumps(cost_parameters or {}, sort_keys=True),
        "time_limit_seconds": time_limit_seconds,
    }
    payload_bytes = sum(
        len(str(row[column]).encode("utf-8")) for column in PAYLOAD_COLUMNS
    )
    if payload_bytes > MAX_SOLVER_PAYLOAD_BYTES:
        raise ValueError(
            f"Route solver payload is {payload_bytes} bytes; the supported limit is "
            f"{MAX_SOLVER_PAYLOAD_BYTES} bytes. Reduce or partition the route problem."
        )
    return row


def compact_travel_matrix(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Encode a directed matrix without repeating IDs and metadata on every arc."""
    if not rows:
        return {"version": SOLVER_PAYLOAD_VERSION, "node_ids": [], "distance_miles": [], "duration_minutes": []}
    ordered = sorted(rows, key=lambda row: (int(row["origin_index"]), int(row["destination_index"])))
    max_index = max(max(int(row["origin_index"]), int(row["destination_index"])) for row in ordered)
    size = max_index + 1
    if size > MAX_SOLVER_POINTS:
        raise ValueError(f"Travel matrix has {size} points; supported limit is {MAX_SOLVER_POINTS}.")
    if len(ordered) != size * size:
        raise ValueError("Travel matrix must contain every directed arc before compaction.")
    node_ids: list[str | None] = [None] * size
    distances: list[float] = []
    durations: list[int] = []
    scenario_id = str(ordered[0].get("scenario_id", ""))
    depot_id = str(ordered[0].get("depot_id", ""))
    delivery_day = str(ordered[0].get("delivery_day", ""))
    for expected, row in enumerate(ordered):
        origin, destination = divmod(expected, size)
        if int(row["origin_index"]) != origin or int(row["destination_index"]) != destination:
            raise ValueError("Travel matrix indexes are incomplete or duplicated.")
        origin_id, destination_id = str(row["origin_id"]), str(row["destination_id"])
        if node_ids[origin] not in (None, origin_id) or node_ids[destination] not in (None, destination_id):
            raise ValueError("Travel matrix node IDs are inconsistent.")
        node_ids[origin], node_ids[destination] = origin_id, destination_id
        distances.append(float(row["distance_miles"]))
        durations.append(int(row["duration_minutes"]))
    return {
        "version": SOLVER_PAYLOAD_VERSION,
        "scenario_id": scenario_id,
        "depot_id": depot_id,
        "delivery_day": delivery_day,
        "node_ids": node_ids,
        "distance_miles": distances,
        "duration_minutes": durations,
    }


def expand_travel_matrix(value: object) -> list[dict[str, object]]:
    """Decode v2 compact matrices while retaining compatibility with v1 row lists."""
    if isinstance(value, list):
        return [dict(row) for row in value]
    if not isinstance(value, dict) or value.get("version") != SOLVER_PAYLOAD_VERSION:
        raise TypeError("travel_matrix must be a legacy row list or compact v2 matrix")
    node_ids = value.get("node_ids")
    distances = value.get("distance_miles")
    durations = value.get("duration_minutes")
    if not isinstance(node_ids, list) or not isinstance(distances, list) or not isinstance(durations, list):
        raise TypeError("compact travel_matrix arrays are malformed")
    size = len(node_ids)
    if size > MAX_SOLVER_POINTS or len(distances) != size * size or len(durations) != size * size:
        raise ValueError("compact travel_matrix dimensions are invalid")
    rows: list[dict[str, object]] = []
    for offset, (miles, minutes) in enumerate(zip(distances, durations)):
        origin, destination = divmod(offset, size)
        rows.append({
            "scenario_id": str(value.get("scenario_id", "")),
            "depot_id": str(value.get("depot_id", "")),
            "delivery_day": str(value.get("delivery_day", "")),
            "origin_id": str(node_ids[origin]),
            "destination_id": str(node_ids[destination]),
            "origin_index": origin,
            "destination_index": destination,
            "distance_miles": float(miles),
            "duration_minutes": int(minutes),
        })
    return rows
