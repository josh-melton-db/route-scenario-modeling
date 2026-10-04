from __future__ import annotations

import json

import pytest

from route_opt.solver.payload import (
    MAX_SOLVER_POINTS,
    compact_travel_matrix,
    expand_travel_matrix,
    make_input_row,
)


def _matrix(size: int) -> list[dict[str, object]]:
    return [
        {
            "scenario_id": "S",
            "depot_id": "D",
            "delivery_day": "2026-10-02",
            "origin_id": f"N{i}",
            "destination_id": f"N{j}",
            "origin_index": i,
            "destination_index": j,
            "distance_miles": float(i + j),
            "duration_minutes": i + j,
        }
        for i in range(size)
        for j in range(size)
    ]


def test_compact_matrix_round_trip_and_payload_reduction() -> None:
    rows = _matrix(20)
    compact = compact_travel_matrix(rows)
    expanded = expand_travel_matrix(compact)

    assert expanded == rows
    assert len(json.dumps(compact)) < len(json.dumps(rows)) * 0.25


def test_solver_payload_rejects_problem_above_point_limit() -> None:
    with pytest.raises(ValueError, match="supported limit"):
        make_input_row(
            scenario_id="S",
            depot_id="D",
            delivery_day="2026-10-02",
            planning_depots=[],
            planning_customers=[{}] * MAX_SOLVER_POINTS,
            planning_fleet=[],
            planning_stops=[],
        )
