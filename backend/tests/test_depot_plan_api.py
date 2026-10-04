from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.depot_plan_models import OverrideRequest
from backend.main import api_app, app
from backend.routes.depot_plans import get_depot_plan_service


def _cost_breakdown() -> dict[str, float]:
    return {
        "mileage_cost": 10,
        "labor_cost": 20,
        "overtime_cost": 0,
        "fixed_vehicle_cost": 30,
        "sla_penalty_cost": 0,
        "carrier_linehaul_cost": 0,
        "carrier_lane_cost": 0,
        "carrier_stop_cost": 0,
        "carrier_minimum_adjustment": 0,
        "fuel_surcharge_cost": 0,
        "accessorial_cost": 0,
        "volume_tier_adjustment": 0,
        "commitment_adjustment": 0,
        "total_cost": 60,
    }


def _kpis() -> dict[str, object]:
    return {
        "route_count": 1,
        "driver_count": 1,
        "vehicle_count": 1,
        "total_miles": 12,
        "drive_minutes": 30,
        "service_minutes": 20,
        "total_cases": 10,
        "avg_stops_per_route": 1,
        "avg_capacity_utilization_pct": 50,
        "avg_driver_utilization_pct": 25,
        "overtime_minutes": 0,
        "missed_windows": 0,
        "late_minutes": 0,
        "total_revenue": 100,
        "profit": 40,
        "cost_breakdown": _cost_breakdown(),
    }


def _day_result(result_id: str = "RES-1") -> dict[str, object]:
    return {
        "result_id": result_id,
        "service_date": "2026-09-30",
        "status": "completed",
        "routes": [],
        "kpis": _kpis(),
        "assigned_cases": 10,
        "routed_cases": 10,
        "unserved_cases": 0,
        "diagnostics": [],
        "matrix_source": "haversine_circuity",
        "created_at": "2026-09-30T12:00:00+00:00",
    }


def _plan_set(route_scenario_id: str = "default") -> dict[str, object]:
    scenarios = [
        {
            "route_scenario_id": "default",
            "scenario_name": "Optimized default",
            "is_default": True,
        }
    ]
    if route_scenario_id != "default":
        scenarios.append(
            {
                "route_scenario_id": route_scenario_id,
                "scenario_name": "Extra driver",
                "is_default": False,
            }
        )
    return {
        "plan_set_id": "DPS-1",
        "parent_run_id": "RUN-1",
        "depot": {
            "depot_id": "DPT-1",
            "name": "Dallas",
            "region": "TOLA",
            "sales_territory": "Texas",
            "location": {"lat": 32.8, "lng": -96.8},
        },
        "horizon_start": "2026-09-30",
        "horizon_end": "2026-10-01",
        "route_scenario_id": route_scenario_id,
        "scenarios": scenarios,
        "days": [
            {
                "service_date": "2026-09-30",
                "status": "completed",
                "default_status": "completed",
                "assigned_cases": 10,
                "routed_cases": 10,
                "unserved_cases": 0,
                "total_cost": 60,
                "is_overridden": route_scenario_id != "default",
                "selected_result_id": "RES-1",
                "error": None,
            }
        ],
        "coverage": {
            "total_days": 2,
            "solved_days": 1,
            "queued_days": 1,
            "running_days": 0,
            "failed_days": 0,
        },
        "kpis": _kpis(),
        "is_partial": True,
        "resource_source": "synthetic_fixed_fleet",
    }


def _day_detail(route_scenario_id: str = "default") -> dict[str, object]:
    result = _day_result()
    return {
        "plan_set_id": "DPS-1",
        "service_date": "2026-09-30",
        "route_scenario_id": route_scenario_id,
        "default_status": "completed",
        "override_status": (
            "queued" if route_scenario_id != "default" else None
        ),
        "default_result": result,
        "selected_result": result,
        "error": None,
    }


