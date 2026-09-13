from __future__ import annotations

import httpx
import pytest

from backend.services.valhalla import KM_TO_MILES, ValhallaMatrixClient, ValhallaMatrixError


def _request_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/matrix"
    assert request.headers["authorization"] == "Bearer test"
    return httpx.Response(
        200,
        json={
            "units": "kilometers",
            "costing": "truck",
            "sources_to_targets": [
                [{"distance": 0, "time": 0}, {"distance": 10, "time": 900}],
                [{"distance": 12, "time": 1200}, {"distance": 0, "time": 0}],
            ],
        },
    )


def test_valhalla_matrix_converts_directed_cells_to_solver_rows() -> None:
    client = ValhallaMatrixClient(
        "https://valhalla.example.test",
        auth_headers=lambda: {"Authorization": "Bearer test"},
        transport=httpx.MockTransport(_request_handler),
    )
    nodes, rows = client.build_travel_matrix(
        scenario_id="scn-1",
        depot={"depot_id": "D1", "lat": 42.0, "lng": -83.0},
        stops=[{"customer_id": "C1", "lat": 42.1, "lng": -83.1}],
        delivery_day="Tuesday",
    )

    assert [node["node_id"] for node in nodes] == ["D1:DEPOT", "C1"]
    assert len(rows) == 4
    outbound = next(row for row in rows if row["origin_id"] == "D1:DEPOT" and row["destination_id"] == "C1")
    inbound = next(row for row in rows if row["origin_id"] == "C1" and row["destination_id"] == "D1:DEPOT")
    assert outbound["distance_miles"] == round(10 * KM_TO_MILES, 3)
    assert outbound["duration_minutes"] == 15
    assert inbound["duration_minutes"] == 20
    assert outbound["matrix_source"] == "valhalla"


def test_valhalla_matrix_rejects_unreachable_cells() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "sources_to_targets": [
                    [{"distance": 0, "time": 0}, {"status": "unreachable"}],
                    [{"distance": 1, "time": 60}, {"distance": 0, "time": 0}],
                ]
            },
        )
    )
    client = ValhallaMatrixClient(
        "https://valhalla.example.test",
        auth_headers=lambda: {},
        transport=transport,
    )
    with pytest.raises(ValhallaMatrixError, match="unreachable"):
        client.build_travel_matrix(
            scenario_id="scn-1",
            depot={"depot_id": "D1", "lat": 42.0, "lng": -83.0},
            stops=[{"customer_id": "C1", "lat": 42.1, "lng": -83.1}],
            delivery_day="Tuesday",
        )
