"""Verify deployed artifact identity and directed truck matrix reachability."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.request import Request, urlopen


def _request_json(url: str, payload: dict | None = None, *, headers: Mapping[str, str] | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=body, headers=request_headers)
    with urlopen(request, timeout=30) as response:  # nosec: operator-selected smoke endpoint
        return json.load(response)


def _databricks_auth_headers(profile: str, *, config_factory: Callable[..., object] | None = None) -> dict[str, str]:
    """Obtain SDK OAuth headers only for an explicitly supplied profile."""
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("Databricks authentication requires an explicitly supplied nonempty profile")
    if config_factory is None:
        from databricks.sdk.core import Config

        config_factory = Config
    headers = config_factory(profile=profile).authenticate()
    if not isinstance(headers, dict):
        raise RuntimeError("Databricks SDK authentication returned invalid headers")
    return {str(key): str(value) for key, value in headers.items()}


def _requester_with_headers(headers: Mapping[str, str]) -> Callable[[str, dict | None], dict]:
    return lambda url, payload=None: _request_json(url, payload, headers=headers)


def smoke(endpoint_url: str, *, coverage_id: str, region_id: str, artifact_version: str, points: Sequence[dict],
          requester: Callable[[str, dict | None], dict] = _request_json,
          max_snap_distance_miles: float = 0.25) -> dict:
    if len(points) != 2:
        raise ValueError("smoke check requires exactly two representative points")
    health = requester(f"{endpoint_url.rstrip('/')}/health", None)
    active = health.get("region", {})
    if health.get("status") != "ok":
        raise RuntimeError("endpoint health check failed")
    if (active.get("coverage_id"), active.get("region"), active.get("artifact_version")) != (
        coverage_id, region_id, artifact_version
    ):
        raise RuntimeError(
            f"active coverage/artifact mismatch: expected {coverage_id}/{region_id}/{artifact_version}, "
            f"received {active.get('coverage_id')}/{active.get('region')}/{active.get('artifact_version')}"
        )
    matrix = requester(f"{endpoint_url.rstrip('/')}/matrix", {"points": list(points), "costing": "truck"})
    if matrix.get("costing") != "truck":
        raise RuntimeError("smoke matrix did not use truck costing")
    rows = matrix.get("sources_to_targets")
    snapped = matrix.get("sources")
    if not isinstance(snapped, list) or len(snapped) != len(points):
        raise RuntimeError("smoke matrix omitted snapped source coordinates")
    for index, (requested, access) in enumerate(zip(points, snapped)):
        try:
            lat1, lon1 = math.radians(float(requested["lat"])), math.radians(float(requested["lon"]))
            lat2 = math.radians(float(access["lat"]))
            lon2 = math.radians(float(access.get("lon", access.get("lng"))))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"smoke snapped source {index} is malformed") from exc
        delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
        arc = 2 * math.asin(math.sqrt(
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
        ))
        snap_miles = 3958.7613 * arc
        if snap_miles > max_snap_distance_miles:
            raise RuntimeError(
                f"smoke snapped source {index} {snap_miles:.3f} miles; "
                f"limit is {max_snap_distance_miles:.3f} miles"
            )
    try:
        cells = (rows[0][1], rows[1][0])
    except (IndexError, TypeError) as exc:
        raise RuntimeError("smoke matrix is not a directed 2x2 matrix") from exc
    for expected, cell in zip(((0, 1), (1, 0)), cells):
        if not isinstance(cell, dict) or cell.get("time") is None or cell.get("distance") is None:
            raise RuntimeError("representative bidirectional truck matrix contains an unreachable cell")
        if cell.get("error") or cell.get("error_code") or cell.get("status") in {"unreachable", "error"}:
            raise RuntimeError("representative bidirectional truck matrix contains an unreachable cell")
        if "from_index" in cell and "to_index" in cell and (cell["from_index"], cell["to_index"]) != expected:
            raise RuntimeError("representative bidirectional truck matrix indices are misaligned")
        if not all(math.isfinite(float(cell[key])) and float(cell[key]) > 0 for key in ("time", "distance")):
            raise RuntimeError("representative bidirectional truck matrix contains invalid costs")
    return {
        "result": "success",
        "tested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage_id": coverage_id,
        "artifact_version": artifact_version,
        "region_id": region_id,
        "endpoint_url": endpoint_url.rstrip("/"),
    }


def record_result(manifest_path: Path, coverage_id: str, result: dict) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [item for item in manifest.get("coverages", []) if item.get("coverage_id") == coverage_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one coverage {coverage_id!r} in manifest")
    matches[0]["smoke_test"] = result
    if result.get("result") == "success":
        matches[0]["status"] = "validated"
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("coverage_id")
    parser.add_argument("--point", action="append", required=True, help="LAT,LON (provide exactly twice)")
    parser.add_argument("--max-snap-distance-miles", type=float, default=0.25)
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument("--profile", help="explicit Databricks SDK profile for managed App OAuth")
    auth.add_argument(
        "--unauthenticated",
        action="store_true",
        help="intentionally omit authentication (local or explicitly public endpoints only)",
    )
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    coverage = next((item for item in manifest["coverages"] if item["coverage_id"] == args.coverage_id), None)
    if coverage is None:
        parser.error("coverage_id is absent from manifest")
    points = [{"lat": float(value.split(",", 1)[0]), "lon": float(value.split(",", 1)[1])} for value in args.point]
    if args.profile is not None:
        try:
            requester = _requester_with_headers(_databricks_auth_headers(args.profile))
        except Exception as exc:
            parser.error(f"could not authenticate explicit Databricks profile {args.profile!r}: {exc}")
    else:
        requester = _request_json
    try:
        result = smoke(coverage["endpoint_url"], coverage_id=coverage["coverage_id"],
                       region_id=coverage["artifact"]["region_id"],
                       artifact_version=coverage["artifact_version"], points=points,
                       requester=requester,
                       max_snap_distance_miles=args.max_snap_distance_miles)
    except Exception as exc:
        result = {
            "result": "failure",
            "tested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "coverage_id": coverage["coverage_id"],
            "artifact_version": coverage["artifact_version"],
            "region_id": coverage["artifact"]["region_id"],
            "endpoint_url": coverage["endpoint_url"].rstrip("/"),
            "message": str(exc),
        }
        record_result(args.manifest, args.coverage_id, result)
        raise
    record_result(args.manifest, args.coverage_id, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
