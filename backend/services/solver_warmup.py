from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from ..config import get_route_solver_endpoint


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SolverWarmupService:
    """Process-local, proxy-safe status for asynchronous endpoint wake-up."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self._status: dict[str, Any] = {
            "state": "not_started",
            "configured": bool(get_route_solver_endpoint(required=False)),
            "endpoint": get_route_solver_endpoint(required=False) or None,
            "started_at": None,
            "completed_at": None,
            "error": None,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(self) -> dict[str, Any]:
        endpoint = get_route_solver_endpoint(required=False)
        with self._lock:
            if self._status["state"] == "warming":
                return dict(self._status)
            self._generation += 1
            generation = self._generation
            if not endpoint:
                self._status = {
                    "state": "skipped",
                    "configured": False,
                    "endpoint": None,
                    "started_at": _now(),
                    "completed_at": _now(),
                    "error": None,
                }
                return dict(self._status)
            self._status = {
                "state": "warming",
                "configured": True,
                "endpoint": endpoint,
                "started_at": _now(),
                "completed_at": None,
                "error": None,
            }
        threading.Thread(
            target=self._invoke,
            args=(generation, endpoint),
            name="solver-endpoint-warmup",
            daemon=True,
        ).start()
        return self.status()

    def _invoke(self, generation: int, endpoint: str) -> None:
        try:
            # Use the production adapter so a successful warm-up proves the
            # deployed solver-v2 response contract, not merely HTTP reachability.
            from .solver import solver_service

            solver_service.invoke_endpoint(
                scenario_id="reset-warmup",
                depot_id="warmup-depot",
                delivery_day="2026-01-01",
                planning_depots=[{
                    "depot_id": "warmup-depot",
                    "depot_name": "Warm-up depot",
                    "lat": 30.2672,
                    "lng": -97.7431,
                }],
                planning_customers=[{
                    "customer_id": "warmup-customer",
                    "customer_name": "Warm-up customer",
                    "depot_id": "warmup-depot",
                    "lat": 30.2772,
                    "lng": -97.7331,
                    "service_minutes": 5,
                    "receiving_window_start": "07:00",
                    "receiving_window_end": "12:00",
                    "hard_time_window_flag": True,
                }],
                planning_fleet=[{
                    "vehicle_id": "warmup-vehicle",
                    "depot_id": "warmup-depot",
                    "available_days": "2026-01-01",
                    "capacity_cases": 100,
                    "max_route_minutes": 480,
                    "max_stops_per_route": 10,
                }],
                planning_stops=[{
                    "customer_id": "warmup-customer",
                    "depot_id": "warmup-depot",
                    "delivery_day": "2026-01-01",
                    "route_date": "2026-01-01",
                    "demand_cases": 1,
                }],
                travel_matrix=[
                    {
                        "scenario_id": "reset-warmup", "depot_id": "warmup-depot",
                        "delivery_day": "2026-01-01", "origin_id": "warmup-depot:DEPOT",
                        "destination_id": "warmup-depot:DEPOT", "origin_index": 0,
                        "destination_index": 0, "distance_miles": 0.0, "duration_minutes": 0,
                    },
                    {
                        "scenario_id": "reset-warmup", "depot_id": "warmup-depot",
                        "delivery_day": "2026-01-01", "origin_id": "warmup-depot:DEPOT",
                        "destination_id": "warmup-customer", "origin_index": 0,
                        "destination_index": 1, "distance_miles": 1.0, "duration_minutes": 5,
                    },
                    {
                        "scenario_id": "reset-warmup", "depot_id": "warmup-depot",
                        "delivery_day": "2026-01-01", "origin_id": "warmup-customer",
                        "destination_id": "warmup-depot:DEPOT", "origin_index": 1,
                        "destination_index": 0, "distance_miles": 1.1, "duration_minutes": 6,
                    },
                    {
                        "scenario_id": "reset-warmup", "depot_id": "warmup-depot",
                        "delivery_day": "2026-01-01", "origin_id": "warmup-customer",
                        "destination_id": "warmup-customer", "origin_index": 1,
                        "destination_index": 1, "distance_miles": 0.0, "duration_minutes": 0,
                    },
                ],
                cost_parameters={},
            )
        except Exception as exc:
            state = "failed"
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
        else:
            state = "ready"
            error = None
        with self._lock:
            if generation != self._generation:
                return
            self._status.update(
                state=state,
                completed_at=_now(),
                error=error,
            )


solver_warmup_service = SolverWarmupService()
