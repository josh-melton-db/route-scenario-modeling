import json
from unittest.mock import mock_open, patch

from fastapi.testclient import TestClient

from valhalla_service import app


def test_health_exposes_selected_coverage_region_and_artifact() -> None:
    active = {"coverage_id": "texas-delivery", "region": "texas", "artifact_version": "tx-1"}
    with patch.object(app.httpx, "get") as get, patch("builtins.open", mock_open(read_data=json.dumps(active))):
        get.return_value.json.return_value = {"version": "3.5.1"}
        response = app.health()

    assert response["status"] == "ok"
    assert response["region"] == active


def test_matrix_preserves_point_order_and_directed_cells() -> None:
    cells = [
        [{"from_index": 0, "to_index": 0, "time": 0, "distance": 0.0}, {"from_index": 0, "to_index": 1, "time": 50, "distance": 0.4}],
        [{"from_index": 1, "to_index": 0, "time": 40, "distance": 0.3}, {"from_index": 1, "to_index": 1, "time": 0, "distance": 0.0}],
    ]
    with patch.object(app, "_matrix", return_value={"sources_to_targets": cells}) as call:
        response = TestClient(app.app).post(
            "/matrix",
            json={
                "points": [{"lat": 42.5063, "lon": 1.5218}, {"lat": 42.5078, "lon": 1.5211}],
                "costing": "auto",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "units": "kilometers",
        "costing": "auto",
        "sources_to_targets": cells,
    }
    sources, targets, costing = call.call_args.args
    assert [(point.lat, point.lon) for point in sources] == [(42.5063, 1.5218), (42.5078, 1.5211)]
    assert sources == targets
    assert costing == "auto"


def test_matrix_preserves_snapped_source_and_target_provenance() -> None:
    result = {
        "sources_to_targets": [[{}, {}], [{}, {}]],
        "sources": [{"lat": 42.5, "lon": 1.5}, {"lat": 42.6, "lon": 1.6}],
        "targets": [{"lat": 42.5, "lon": 1.5}, {"lat": 42.6, "lon": 1.6}],
    }
    with patch.object(app, "_matrix", return_value=result):
        response = TestClient(app.app).post(
            "/matrix",
            json={"points": [{"lat": 42.5, "lon": 1.5}, {"lat": 42.6, "lon": 1.6}]},
        )
    assert response.json()["sources"] == result["sources"]
    assert response.json()["targets"] == result["targets"]


def test_matrix_requires_at_least_two_points() -> None:
    with patch.object(app, "_matrix") as call:
        response = TestClient(app.app).post(
            "/matrix",
            json={"points": [{"lat": 42.5063, "lon": 1.5218}]},
        )

    assert response.status_code == 422
    call.assert_not_called()
