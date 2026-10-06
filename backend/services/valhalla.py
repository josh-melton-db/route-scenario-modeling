from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx

from route_opt.matrix import build_nodes, haversine_miles
from route_opt.solver_limits import MAX_SOLVER_POINTS

KM_TO_MILES = 0.621371192237334
PROHIBITED_ARC_DISTANCE_MILES = 1_000_000.0
PROHIBITED_ARC_DURATION_MINUTES = 1_000_000


class ValhallaMatrixError(RuntimeError):
    """Valhalla could not produce a complete matrix for a solver partition."""


class ValhallaSnapDistanceRejected(ValhallaMatrixError):
    """A valid Valhalla response snapped a requested point beyond policy."""

    def __init__(self, index: int, miles: float, max_miles: float) -> None:
        self.index = index
        self.miles = miles
        self.max_miles = max_miles
        super().__init__(
            f"Valhalla snapped source {index} {miles:.3f} miles; "
            f"limit is {max_miles:.3f} miles"
        )


class ValhallaMatrixClient:
    def __init__(
        self,
        base_url: str,
        *,
        costing: str = "truck",
        timeout_seconds: float = 30,
        auth_headers: Callable[[], dict[str, str]] | None = None,
        transport: httpx.BaseTransport | None = None,
        max_snap_distance_miles: float | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.costing = costing
        self.timeout_seconds = timeout_seconds
        self.auth_headers = auth_headers or _databricks_auth_headers
        self.transport = transport
        self.max_snap_distance_miles = max_snap_distance_miles

    def is_bidirectionally_reachable(
        self,
        depot: Mapping[str, object],
        point: Mapping[str, object],
    ) -> bool:
        """Generation/bootstrap validator using the same directed truck graph as solves."""
        return bool(self.inspect_bidirectional_reachability(depot, point)["reachable"])

    def inspect_bidirectional_reachability(
        self,
        depot: Mapping[str, object],
        point: Mapping[str, object],
    ) -> dict[str, object]:
        """Return directed reachability plus bounded road-access provenance."""
        payload = {
            "points": [
                {"lat": float(depot["lat"]), "lon": float(depot.get("lng", depot.get("lon")))},
                {"lat": float(point["lat"]), "lon": float(point.get("lng", point.get("lon")))},
            ],
            "costing": self.costing,
        }
        try:
            with httpx.Client(transport=self.transport) as client:
                response = client.post(
                    f"{self.base_url}/matrix", json=payload,
                    headers=self.auth_headers(), timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                body = response.json()
            cells = body["sources_to_targets"]
            reachable = all(
                isinstance(cell, dict)
                and not _cell_has_error(cell)
                and isinstance(cell.get("distance"), (int, float))
                and isinstance(cell.get("time"), (int, float))
                for cell in (cells[0][1], cells[1][0])
            )
            if not reachable:
                return {"reachable": False}
            access: dict[str, object] = {}
            if self.max_snap_distance_miles is not None:
                try:
                    snapped = _validate_snap_distances(
                        body, payload["points"], self.max_snap_distance_miles
                    )
                except ValhallaSnapDistanceRejected as exc:
                    if exc.index != 1:
                        raise
                    return {
                        "reachable": False,
                        "reason": "snap_distance_exceeded",
                        "detail": str(exc),
                    }
                point_access = snapped[1]
                access = {
                    "road_access_lat": float(point_access["lat"]),
                    "road_access_lng": float(point_access.get("lon", point_access.get("lng"))),
                    "road_snap_distance_miles": round(
                        haversine_miles(
                            float(point["lat"]), float(point.get("lng", point.get("lon"))),
                            float(point_access["lat"]),
                            float(point_access.get("lon", point_access.get("lng"))),
                        ), 3,
                    ),
                }
            return {"reachable": True, **access}
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValhallaMatrixError(f"Valhalla reachability request failed: {exc}") from exc

    def build_travel_matrix(
        self,
        *,
        scenario_id: str,
        depot: dict[str, object],
        stops: list[dict[str, object]],
        delivery_day: str,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        nodes = build_nodes(scenario_id, depot, stops, delivery_day)
        if len(nodes) > MAX_SOLVER_POINTS:
            raise ValhallaMatrixError(
                f"Route matrices support at most {MAX_SOLVER_POINTS} points; "
                f"partition contains {len(nodes)}"
            )
        if len(nodes) == 1:
            node = nodes[0]
            return nodes, [
                {
                    "scenario_id": scenario_id,
                    "depot_id": depot["depot_id"],
                    "delivery_day": delivery_day,
                    "origin_id": node["node_id"],
                    "destination_id": node["node_id"],
                    "origin_index": 0,
                    "destination_index": 0,
                    "distance_miles": 0.0,
                    "duration_minutes": 0,
                    "matrix_source": "valhalla",
                    "distance_method": "road_network",
                    "duration_method": f"valhalla_{self.costing}",
                }
            ]
        payload = {
            "points": [
                {"lat": float(node["lat"]), "lon": float(node["lng"])}
                for node in nodes
            ],
            "costing": self.costing,
        }
        try:
            with httpx.Client(transport=self.transport) as client:
                response = client.post(
                    f"{self.base_url}/matrix",
                    json=payload,
                    headers=self.auth_headers(),
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ValhallaMatrixError(f"Valhalla matrix request failed: {exc}") from exc

        if self.max_snap_distance_miles is not None:
            _validate_snap_distances(body, payload["points"], self.max_snap_distance_miles)

        cells = body.get("sources_to_targets") if isinstance(body, dict) else None
        size = len(nodes)
        if not isinstance(cells, list) or len(cells) != size:
            raise ValhallaMatrixError("Valhalla returned a matrix with the wrong row count")

        rows: list[dict[str, object]] = []
        for origin_index, cell_row in enumerate(cells):
            if not isinstance(cell_row, list) or len(cell_row) != size:
                raise ValhallaMatrixError("Valhalla returned a matrix with the wrong column count")
            for destination_index, cell in enumerate(cell_row):
                miles, minutes, reachable = _cell_metrics(cell, origin_index, destination_index)
                origin = nodes[origin_index]
                destination = nodes[destination_index]
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "depot_id": depot["depot_id"],
                        "delivery_day": delivery_day,
                        "origin_id": origin["node_id"],
                        "destination_id": destination["node_id"],
                        "origin_index": origin_index,
                        "destination_index": destination_index,
                        "distance_miles": round(miles, 3),
                        "duration_minutes": minutes,
                        "matrix_source": "valhalla",
                        "distance_method": "road_network",
                        "duration_method": f"valhalla_{self.costing}",
                        "road_reachable": reachable,
                    }
                )
        return nodes, rows


def _cell_metrics(cell: Any, origin_index: int, destination_index: int) -> tuple[float, int, bool]:
    if not isinstance(cell, dict):
        raise ValhallaMatrixError(f"Valhalla cell {origin_index},{destination_index} is malformed")
    if _cell_has_error(cell):
        return PROHIBITED_ARC_DISTANCE_MILES, PROHIBITED_ARC_DURATION_MINUTES, False
    if origin_index == destination_index:
        return 0.0, 0, True
    distance = cell.get("distance")
    seconds = cell.get("time")
    if not isinstance(distance, (int, float)) or not isinstance(seconds, (int, float)):
        return PROHIBITED_ARC_DISTANCE_MILES, PROHIBITED_ARC_DURATION_MINUTES, False
    return float(distance) * KM_TO_MILES, max(1, round(float(seconds) / 60)), True


def _cell_has_error(cell: Mapping[str, Any]) -> bool:
    return bool(
        cell.get("error")
        or cell.get("error_code")
        or cell.get("status") in {"unreachable", "error"}
    )


def _validate_snap_distances(
    body: Mapping[str, Any], requested: list[dict[str, float]], max_miles: float
) -> list[Mapping[str, Any]]:
    if max_miles < 0:
        raise ValueError("max_snap_distance_miles must be nonnegative")
    snapped = body.get("sources")
    if not isinstance(snapped, list) or len(snapped) != len(requested):
        raise ValhallaMatrixError(
            "Valhalla did not return snapped source coordinates required by the snap bound"
        )
    normalized: list[Mapping[str, Any]] = []
    for index, (source, expected) in enumerate(zip(snapped, requested)):
        source = _snap_coordinate(source, index)
        normalized.append(source)
        try:
            miles = haversine_miles(
                float(expected["lat"]), float(expected["lon"]),
                float(source["lat"]), float(source.get("lon", source.get("lng"))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValhallaMatrixError(
                f"Valhalla snapped source {index} has invalid coordinates"
            ) from exc
        if miles > max_miles:
            raise ValhallaSnapDistanceRejected(index, miles, max_miles)
    return normalized


def _snap_coordinate(value: Any, index: int) -> Mapping[str, Any]:
    """Normalize Valhalla direct, one-element candidate-list, and location shapes."""
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, Mapping) and isinstance(value.get("location"), Mapping):
        value = value["location"]
    if not isinstance(value, Mapping):
        raise ValhallaMatrixError(f"Valhalla snapped source {index} is malformed")
    return value


def _databricks_auth_headers() -> dict[str, str]:
    """Use the route app's injected service-principal credentials for app-to-app OAuth."""
    try:
        from databricks.sdk.core import Config

        headers = Config().authenticate()
    except Exception as exc:
        raise ValhallaMatrixError(f"Could not obtain Databricks app credentials: {exc}") from exc
    if not isinstance(headers, dict):
        raise ValhallaMatrixError("Databricks authentication returned invalid headers")
    return {str(key): str(value) for key, value in headers.items()}
