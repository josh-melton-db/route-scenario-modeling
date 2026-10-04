"""Validate a deployed road-matrix service against an accelerator coverage manifest."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


Requester = Callable[[str, dict[str, Any] | None], dict[str, Any]]


def _request_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    encoded = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json", **dict(headers or {})},
        method="GET" if payload is None else "POST",
    )
    with urlopen(request, timeout=30) as response:  # nosec: operator-selected smoke endpoint
        body = json.load(response)
    if not isinstance(body, dict):
        raise RuntimeError("road-matrix service returned a non-object response")
    return body


def _databricks_auth_headers(profile: str) -> dict[str, str]:
    if not profile.strip():
        raise ValueError("Databricks authentication requires an explicit profile")
    from databricks.sdk.core import Config

    headers = Config(profile=profile).authenticate()
    if not isinstance(headers, dict):
        raise RuntimeError("Databricks SDK authentication returned invalid headers")
    return {str(key): str(value) for key, value in headers.items()}


def _requester(headers: Mapping[str, str]) -> Requester:
    return lambda url, payload=None: _request_json(url, payload, headers=headers)


def smoke(
    endpoint_url: str,
    *,
    coverage_id: str,
    region_id: str,
    artifact_version: str,
    points: Sequence[dict[str, float]],
    requester: Requester = _request_json,
) -> dict[str, Any]:
    if len(points) != 2:
        raise ValueError("smoke check requires exactly two representative points")

    endpoint = endpoint_url.rstrip("/")
    health = requester(f"{endpoint}/health", None)
    active = health.get("region")
    expected_identity = (coverage_id, region_id, artifact_version)
    if health.get("status") != "ok" or not isinstance(active, dict):
        raise RuntimeError("road-matrix service health check failed")
    if (active.get("coverage_id"), active.get("region"), active.get("artifact_version")) != expected_identity:
        raise RuntimeError("active road-matrix coverage/artifact identity does not match the manifest")

    matrix = requester(f"{endpoint}/matrix", {"points": list(points), "costing": "truck"})
    if matrix.get("units") != "kilometers":
        raise RuntimeError("road-matrix service must return distances in kilometers")
    if matrix.get("costing") != "truck":
        raise RuntimeError("road-matrix service did not use truck costing")
    rows = matrix.get("sources_to_targets")
    try:
        directed_cells = ((0, 1, rows[0][1]), (1, 0, rows[1][0]))
    except (IndexError, TypeError) as exc:
        raise RuntimeError("road-matrix service did not return a directed 2x2 matrix") from exc
    for from_index, to_index, cell in directed_cells:
        if not isinstance(cell, dict):
            raise RuntimeError("road-matrix service returned a malformed directed cell")
        if cell.get("error") or cell.get("error_code") or cell.get("status") in {"unreachable", "error"}:
            raise RuntimeError("representative truck matrix contains an unreachable cell")
        values = (cell.get("time"), cell.get("distance"))
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in values):
            raise RuntimeError("representative truck matrix contains invalid time or distance")
        if "from_index" in cell and "to_index" in cell:
            if (cell["from_index"], cell["to_index"]) != (from_index, to_index):
                raise RuntimeError("road-matrix service returned misaligned cell indices")

    return {
        "result": "success",
        "tested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage_id": coverage_id,
        "artifact_version": artifact_version,
        "region_id": region_id,
        "endpoint_url": endpoint,
    }


def record_result(manifest_path: Path, coverage_id: str, result: Mapping[str, Any]) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [item for item in manifest.get("coverages", []) if item.get("coverage_id") == coverage_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one coverage {coverage_id!r} in manifest")
    matches[0]["smoke_test"] = dict(result)
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
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument("--profile", help="explicit Databricks profile for managed App OAuth")
    auth.add_argument("--unauthenticated", action="store_true", help="only for local or explicitly public services")
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    coverage = next((item for item in manifest.get("coverages", []) if item.get("coverage_id") == args.coverage_id), None)
    if coverage is None:
        parser.error("coverage_id is absent from manifest")
    try:
        points = [
            {"lat": float(value.split(",", 1)[0]), "lon": float(value.split(",", 1)[1])}
            for value in args.point
        ]
    except (ValueError, IndexError) as exc:
        parser.error(f"points must use LAT,LON: {exc}")
    requester = _requester(_databricks_auth_headers(args.profile)) if args.profile else _request_json
    try:
        result = smoke(
            coverage["endpoint_url"],
            coverage_id=coverage["coverage_id"],
            region_id=coverage["artifact"]["region_id"],
            artifact_version=coverage["artifact_version"],
            points=points,
            requester=requester,
        )
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
