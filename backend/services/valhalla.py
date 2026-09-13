from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from route_opt.matrix import build_nodes

KM_TO_MILES = 0.621371192237334


class ValhallaMatrixError(RuntimeError):
    """Valhalla could not produce a complete matrix for a solver partition."""


class ValhallaMatrixClient:
    def __init__(
        self,
        base_url: str,
        *,
        costing: str = "truck",
        timeout_seconds: float = 30,
        auth_headers: Callable[[], dict[str, str]] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.costing = costing
        self.timeout_seconds = timeout_seconds
        self.auth_headers = auth_headers or _databricks_auth_headers
        self.transport = transport

    def build_travel_matrix(
        self,
        *,
        scenario_id: str,
        depot: dict[str, object],
        stops: list[dict[str, object]],
        delivery_day: str,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        nodes = build_nodes(scenario_id, depot, stops, delivery_day)
        if len(nodes) > 500:
            raise ValhallaMatrixError(
                f"Valhalla accepts at most 500 points; partition contains {len(nodes)}"
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

        cells = body.get("sources_to_targets") if isinstance(body, dict) else None
        size = len(nodes)
        if not isinstance(cells, list) or len(cells) != size:
            raise ValhallaMatrixError("Valhalla returned a matrix with the wrong row count")

        rows: list[dict[str, object]] = []
        for origin_index, cell_row in enumerate(cells):
            if not isinstance(cell_row, list) or len(cell_row) != size:
                raise ValhallaMatrixError("Valhalla returned a matrix with the wrong column count")
            for destination_index, cell in enumerate(cell_row):
                miles, minutes = _cell_metrics(cell, origin_index, destination_index)
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
                    }
                )
        return nodes, rows


def _cell_metrics(cell: Any, origin_index: int, destination_index: int) -> tuple[float, int]:
    if not isinstance(cell, dict):
        raise ValhallaMatrixError(f"Valhalla cell {origin_index},{destination_index} is malformed")
    if origin_index == destination_index:
        return 0.0, 0
    distance = cell.get("distance")
    seconds = cell.get("time")
    if not isinstance(distance, (int, float)) or not isinstance(seconds, (int, float)):
        status = cell.get("status", "unreachable")
        raise ValhallaMatrixError(
            f"Valhalla cell {origin_index},{destination_index} is unreachable ({status})"
        )
    return float(distance) * KM_TO_MILES, max(1, round(float(seconds) / 60))


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
