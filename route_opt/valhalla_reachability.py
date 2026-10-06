"""Dependency-light Valhalla reachability client for serverless bootstrap notebooks."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.request import Request, urlopen

from .matrix import haversine_miles


class BootstrapReachabilityError(RuntimeError):
    pass


class BootstrapValhallaClient:
    def __init__(
        self, base_url: str, *, auth_headers: Callable[[], Mapping[str, str]],
        max_snap_distance_miles: float = 0.25, timeout_seconds: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_headers = auth_headers
        self.max_snap_distance_miles = max_snap_distance_miles
        self.timeout_seconds = timeout_seconds

    def inspect_bidirectional_reachability(
        self, depot: Mapping[str, object], point: Mapping[str, object]
    ) -> dict[str, object]:
        requested = [
            {"lat": float(depot["lat"]), "lon": float(depot.get("lng", depot.get("lon")))},
            {"lat": float(point["lat"]), "lon": float(point.get("lng", point.get("lon")))},
        ]
        request = Request(
            f"{self.base_url}/matrix",
            data=json.dumps({"points": requested, "costing": "truck"}).encode(),
            headers={"Content-Type": "application/json", **dict(self.auth_headers())},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec: configured app URL
                body = json.load(response)
            cells = body["sources_to_targets"]
            arcs = (cells[0][1], cells[1][0])
        except Exception as exc:
            raise BootstrapReachabilityError(
                f"Valhalla truck reachability request failed: {exc}"
            ) from exc
        if not all(_reachable(cell) for cell in arcs):
            return {"reachable": False}
        sources = body.get("sources")
        if not isinstance(sources, list) or len(sources) != 2:
            raise BootstrapReachabilityError(
                "Valhalla did not return snapped source coordinates required by the snap bound"
            )
        access = _coordinate(sources[1], 1)
        snap_miles = haversine_miles(
            requested[1]["lat"], requested[1]["lon"],
            float(access["lat"]), float(access.get("lon", access.get("lng"))),
        )
        if snap_miles > self.max_snap_distance_miles:
            return {
                "reachable": False,
                "reason": "snap_distance_exceeded",
                "detail": (
                    f"Valhalla snapped source 1 {snap_miles:.3f} miles; "
                    f"limit is {self.max_snap_distance_miles:.3f} miles"
                ),
            }
        return {
            "reachable": True,
            "road_access_lat": float(access["lat"]),
            "road_access_lng": float(access.get("lon", access.get("lng"))),
            "road_snap_distance_miles": round(snap_miles, 3),
        }


def _reachable(cell: Any) -> bool:
    return bool(
        isinstance(cell, Mapping)
        and not (cell.get("error") or cell.get("error_code"))
        and cell.get("status") not in {"unreachable", "error"}
        and isinstance(cell.get("distance"), (int, float))
        and isinstance(cell.get("time"), (int, float))
    )


def _coordinate(value: Any, index: int) -> Mapping[str, Any]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, Mapping) and isinstance(value.get("location"), Mapping):
        value = value["location"]
    if not isinstance(value, Mapping):
        raise BootstrapReachabilityError(f"Valhalla snapped source {index} is malformed")
    try:
        float(value["lat"])
        float(value.get("lon", value.get("lng")))
    except (KeyError, TypeError, ValueError) as exc:
        raise BootstrapReachabilityError(
            f"Valhalla snapped source {index} has invalid coordinates"
        ) from exc
    return value
