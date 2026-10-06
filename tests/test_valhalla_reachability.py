from unittest.mock import patch

import pytest

from route_opt.valhalla_reachability import (
    BootstrapReachabilityError,
    BootstrapValhallaClient,
)


class Response:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return None
    def read(self):
        import json
        return json.dumps(self.body).encode()


def body(source):
    return {
        "sources_to_targets": [
            [{"distance": 0, "time": 0}, {"distance": 1, "time": 60}],
            [{"distance": 1, "time": 60}, {"distance": 0, "time": 0}],
        ],
        "sources": [[{"lat": 32.85, "lon": -96.85}], source],
    }


@pytest.mark.parametrize("source", [
    [{"lat": 32.7001, "lon": -96.9001}],
    {"location": {"lat": 32.7001, "lon": -96.9001}},
])
def test_bootstrap_client_accepts_nested_bounded_snap(source):
    client = BootstrapValhallaClient(
        "https://routing.test", auth_headers=lambda: {"Authorization": "Bearer test"}
    )
    with patch("route_opt.valhalla_reachability.urlopen", return_value=Response(body(source))):
        result = client.inspect_bidirectional_reachability(
            {"lat": 32.85, "lng": -96.85}, {"lat": 32.7, "lng": -96.9}
        )
    assert result["reachable"] is True
    assert result["road_access_lat"] == 32.7001


def test_bootstrap_client_fails_closed_without_snap_provenance():
    payload = body([{"lat": 32.7, "lon": -96.9}])
    payload.pop("sources")
    client = BootstrapValhallaClient("https://routing.test", auth_headers=lambda: {})
    with patch("route_opt.valhalla_reachability.urlopen", return_value=Response(payload)):
        with pytest.raises(BootstrapReachabilityError, match="did not return snapped"):
            client.inspect_bidirectional_reachability(
                {"lat": 32.85, "lng": -96.85}, {"lat": 32.7, "lng": -96.9}
            )


def test_bootstrap_client_returns_unreachable_for_excessive_candidate_snap():
    client = BootstrapValhallaClient(
        "https://routing.test", auth_headers=lambda: {}, max_snap_distance_miles=0.25
    )
    payload = body([{"lat": 33.7, "lon": -96.9}])
    with patch("route_opt.valhalla_reachability.urlopen", return_value=Response(payload)):
        result = client.inspect_bidirectional_reachability(
            {"lat": 32.85, "lng": -96.85}, {"lat": 32.7, "lng": -96.9}
        )
    assert result["reachable"] is False
    assert result["reason"] == "snap_distance_exceeded"
