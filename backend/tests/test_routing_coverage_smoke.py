from __future__ import annotations

import json

import pytest

from backend.services.routing_coverage_smoke import record_result, smoke


POINTS = [{"lat": 32.8, "lon": -96.8}, {"lat": 29.4, "lon": -98.5}]


def _requester(url: str, payload: dict | None) -> dict:
    if url.endswith("/health"):
        return {
            "status": "ok",
            "region": {
                "coverage_id": "texas-delivery",
                "region": "texas",
                "artifact_version": "tx-v1",
            },
        }
    assert payload == {"points": POINTS, "costing": "truck"}
    return {
        "units": "kilometers",
        "costing": "truck",
        "sources_to_targets": [
            [
                {"from_index": 0, "to_index": 0, "time": 0, "distance": 0},
                {"from_index": 0, "to_index": 1, "time": 10, "distance": 1.2},
            ],
            [
                {"from_index": 1, "to_index": 0, "time": 12, "distance": 1.4},
                {"from_index": 1, "to_index": 1, "time": 0, "distance": 0},
            ],
        ],
    }


def test_smoke_validates_health_identity_and_directed_matrix_contract() -> None:
    result = smoke(
        "https://routing.example.test/",
        coverage_id="texas-delivery",
        region_id="texas",
        artifact_version="tx-v1",
        points=POINTS,
        requester=_requester,
    )
    assert result["result"] == "success"
    assert result["endpoint_url"] == "https://routing.example.test"


def test_smoke_rejects_stale_artifact_identity() -> None:
    with pytest.raises(RuntimeError, match="identity"):
        smoke(
            "https://routing.example.test",
            coverage_id="texas-delivery",
            region_id="texas",
            artifact_version="tx-v2",
            points=POINTS,
            requester=_requester,
        )


def test_smoke_rejects_unreachable_or_misaligned_directed_cells() -> None:
    def requester(url: str, payload: dict | None) -> dict:
        body = _requester(url, payload)
        if url.endswith("/matrix"):
            body["sources_to_targets"][1][0]["status"] = "unreachable"
        return body

    with pytest.raises(RuntimeError, match="unreachable"):
        smoke(
            "https://routing.example.test",
            coverage_id="texas-delivery",
            region_id="texas",
            artifact_version="tx-v1",
            points=POINTS,
            requester=requester,
        )


def test_smoke_rejects_incompatible_distance_units() -> None:
    def requester(url: str, payload: dict | None) -> dict:
        body = _requester(url, payload)
        if url.endswith("/matrix"):
            body["units"] = "miles"
        return body

    with pytest.raises(RuntimeError, match="kilometers"):
        smoke(
            "https://routing.example.test",
            coverage_id="texas-delivery",
            region_id="texas",
            artifact_version="tx-v1",
            points=POINTS,
            requester=requester,
        )


def test_record_result_updates_only_requested_coverage(tmp_path) -> None:
    path = tmp_path / "coverage.json"
    path.write_text(
        json.dumps({"coverages": [{"coverage_id": "texas-delivery", "status": "candidate"}]}),
        encoding="utf-8",
    )
    record_result(path, "texas-delivery", {"result": "success", "artifact_version": "tx-v1"})
    coverage = json.loads(path.read_text(encoding="utf-8"))["coverages"][0]
    assert coverage["status"] == "validated"
    assert coverage["smoke_test"]["artifact_version"] == "tx-v1"
