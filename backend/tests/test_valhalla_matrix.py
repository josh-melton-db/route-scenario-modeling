from __future__ import annotations

import httpx
import pytest
import subprocess
import sys

from backend.services.valhalla import (
    KM_TO_MILES,
    PROHIBITED_ARC_DURATION_MINUTES,
    ValhallaMatrixClient,
    ValhallaMatrixError,
)
from backend import config


def test_valhalla_import_does_not_require_ortools() -> None:
    script = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'ortools' or name.startswith('ortools.'):
        raise RuntimeError('unexpected OR-Tools import')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from backend.services.valhalla import ValhallaMatrixClient
assert ValhallaMatrixClient
"""
    subprocess.run([sys.executable, "-c", script], check=True)


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


def test_valhalla_matrix_preserves_unreachable_cells_as_prohibited_arcs() -> None:
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
    _, rows = client.build_travel_matrix(
        scenario_id="scn-1",
        depot={"depot_id": "D1", "lat": 42.0, "lng": -83.0},
        stops=[{"customer_id": "C1", "lat": 42.1, "lng": -83.1}],
        delivery_day="Tuesday",
    )
    outbound = next(row for row in rows if row["origin_index"] == 0 and row["destination_index"] == 1)
    inbound = next(row for row in rows if row["origin_index"] == 1 and row["destination_index"] == 0)
    assert outbound["road_reachable"] is False
    assert outbound["duration_minutes"] == PROHIBITED_ARC_DURATION_MINUTES
    assert inbound["road_reachable"] is True


def test_valhalla_matrix_error_code_prohibits_arc_even_with_distance_and_time() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "sources_to_targets": [
                    [{"distance": 0, "time": 0}, {"distance": 10, "time": 900, "error_code": 442}],
                    [{"distance": 12, "time": 1200}, {"distance": 0, "time": 0}],
                ]
            },
        )
    )
    client = ValhallaMatrixClient(
        "https://valhalla.example.test", auth_headers=lambda: {}, transport=transport
    )
    _, rows = client.build_travel_matrix(
        scenario_id="scn-1",
        depot={"depot_id": "D1", "lat": 42.0, "lng": -83.0},
        stops=[{"customer_id": "C1", "lat": 42.1, "lng": -83.1}],
        delivery_day="Tuesday",
    )
    outbound = next(row for row in rows if row["origin_index"] == 0 and row["destination_index"] == 1)
    assert outbound["road_reachable"] is False
    assert outbound["distance_miles"] == 1_000_000.0
    assert outbound["duration_minutes"] == PROHIBITED_ARC_DURATION_MINUTES


def test_generation_reachability_validator_requires_both_directed_arcs() -> None:
    responses = iter([
        [[{"distance": 0, "time": 0}, {"distance": 1, "time": 60}],
         [{"distance": 1, "time": 60}, {"distance": 0, "time": 0}]],
        [[{"distance": 0, "time": 0}, {"distance": 1, "time": 60}],
         [{"distance": None, "time": None}, {"distance": 0, "time": 0}]],
    ])
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"sources_to_targets": next(responses)})
    )
    client = ValhallaMatrixClient(
        "https://valhalla.example.test", auth_headers=lambda: {}, transport=transport
    )
    depot = {"lat": 32.85, "lng": -96.85}
    point = {"lat": 32.7, "lng": -96.9}
    assert client.is_bidirectionally_reachable(depot, point) is True
    assert client.is_bidirectionally_reachable(depot, point) is False


def test_generation_reachability_rejects_excessive_or_unreported_snap() -> None:
    cells = [
        [{"distance": 0, "time": 0}, {"distance": 1, "time": 60}],
        [{"distance": 1, "time": 60}, {"distance": 0, "time": 0}],
    ]
    responses = iter([
        {"sources_to_targets": cells, "sources": [
            {"lat": 32.85, "lon": -96.85}, {"lat": 33.7, "lon": -96.9}
        ]},
        {"sources_to_targets": cells},
    ])
    client = ValhallaMatrixClient(
        "https://valhalla.example.test", auth_headers=lambda: {},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=next(responses))),
        max_snap_distance_miles=0.25,
    )
    rejected = client.inspect_bidirectional_reachability(
        {"lat": 32.85, "lng": -96.85}, {"lat": 32.7, "lng": -96.9}
    )
    assert rejected["reachable"] is False
    assert rejected["reason"] == "snap_distance_exceeded"
    with pytest.raises(ValhallaMatrixError, match="did not return snapped"):
        client.is_bidirectionally_reachable(
            {"lat": 32.85, "lng": -96.85}, {"lat": 32.7, "lng": -96.9}
        )


def test_generation_retries_next_candidate_after_excessive_snap() -> None:
    from route_opt.network_synthetic import _resolve_road_reachable_coordinate

    calls = 0
    cells = [
        [{"distance": 0, "time": 0}, {"distance": 1, "time": 60}],
        [{"distance": 1, "time": 60}, {"distance": 0, "time": 0}],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        requested = request.read()
        import json
        points = json.loads(requested)["points"]
        customer = points[1]
        access = (
            {"lat": customer["lat"] + 1.0, "lon": customer["lon"]}
            if calls == 1 else customer
        )
        return httpx.Response(200, json={
            "sources_to_targets": cells,
            "sources": [points[0], access],
        })

    client = ValhallaMatrixClient(
        "https://valhalla.example.test", auth_headers=lambda: {},
        transport=httpx.MockTransport(handler), max_snap_distance_miles=0.25,
    )
    lat, lng, metadata = _resolve_road_reachable_coordinate(
        depot={"lat": 32.85, "lng": -96.85},
        original_lat=32.70, original_lng=-96.90,
        validator=client.inspect_bidirectional_reachability,
        provenance={"costing": "truck", "coverage_id": "tx", "artifact_version": "v1"},
    )
    assert calls == 3
    assert metadata["road_reachability_status"] == "validated"
    assert metadata["road_adjustment_attempt"] == 1
    assert metadata["road_adjustment_miles"] == 1.0
    assert (lat, lng) != (32.70, -96.90)


def test_full_matrix_solve_still_rejects_excessive_snap() -> None:
    cells = [
        [{"distance": 0, "time": 0}, {"distance": 1, "time": 60}],
        [{"distance": 1, "time": 60}, {"distance": 0, "time": 0}],
    ]
    client = ValhallaMatrixClient(
        "https://valhalla.example.test", auth_headers=lambda: {},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            "sources_to_targets": cells,
            "sources": [
                {"lat": 32.85, "lon": -96.85},
                {"lat": 33.7, "lon": -96.9},
            ],
        })),
        max_snap_distance_miles=0.25,
    )
    with pytest.raises(ValhallaMatrixError, match="snapped source 1"):
        client.build_travel_matrix(
            scenario_id="scn", depot={"depot_id": "D1", "lat": 32.85, "lng": -96.85},
            stops=[{"customer_id": "C1", "lat": 32.7, "lng": -96.9}],
            delivery_day="2026-10-06",
        )


def test_generation_reachability_reports_bounded_access_provenance() -> None:
    body = {
        "sources_to_targets": [
            [{"distance": 0, "time": 0}, {"distance": 1, "time": 60}],
            [{"distance": 1, "time": 60}, {"distance": 0, "time": 0}],
        ],
        "sources": [
            {"lat": 32.85, "lon": -96.85},
            {"lat": 32.7001, "lon": -96.9001},
        ],
    }
    client = ValhallaMatrixClient(
        "https://valhalla.example.test", auth_headers=lambda: {},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
        max_snap_distance_miles=0.25,
    )
    inspected = client.inspect_bidirectional_reachability(
        {"lat": 32.85, "lng": -96.85}, {"lat": 32.7, "lng": -96.9}
    )
    assert inspected["reachable"] is True
    assert inspected["road_access_lat"] == 32.7001
    assert inspected["road_access_lng"] == -96.9001
    assert 0 < inspected["road_snap_distance_miles"] < 0.25


@pytest.mark.parametrize(
    "source",
    [
        [{"lat": 32.7001, "lon": -96.9001}],
        {"location": {"lat": 32.7001, "lon": -96.9001}},
    ],
)
def test_generation_reachability_accepts_actual_nested_snap_shapes(source) -> None:
    body = {
        "sources_to_targets": [
            [{"distance": 0, "time": 0}, {"distance": 1, "time": 60}],
            [{"distance": 1, "time": 60}, {"distance": 0, "time": 0}],
        ],
        "sources": [
            [{"lat": 32.85, "lon": -96.85}],
            source,
        ],
    }
    client = ValhallaMatrixClient(
        "https://valhalla.example.test", auth_headers=lambda: {},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
        max_snap_distance_miles=0.25,
    )
    result = client.inspect_bidirectional_reachability(
        {"lat": 32.85, "lng": -96.85}, {"lat": 32.7, "lng": -96.9}
    )
    assert result["road_access_lat"] == 32.7001


def test_valhalla_url_accepts_explicit_url(monkeypatch) -> None:
    monkeypatch.setenv("VALHALLA_APP_URL", "https://valhalla.example/")
    assert config.get_valhalla_app_url() == "https://valhalla.example"


def test_valhalla_url_resolves_app_resource_name(monkeypatch) -> None:
    class Apps:
        @staticmethod
        def get(*, name: str):
            assert name == "valhalla-api-poc"
            return type("App", (), {"url": "https://valhalla.apps.example/"})()

    monkeypatch.setenv("VALHALLA_APP_URL", "valhalla-api-poc")
    monkeypatch.setattr(config, "get_workspace_client", lambda: type("Client", (), {"apps": Apps()})())
    assert config.get_valhalla_app_url() == "https://valhalla.apps.example"
