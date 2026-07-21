from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..config import get_stub_dir
from ..models import (
    BaselineNetwork,
    ComparisonResult,
    Depot,
    Kpis,
    LatLng,
    Route,
    ScenarioCreateRequest,
    ScenarioDefinition,
    ScenarioHistoryItem,
    ScenarioLifecycleStatus,
    ScenarioTypeSpec,
    Stop,
    ValidationResponse,
)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _route_with_scenario(route: Route, scenario_id: str, depot: Depot | None = None) -> Route:
    data = route.model_dump()
    data["scenario_id"] = scenario_id
    if depot is not None:
        data["depot_id"] = depot.depot_id
        data["path"] = [depot.location.model_dump()] + [
            stop["location"] for stop in data["stops"]
        ] + [depot.location.model_dump()]
    return Route.model_validate(data)


def _build_route(
    *,
    route_id: str,
    scenario_id: str,
    route_name: str,
    depot: Depot,
    driver_num: int,
    stops: list[Stop],
    total_miles: float,
    drive_minutes: int,
    total_cost: float,
    capacity_cases: int,
    overtime_minutes: int,
) -> Route:
    service_minutes = sum(stop.service_minutes for stop in stops)
    total_cases = sum(stop.demand_cases for stop in stops)
    path = [depot.location] + [stop.location for stop in stops] + [depot.location]
    return Route(
        route_id=route_id,
        scenario_id=scenario_id,
        route_name=route_name,
        depot_id=depot.depot_id,
        driver_id=f"DRV-{driver_num:03d}",
        driver_name=f"Driver {driver_num}",
        vehicle_id=f"VEH-{driver_num:03d}",
        delivery_day="Tuesday",
        path=path,
        stops=stops,
        total_miles=total_miles,
        drive_minutes=drive_minutes,
        service_minutes=service_minutes,
        total_cases=total_cases,
        capacity_cases=capacity_cases,
        capacity_utilization_pct=round(total_cases / capacity_cases * 100, 1),
        driver_utilization_pct=96.0 if overtime_minutes else 88.0,
        overtime_minutes=overtime_minutes,
        missed_windows=0,
        late_minutes=0,
        total_cost=total_cost,
    )