class FakeDepotPlanService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _call(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def get_or_create_plan(
        self, run_id: str, depot_id: str, priority_date: str | None = None
    ) -> dict[str, object]:
        self._call("get_or_create_plan", run_id, depot_id, priority_date)
        if run_id == "missing":
            raise HTTPException(status_code=404, detail="Network run not found.")
        return _plan_set()

    def get_plan(
        self, plan_set_id: str, route_scenario_id: str = "default"
    ) -> dict[str, object]:
        self._call("get_plan", plan_set_id, route_scenario_id)
        return _plan_set(route_scenario_id)

    def get_day(
        self,
        plan_set_id: str,
        service_date: str,
        route_scenario_id: str = "default",
    ) -> dict[str, object]:
        self._call("get_day", plan_set_id, service_date, route_scenario_id)
        return _day_detail(route_scenario_id)

    def list_day_results(
        self, plan_set_id: str, service_date: str, *, limit: int, offset: int
    ) -> dict[str, object]:
        self._call("list_day_results", plan_set_id, service_date, limit=limit, offset=offset)
        return {"items": [_day_result("RES-2")], "total": 3, "limit": limit, "offset": offset}

    def list_result_routes(
        self, plan_set_id: str, result_id: str, *, limit: int, offset: int
    ) -> dict[str, object]:
        self._call("list_result_routes", plan_set_id, result_id, limit=limit, offset=offset)
        if result_id == "missing":
            raise KeyError("Unknown depot result 'missing'.")
        return {"items": [{"route_id": "ROUTE-2"}], "total": 2, "limit": limit, "offset": offset}

    def create_scenario(
        self, plan_set_id: str, scenario_name: str
    ) -> dict[str, object]:
        self._call("create_scenario", plan_set_id, scenario_name)
        return {
            "route_scenario_id": "SCN-1",
            "scenario_name": scenario_name,
            "is_default": False,
        }

    def optimize_day(
        self, plan_set_id: str, service_date: str, request: OverrideRequest
    ) -> dict[str, object]:
        self._call("optimize_day", plan_set_id, service_date, request)
        return _day_detail(request.route_scenario_id)

    def reset_day_override(
        self, plan_set_id: str, route_scenario_id: str, service_date: str
    ) -> dict[str, object]:
        self._call(
            "reset_day_override", plan_set_id, route_scenario_id, service_date
        )
        return _day_detail(route_scenario_id)


@pytest.fixture
def fake_service() -> FakeDepotPlanService:
    service = FakeDepotPlanService()
    api_app.dependency_overrides[get_depot_plan_service] = lambda: service
    yield service
    api_app.dependency_overrides.pop(get_depot_plan_service, None)


def test_depot_plan_routes_delegate_with_exact_contract(
    fake_service: FakeDepotPlanService,
) -> None:
    client = TestClient(app)

    created = client.post(
        "/api/network/runs/RUN-1/depots/DPT-1/plans",
        params={"priority_date": "2026-09-30"},
    )
    assert created.status_code == 200
    assert created.json()["route_scenario_id"] == "default"

    summary = client.get(
        "/api/depot-plans/DPS-1", params={"route_scenario_id": "SCN-1"}
    )
    assert summary.status_code == 200
    assert summary.json()["route_scenario_id"] == "SCN-1"

    day = client.get(
        "/api/depot-plans/DPS-1/days/2026-09-30",
        params={"route_scenario_id": "default"},
    )
    assert day.status_code == 200
    assert day.json()["service_date"] == "2026-09-30"

    scenario = client.post(
        "/api/depot-plans/DPS-1/scenarios", json={"scenario_name": " Extra driver "}
    )
    assert scenario.status_code == 201
    assert scenario.json() == {
        "route_scenario_id": "SCN-1",
        "scenario_name": "Extra driver",
        "is_default": False,
    }

    optimized = client.post(
        "/api/depot-plans/DPS-1/days/2026-09-30/optimize",
        json={"route_scenario_id": "SCN-1", "driver_delta": 1},
    )
    assert optimized.status_code == 202
    assert optimized.json()["override_status"] == "queued"

    reset = client.delete(
        "/api/depot-plans/DPS-1/scenarios/SCN-1/days/2026-09-30"
    )
    assert reset.status_code == 200

    assert fake_service.calls[0] == (
        "get_or_create_plan",
        ("RUN-1", "DPT-1", "2026-09-30"),
        {},
    )
    assert fake_service.calls[3] == (
        "create_scenario",
        ("DPS-1", "Extra driver"),
        {},
    )


def test_routes_reject_invalid_dates_default_override_and_blank_name(
    fake_service: FakeDepotPlanService,
) -> None:
    client = TestClient(app)

    assert (
        client.post(
            "/api/network/runs/RUN-1/depots/DPT-1/plans",
            params={"priority_date": "09-30-2026"},
        ).status_code
        == 422
    )
    assert (
        client.get("/api/depot-plans/DPS-1/days/not-a-date").status_code == 422
    )
    assert (
        client.post(
            "/api/depot-plans/DPS-1/days/2026-09-30/optimize",
            json={"route_scenario_id": "default"},
        ).status_code
        == 422
    )
    assert (
        client.delete(
            "/api/depot-plans/DPS-1/scenarios/default/days/2026-09-30"
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/depot-plans/DPS-1/scenarios", json={"scenario_name": "   "}
        ).status_code
        == 422
    )


def test_service_404_is_preserved(fake_service: FakeDepotPlanService) -> None:
    response = TestClient(app).post(
        "/api/network/runs/missing/depots/DPT-1/plans"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Network run not found."


def test_depot_result_and_route_history_pagination_contract(
    fake_service: FakeDepotPlanService,
) -> None:
    client = TestClient(app)

    results = client.get(
        "/api/depot-plans/DPS-1/days/2026-09-30/results",
        params={"limit": 2, "offset": 1},
    )
    assert results.status_code == 200
    assert results.json()["total"] == 3
    assert results.json()["limit"] == 2
    assert results.json()["offset"] == 1

    routes = client.get(
        "/api/depot-plans/DPS-1/results/RES-2/routes",
        params={"limit": 1, "offset": 1},
    )
    assert routes.status_code == 200
    assert routes.json()["items"] == [{"route_id": "ROUTE-2"}]
    assert fake_service.calls[-1] == (
        "list_result_routes",
        ("DPS-1", "RES-2"),
        {"limit": 1, "offset": 1},
    )

    assert client.get(
        "/api/depot-plans/DPS-1/results/missing/routes"
    ).status_code == 404
    assert client.get(
        "/api/depot-plans/DPS-1/days/2026-09-30/results",
        params={"limit": 101},
    ).status_code == 422
    assert client.get(
        "/api/depot-plans/DPS-1/results/RES-2/routes",
        params={"offset": -1},
    ).status_code == 422
