"""Local routing coverage registry used before requesting a road matrix.

Bounds are a cheap configuration preflight only.  The matrix caller must still
validate snapping and every directed matrix cell returned by Valhalla.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


class RoutingCoverageError(ValueError):
    """Raised when routing coverage cannot safely serve a request."""


def _fail(message: str) -> RoutingCoverageError:
    return RoutingCoverageError(f"Routing coverage configuration error: {message}")


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise _fail(f"manifest not found at {path}; set ROUTING_COVERAGE_MANIFEST") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise _fail(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise _fail("manifest root must be an object")
    if value.get("schema_version") != 1:
        raise _fail("schema_version must be 1")
    if not isinstance(value.get("coverages"), list) or not value["coverages"]:
        raise _fail("coverages must be a non-empty array")
    return value


def _nonempty(entry: Mapping[str, Any], field: str, coverage_id: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _fail(f"coverage {coverage_id!r} requires non-empty {field}")
    return value.strip()


def _validate_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise _fail("each coverage must be an object")
    coverage_id = _nonempty(entry, "coverage_id", "<unknown>")
    artifact_version = _nonempty(entry, "artifact_version", coverage_id)
    endpoint_url = _nonempty(entry, "endpoint_url", coverage_id)
    parsed = urlsplit(endpoint_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise _fail(f"coverage {coverage_id!r} has an invalid or credential-bearing endpoint_url")
    costing = _nonempty(entry, "costing", coverage_id)
    if costing != "truck":
        raise _fail(f"coverage {coverage_id!r} costing must be 'truck' for this workflow")
    max_points = entry.get("max_points")
    if isinstance(max_points, bool) or not isinstance(max_points, int) or max_points < 2:
        raise _fail(f"coverage {coverage_id!r} max_points must be an integer of at least 2")

    bounds = entry.get("bounds")
    if not isinstance(bounds, dict) or set(bounds) != {"west", "south", "east", "north"}:
        raise _fail(f"coverage {coverage_id!r} bounds require west, south, east, and north")
    try:
        normalized_bounds = {key: float(bounds[key]) for key in ("west", "south", "east", "north")}
    except (TypeError, ValueError) as exc:
        raise _fail(f"coverage {coverage_id!r} bounds must be numeric") from exc
    if not all(math.isfinite(value) for value in normalized_bounds.values()):
        raise _fail(f"coverage {coverage_id!r} bounds must be finite")
    if not (-180 <= normalized_bounds["west"] < normalized_bounds["east"] <= 180):
        raise _fail(f"coverage {coverage_id!r} longitude bounds are invalid")
    if not (-90 <= normalized_bounds["south"] < normalized_bounds["north"] <= 90):
        raise _fail(f"coverage {coverage_id!r} latitude bounds are invalid")

    depots = entry.get("depot_ids")
    if not isinstance(depots, list) or not depots or any(not isinstance(item, str) or not item.strip() for item in depots):
        raise _fail(f"coverage {coverage_id!r} depot_ids must be a non-empty string array")
    if len(set(depots)) != len(depots):
        raise _fail(f"coverage {coverage_id!r} contains duplicate depot_ids")
    for provenance in ("source", "build", "artifact", "smoke_test"):
        if not isinstance(entry.get(provenance), dict):
            raise _fail(f"coverage {coverage_id!r} requires {provenance} provenance")
    region_id = entry["artifact"].get("region_id")
    if not isinstance(region_id, str) or not region_id.strip():
        raise _fail(f"coverage {coverage_id!r} artifact requires non-empty region_id")

    return {
        **entry,
        "coverage_id": coverage_id,
        "artifact_version": artifact_version,
        "endpoint_url": endpoint_url.rstrip("/"),
        "costing": costing,
        "max_points": max_points,
        "bounds": normalized_bounds,
        "depot_ids": depots,
    }


def resolve_coverage(
    depot_id: str,
    points: Sequence[Mapping[str, Any]],
    *,
    manifest_path: str | os.PathLike[str] | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Resolve one depot and ordered point list to configured Valhalla coverage."""
    selected_path = manifest_path or os.environ.get("ROUTING_COVERAGE_MANIFEST")
    if not selected_path:
        raise _fail("no manifest path supplied; set ROUTING_COVERAGE_MANIFEST")
    manifest = _load_manifest(Path(selected_path))
    entries = [_validate_entry(value) for value in manifest["coverages"]]

    ids = [entry["coverage_id"] for entry in entries]
    if len(set(ids)) != len(ids):
        raise _fail("coverage_id values must be unique")
    mappings: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        for mapped_depot in entry["depot_ids"]:
            mappings.setdefault(mapped_depot, []).append(entry)
    ambiguous = {key: values for key, values in mappings.items() if len(values) > 1}
    if ambiguous:
        names = ", ".join(sorted(ambiguous))
        raise _fail(f"depot mappings are ambiguous for: {names}")

    matches = mappings.get(depot_id, [])
    if not matches:
        raise RoutingCoverageError(
            f"No routing coverage is configured for depot {depot_id!r}; add it to a validated coverage manifest."
        )
    coverage = matches[0]
    smoke = coverage["smoke_test"]
    expected_smoke_identity = {
        "coverage_id": coverage["coverage_id"],
        "artifact_version": coverage["artifact_version"],
        "region_id": coverage["artifact"]["region_id"],
        "endpoint_url": coverage["endpoint_url"],
    }
    smoke_identity_matches = all(smoke.get(key) == value for key, value in expected_smoke_identity.items())
    if strict and (
        coverage.get("status") != "validated"
        or smoke.get("result") != "success"
        or not smoke_identity_matches
    ):
        raise RoutingCoverageError(
            f"Routing coverage {coverage['coverage_id']!r} for depot {depot_id!r} is not validated; "
            "run the artifact identity and bidirectional truck matrix smoke check for this exact "
            "coverage, artifact, region, and endpoint first."
        )
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        raise RoutingCoverageError("Routing points must be an ordered sequence of lat/lon mappings.")
    if len(points) > coverage["max_points"]:
        raise RoutingCoverageError(
            f"Routing request has {len(points)} points but coverage {coverage['coverage_id']!r} allows "
            f"at most {coverage['max_points']}."
        )
    bounds = coverage["bounds"]
    for index, point in enumerate(points):
        if not isinstance(point, Mapping) or "lat" not in point or "lon" not in point:
            raise RoutingCoverageError(f"Routing point {index} must be a mapping with lat and lon.")
        try:
            lat, lon = float(point["lat"]), float(point["lon"])
        except (TypeError, ValueError) as exc:
            raise RoutingCoverageError(f"Routing point {index} lat/lon must be numeric.") from exc
        if not math.isfinite(lat) or not math.isfinite(lon):
            raise RoutingCoverageError(f"Routing point {index} lat/lon must be finite.")
        if not (bounds["south"] <= lat <= bounds["north"] and bounds["west"] <= lon <= bounds["east"]):
            raise RoutingCoverageError(
                f"Routing point {index} ({lat}, {lon}) is outside coverage {coverage['coverage_id']!r} bounds."
            )
    return {
        key: coverage[key]
        for key in ("coverage_id", "artifact_version", "endpoint_url", "costing", "max_points", "bounds")
    }