class StubStore:
    def __init__(self, stub_dir: Path | None = None):
        self.stub_dir = stub_dir or get_stub_dir()
        self._depots = [Depot.model_validate(row) for row in _read_json(self.stub_dir / "depots.json")]
        self._scenario_types = [
            ScenarioTypeSpec.model_validate(row)
            for row in _read_json(self.stub_dir / "scenario_types.json")
        ]
        self._baseline_network = BaselineNetwork.model_validate(
            _read_json(self.stub_dir / "baseline" / "network.json")
        )
        self._baseline_kpis = Kpis.model_validate(
            _read_json(self.stub_dir / "baseline" / "kpis.json")
        )
        self._scenario_raw: dict[str, dict[str, Any]] = {}
        scenarios_dir = self.stub_dir / "scenarios"
        for path in sorted(scenarios_dir.glob("*.json")):
            self._scenario_raw[path.stem] = _read_json(path)

        self._scenario_registry: dict[str, ScenarioDefinition] = {
            "baseline": ScenarioDefinition(
                scenario_id="baseline",
                scenario_name="Baseline",
                scenario_type="baseline",
                baseline_scenario_id="baseline",
                depot_id=self._baseline_network.depot.depot_id,
                delivery_day=self._baseline_network.delivery_day,
                parameters={},
                status="completed",
            )
        }
        self._result_registry: dict[str, str] = {"baseline": "scn_baseline_identity"}
        self._scenario_created_at: dict[str, str] = {}

    def list_depots(self) -> list[Depot]:
        return [self._baseline_network.depot]

    def list_days(self) -> list[str]:
        return [self._baseline_network.delivery_day]

    def list_scenario_types(self) -> list[ScenarioTypeSpec]:
        return self._scenario_types

    def list_recent_scenarios(self, limit: int = 10) -> list[ScenarioHistoryItem]:
        scenarios = [
            scenario
            for scenario_id, scenario in reversed(self._scenario_registry.items())
            if scenario_id != "baseline"
        ][:limit]
        return [
            ScenarioHistoryItem(
                **scenario.model_dump(),
                created_at=self._scenario_created_at[scenario.scenario_id],
                has_results=scenario.scenario_id in self._result_registry,
            )
            for scenario in scenarios
        ]

    def get_baseline_network(self, depot_id: str, delivery_day: str) -> BaselineNetwork:
        if depot_id != self._baseline_network.depot.depot_id:
            raise HTTPException(status_code=404, detail="Baseline depot not found in stubs.")
        if delivery_day != self._baseline_network.delivery_day:
            raise HTTPException(status_code=404, detail="Baseline day not found in stubs.")
        return self._baseline_network

    def get_baseline_kpis(self, depot_id: str, delivery_day: str) -> Kpis:
        self.get_baseline_network(depot_id, delivery_day)
        return self._baseline_kpis

    def create_scenario(self, payload: ScenarioCreateRequest) -> tuple[ScenarioDefinition, str]:
        spec = self._spec_for(payload.scenario_type)
        scenario_id = f"scn_{uuid.uuid4().hex[:12]}"
        scenario = ScenarioDefinition(
            scenario_id=scenario_id,
            scenario_name=payload.scenario_name,
            scenario_type=payload.scenario_type,
            baseline_scenario_id=payload.baseline_scenario_id,
            depot_id=payload.depot_id,
            delivery_day=payload.delivery_day,
            parameters=payload.parameters,
            status="draft",
        )
        self._scenario_registry[scenario_id] = scenario
        self._result_registry[scenario_id] = spec.result_stub_id
        self._scenario_created_at[scenario_id] = datetime.now(timezone.utc).isoformat()
        return scenario, spec.result_stub_id

    def get_scenario_definition(self, scenario_id: str) -> ScenarioDefinition:
        scenario = self._scenario_registry.get(scenario_id)
        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        return scenario

    def set_scenario_status(self, scenario_id: str, status: ScenarioLifecycleStatus) -> None:
        scenario = self.get_scenario_definition(scenario_id)
        self._scenario_registry[scenario_id] = scenario.model_copy(update={"status": status})

    def validate_scenario(self, scenario_id: str) -> ValidationResponse:
        scenario = self.get_scenario_definition(scenario_id)
        spec = self._spec_for(scenario.scenario_type)
        missing = [
            field.name
            for field in spec.fields
            if field.required and scenario.parameters.get(field.name) in (None, "")
        ]
        result_stub_id = self._result_registry[scenario_id]
        result_raw = self._raw_result(result_stub_id)
        self.set_scenario_status(scenario_id, "validated" if not missing else "draft")
        return ValidationResponse(
            scenario_id=scenario_id,
            valid=not missing,
            hard_constraints=[],
            soft_penalties=[],
            missing_fields=missing,
            inferred_fields=[],
            estimated_affected_customers=len(result_raw.get("customer_impacts", [])),
            estimated_affected_routes=max(1, abs((result_raw.get("kpi_deltas") or {}).get("route_count", 0))),
            summary=(
                "Scenario parameters are complete and ready to run."
                if not missing
                else "Scenario is missing required fields."
            ),
        )

    def get_target_status(self, scenario_id: str) -> str:
        result_stub_id = self._result_registry.get(scenario_id)
        if not result_stub_id:
            raise HTTPException(status_code=404, detail="Scenario result mapping not found.")
        return str(self._raw_result(result_stub_id)["status"])

    def get_scenario_result(self, scenario_id: str) -> ComparisonResult:
        result_stub_id = self._result_registry.get(scenario_id, scenario_id)
        raw = copy.deepcopy(self._raw_result(result_stub_id))
        scenario = self._scenario_registry.get(scenario_id)
        scenario_id_for_response = scenario.scenario_id if scenario else raw["scenario_id"]
        scenario_name = scenario.scenario_name if scenario else raw["scenario_name"]
        variant = raw.pop("route_variant")
        scenario_depot = Depot.model_validate(raw["scenario_depot"])
        raw["scenario_id"] = scenario_id_for_response
        raw["scenario_name"] = scenario_name
        raw["baseline_depot"] = self._baseline_network.depot.model_dump()
        raw["baseline_routes"] = [route.model_dump() for route in self._baseline_network.routes]
        raw["baseline_kpis"] = self._baseline_kpis.model_dump()
        raw["scenario_routes"] = [
            route.model_dump()
            for route in self._build_scenario_routes(variant, scenario_id_for_response, scenario_depot)
        ]
        return ComparisonResult.model_validate(raw)

    def _spec_for(self, scenario_type: str) -> ScenarioTypeSpec:
        for spec in self._scenario_types:
            if spec.scenario_type == scenario_type:
                return spec
        raise HTTPException(status_code=404, detail="Scenario type not found.")

    def _raw_result(self, result_stub_id: str) -> dict[str, Any]:
        raw = self._scenario_raw.get(result_stub_id)
        if not raw:
            raise HTTPException(status_code=404, detail="Scenario result stub not found.")
        return raw

    def _build_scenario_routes(
        self,
        variant: str,
        scenario_id: str,
        scenario_depot: Depot,
    ) -> list[Route]:
        baseline_routes = self._baseline_network.routes
        if variant in {"baseline_identity", "day_change"}:
            routes = [_route_with_scenario(route, scenario_id, scenario_depot) for route in baseline_routes]
            if variant == "day_change":
                moved_ids = {"CUST-003", "CUST-006", "CUST-010", "CUST-015", "CUST-020", "CUST-023"}
                changed = []
                for route in routes:
                    data = route.model_dump()
                    for stop in data["stops"]:
                        if stop["customer_id"] in moved_ids:
                            stop["delivery_day"] = "Thursday"
                    data["delivery_day"] = "Tuesday / Thursday"
                    changed.append(Route.model_validate(data))
                return changed
            return routes

        if variant == "facility_move":
            return [_route_with_scenario(route, scenario_id, scenario_depot) for route in baseline_routes]

        if variant == "driver_minus_one":
            stops = [stop for route in baseline_routes for stop in route.stops]
            chunks = [stops[0:8], stops[8:16], stops[16:24]]
            specs = [
                ("RTE-001", "Route 1 Consolidated", 1, 100, 149, 1595, 1080, 35),
                ("RTE-002", "Route 2 Consolidated", 2, 99, 148, 1580, 1040, 40),
                ("RTE-003", "Route 3 Consolidated", 3, 102, 151, 1631, 1040, 43),
            ]
            return [
                _build_route(
                    route_id=route_id,
                    scenario_id=scenario_id,
                    route_name=name,
                    depot=scenario_depot,
                    driver_num=driver_num,
                    stops=chunk,
                    total_miles=miles,
                    drive_minutes=drive,
                    total_cost=cost,
                    capacity_cases=capacity,
                    overtime_minutes=overtime,
                )
                for (route_id, name, driver_num, miles, drive, cost, capacity, overtime), chunk in zip(specs, chunks)
            ]

        if variant == "new_customers":
            routes = [_route_with_scenario(route, scenario_id, scenario_depot) for route in baseline_routes]
            new_stops = [
                Stop(stop_id="STP-901", customer_id="CUST-901", customer_name="Meadowbrook Foods", sequence=1, location=LatLng(lat=42.5537, lng=-83.0284), demand_cases=105, service_minutes=25, time_window_start="08:00", time_window_end="12:00", arrival_time="08:32", departure_time="08:57", delivery_day="Tuesday", is_new_customer=True),
                Stop(stop_id="STP-902", customer_id="CUST-902", customer_name="Creekside Market", sequence=2, location=LatLng(lat=42.5902, lng=-82.9861), demand_cases=95, service_minutes=25, time_window_start="09:00", time_window_end="13:00", arrival_time="09:28", departure_time="09:53", delivery_day="Tuesday", is_new_customer=True),
                Stop(stop_id="STP-903", customer_id="CUST-903", customer_name="Prairie Grocery", sequence=3, location=LatLng(lat=42.6194, lng=-83.0702), demand_cases=100, service_minutes=25, time_window_start="10:00", time_window_end="14:00", arrival_time="10:31", departure_time="10:56", delivery_day="Tuesday", is_new_customer=True),
                Stop(stop_id="STP-904", customer_id="CUST-904", customer_name="Townline Retail", sequence=4, location=LatLng(lat=42.5746, lng=-83.1517), demand_cases=100, service_minutes=25, time_window_start="11:00", time_window_end="15:00", arrival_time="11:48", departure_time="12:13", delivery_day="Tuesday", is_new_customer=True),
            ]
            routes.append(
                _build_route(
                    route_id="RTE-005",
                    scenario_id=scenario_id,
                    route_name="Route 5",
                    depot=scenario_depot,
                    driver_num=5,
                    stops=new_stops,
                    total_miles=48,
                    drive_minutes=74,
                    total_cost=969,
                    capacity_cases=600,
                    overtime_minutes=7,
                )
            )
            return routes

        return [_route_with_scenario(route, scenario_id, scenario_depot) for route in baseline_routes]


store = StubStore()
