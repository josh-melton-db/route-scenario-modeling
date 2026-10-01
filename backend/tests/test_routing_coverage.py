import json

import pytest

from backend.services.routing_coverage import RoutingCoverageError, resolve_coverage


def entry(**changes):
    value = {
        "coverage_id": "texas-v1",
        "artifact_version": "texas-2026-10-01",
        "endpoint_url": "https://routing.example.test",
        "costing": "truck",
        "max_points": 4,
        "bounds": {"west": -107, "south": 25, "east": -93, "north": 37},
        "depot_ids": ["DALLAS", "SAN_ANTONIO"],
        "status": "validated",
        "source": {"url": "https://download.example.test/texas.osm.pbf"},
        "build": {"valhalla_version": "3.5.1"},
        "artifact": {"region_id": "texas"},
        "smoke_test": {
            "result": "success", "tested_at": "2026-10-01T00:00:00Z",
            "coverage_id": "texas-v1", "artifact_version": "texas-2026-10-01",
            "region_id": "texas", "endpoint_url": "https://routing.example.test",
        },
    }
    value.update(changes)
    return value


def manifest(tmp_path, coverages):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"schema_version": 1, "coverages": coverages}), encoding="utf-8")
    return path


def test_resolves_shared_coverage_and_preserves_contract(tmp_path):
    result = resolve_coverage("DALLAS", [{"lat": 32.8, "lon": -96.8}], manifest_path=manifest(tmp_path, [entry()]))
    assert result == {
        "coverage_id": "texas-v1", "artifact_version": "texas-2026-10-01",
        "endpoint_url": "https://routing.example.test", "costing": "truck", "max_points": 4,
        "bounds": {"west": -107.0, "south": 25.0, "east": -93.0, "north": 37.0},
    }


def test_uses_environment_manifest(monkeypatch, tmp_path):
    path = manifest(tmp_path, [entry()])
    monkeypatch.setenv("ROUTING_COVERAGE_MANIFEST", str(path))
    assert resolve_coverage("SAN_ANTONIO", []) ["coverage_id"] == "texas-v1"


@pytest.mark.parametrize("point", [{"lat": 40, "lon": -96}, {"lat": 30}, {"lat": "bad", "lon": -96}])
def test_rejects_unsupported_points(tmp_path, point):
    with pytest.raises(RoutingCoverageError, match="point 0"):
        resolve_coverage("DALLAS", [point], manifest_path=manifest(tmp_path, [entry()]))


def test_rejects_ambiguous_mapping(tmp_path):
    other = entry(coverage_id="texas-v2", artifact_version="v2")
    with pytest.raises(RoutingCoverageError, match="ambiguous.*DALLAS"):
        resolve_coverage("DALLAS", [], manifest_path=manifest(tmp_path, [entry(), other]))


@pytest.mark.parametrize("change,match", [
    ({"max_points": 1}, "max_points"),
    ({"bounds": {"west": -90, "south": 25, "east": -100, "north": 37}}, "longitude"),
    ({"endpoint_url": "https://secret@example.test"}, "credential-bearing"),
])
def test_rejects_invalid_entries(tmp_path, change, match):
    with pytest.raises(RoutingCoverageError, match=match):
        resolve_coverage("DALLAS", [], manifest_path=manifest(tmp_path, [entry(**change)]))


def test_strict_rejects_candidate_but_non_strict_allows_preflight(tmp_path):
    path = manifest(tmp_path, [entry(status="candidate", smoke_test={"result": "not_run", "tested_at": None})])
    with pytest.raises(RoutingCoverageError, match="not validated"):
        resolve_coverage("DALLAS", [], manifest_path=path)
    assert resolve_coverage("DALLAS", [], manifest_path=path, strict=False)["coverage_id"] == "texas-v1"


@pytest.mark.parametrize("field,value", [
    ("coverage_id", "other-coverage"),
    ("artifact_version", "stale-artifact"),
    ("region_id", "michigan"),
    ("endpoint_url", "https://other.example.test"),
])
def test_strict_binds_smoke_success_to_exact_identity(tmp_path, field, value):
    value_entry = entry()
    value_entry["smoke_test"][field] = value
    with pytest.raises(RoutingCoverageError, match="exact coverage, artifact, region, and endpoint"):
        resolve_coverage("DALLAS", [], manifest_path=manifest(tmp_path, [value_entry]))
