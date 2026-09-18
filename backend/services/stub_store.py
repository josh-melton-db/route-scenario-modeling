from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from route_opt.rates import contract_detail_from_legacy, contract_status, quote_contract

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
    Carrier,
    CarrierContract,
    RateContractCreateRequest,
    RateContractDetail,
    RateDraftUpdateRequest,
    RateChargeLine,
    RateVersionCreateRequest,
    OperatingParameterSet,
    CostParameterSet,
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

        # Make the modeled demo results discoverable through the same scenario
        # listing used by Scenario History and the Analyze selectors. Previously
        # these files could be opened by ID but were absent from /api/scenarios.
        seeded_result_ids: set[str] = set()
        for spec in self._scenario_types:
            result_stub_id = spec.result_stub_id
            if (
                spec.scenario_type in {"baseline", "custom"}
                or result_stub_id in seeded_result_ids
            ):
                continue
            raw = self._scenario_raw.get(result_stub_id)
            if raw is None:
                continue
            seeded_result_ids.add(result_stub_id)
            raw_status = str(raw.get("status", "succeeded"))
            status = "infeasible" if raw_status == "infeasible" else "completed"
            parameters = {
                field.name: field.default
                for field in spec.fields
                if field.default is not None
            }
            self._scenario_registry[result_stub_id] = ScenarioDefinition(
                scenario_id=result_stub_id,
                scenario_name=str(raw.get("scenario_name", spec.label)),
                scenario_type=spec.scenario_type,
                baseline_scenario_id="baseline",
                depot_id=self._baseline_network.depot.depot_id,
                delivery_day=self._baseline_network.delivery_day,
                parameters=parameters,
                status=status,
            )
            self._result_registry[result_stub_id] = result_stub_id
            self._scenario_created_at[result_stub_id] = str(
                raw.get("generated_at", datetime.now(timezone.utc).isoformat())
            )

        self._carriers = [
            Carrier(carrier_id="GL_LOGISTICS", carrier_name="Great Lakes Logistics"),
            Carrier(carrier_id="MIDWEST_EXPRESS", carrier_name="Midwest Express"),
        ]
        self._carrier_contracts = [
            CarrierContract(contract_id="GL_STANDARD_2026", carrier_id="GL_LOGISTICS", contract_name="GL Standard 2026", capacity_stops=12, rate_per_mile=4.25, rate_per_stop=45, minimum_charge=350, fuel_surcharge_pct=12, effective_start="2026-01-01", effective_end="2026-12-31"),
            CarrierContract(contract_id="GL_PRIORITY_2026", carrier_id="GL_LOGISTICS", contract_name="GL Priority 2026", capacity_stops=20, rate_per_mile=5.10, rate_per_stop=55, minimum_charge=425, fuel_surcharge_pct=10, effective_start="2026-01-01", effective_end="2026-12-31"),
            CarrierContract(contract_id="MW_SPOT_2026", carrier_id="MIDWEST_EXPRESS", contract_name="Midwest Spot 2026", capacity_stops=8, rate_per_mile=4.70, rate_per_stop=50, minimum_charge=400, fuel_surcharge_pct=14, effective_start="2026-01-01", effective_end="2026-12-31"),
        ]
        carrier_names = {row.carrier_id: row.carrier_name for row in self._carriers}
        self._rate_contract_details: dict[tuple[str, str], RateContractDetail] = {}
        for contract in self._carrier_contracts:
            detail = RateContractDetail.model_validate(
                contract_detail_from_legacy(
                    contract.model_dump(mode="json"),
                    carrier_names[contract.carrier_id],
                )
            )
            self._rate_contract_details[(contract.contract_id, detail.version.version_id)] = detail

    def list_depots(self) -> list[Depot]:
        return [self._baseline_network.depot]

    def list_days(self) -> list[str]:
        return [self._baseline_network.delivery_day]

    def list_scenario_types(self) -> list[ScenarioTypeSpec]:
        return self._scenario_types

    def list_carriers(self) -> list[Carrier]:
        return [row.model_copy(deep=True) for row in self._carriers]

    def list_carrier_contracts(self) -> list[CarrierContract]:
        return [row.model_copy(deep=True) for row in self._carrier_contracts]

    def list_rate_contract_details(self) -> list[RateContractDetail]:
        return [row.model_copy(deep=True) for row in self._rate_contract_details.values()]

    def create_rate_contract(
        self, request: RateContractCreateRequest
    ) -> RateContractDetail:
        carrier = next(
            (row for row in self._carriers if row.carrier_id == request.carrier_id),
            None,
        )
        if carrier is None:
            raise HTTPException(status_code=404, detail="Carrier not found.")
        stem = re.sub(r"[^A-Z0-9]+", "_", request.contract_name.upper()).strip("_")
        contract_id = f"{(stem or 'CONTRACT')[:28]}_{uuid.uuid4().hex[:6].upper()}"
        version_id = f"{contract_id}_V1"
        now = datetime.now(timezone.utc).isoformat()
        detail = RateContractDetail(
            contract_id=contract_id,
            carrier_id=carrier.carrier_id,
            carrier_name=carrier.carrier_name,
            contract_name=request.contract_name.strip(),
            version={
                "version_id": version_id,
                "version_number": 1,
                "status": "draft",
                "currency": request.currency.strip().upper(),
                "effective_start": request.effective_start,
                "effective_end": request.effective_end,
                "change_reason": "Initial contract",
            },
            lane_rates=[],
            fuel_surcharges=[],
            accessorials=[],
            volume_tiers=[],
            capacity_commitments=[],
            source="Local rate book",
            freshness_at=now,
        )
        self._rate_contract_details[(contract_id, version_id)] = detail
        self._carrier_contracts.append(
            CarrierContract(
                contract_id=contract_id,
                carrier_id=carrier.carrier_id,
                contract_name=detail.contract_name,
                capacity_stops=0,
                rate_per_mile=0,
                rate_per_stop=0,
                minimum_charge=0,
                fuel_surcharge_pct=0,
                effective_start=request.effective_start,
                effective_end=request.effective_end,
            )
        )
        return detail.model_copy(deep=True)

    def create_rate_version(
        self, contract_id: str, request: RateVersionCreateRequest
    ) -> RateContractDetail:
        versions = [
            detail
            for (current_contract_id, _), detail in self._rate_contract_details.items()
            if current_contract_id == contract_id
        ]
        if not versions:
            raise HTTPException(status_code=404, detail="Rate contract not found.")
        if any(row.version.status == "draft" for row in versions):
            raise HTTPException(
                status_code=409,
                detail="This contract already has a draft. Open or discard it before creating another version.",
            )
        source = next(
            (
                row
                for row in versions
                if request.source_version_id
                and row.version.version_id == request.source_version_id
            ),
            None,
        )
        if request.source_version_id and source is None:
            raise HTTPException(status_code=404, detail="Source contract version not found.")
        source = source or max(versions, key=lambda row: row.version.version_number)
        version_number = max(row.version.version_number for row in versions) + 1
        version_id = f"{contract_id}_V{version_number}"

        def clone(rules: list[Any], family: str) -> list[Any]:
            return [
                rule.model_copy(update={"rule_id": f"{version_id}_{family}_{index + 1}"})
                for index, rule in enumerate(rules)
            ]

        detail = source.model_copy(
            deep=True,
            update={
                "version": source.version.model_copy(
                    update={
                        "version_id": version_id,
                        "version_number": version_number,
                        "status": "draft",
                        "effective_start": request.effective_start,
                        "effective_end": request.effective_end,
                        "published_at": None,
                        "published_by": None,
                        "change_reason": request.change_reason.strip(),
                    }
                ),
                "lane_rates": clone(source.lane_rates, "LANE"),
                "fuel_surcharges": clone(source.fuel_surcharges, "FUEL"),
                "accessorials": clone(source.accessorials, "ACC"),
                "volume_tiers": clone(source.volume_tiers, "TIER"),
                "capacity_commitments": clone(source.capacity_commitments, "COMMIT"),
                "version_history": [],
                "freshness_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._rate_contract_details[(contract_id, version_id)] = detail
        return detail.model_copy(deep=True)

    def replace_rate_draft(
        self,
        contract_id: str,
        version_id: str,
        request: RateDraftUpdateRequest,
    ) -> RateContractDetail:
        key = (contract_id, version_id)
        detail = self._rate_contract_details.get(key)
        if detail is None:
            raise HTTPException(status_code=404, detail="Rate contract version not found.")
        if detail.version.status != "draft":
            raise HTTPException(status_code=409, detail="Published versions are immutable.")
        updated = detail.model_copy(
            deep=True,
            update={
                "contract_name": request.contract_name.strip(),
                "version": detail.version.model_copy(
                    update={
                        "currency": request.currency.strip().upper(),
                        "effective_start": request.effective_start,
                        "effective_end": request.effective_end,
                        "change_reason": request.change_reason.strip(),
                    }
                ),
                "lane_rates": [row.model_copy(deep=True) for row in request.lane_rates],
                "fuel_surcharges": [row.model_copy(deep=True) for row in request.fuel_surcharges],
                "accessorials": [row.model_copy(deep=True) for row in request.accessorials],
                "volume_tiers": [row.model_copy(deep=True) for row in request.volume_tiers],
                "capacity_commitments": [row.model_copy(deep=True) for row in request.capacity_commitments],
                "freshness_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._rate_contract_details[key] = updated
        self._carrier_contracts = [
            row.model_copy(update={"contract_name": updated.contract_name})
            if row.contract_id == contract_id
            else row
            for row in self._carrier_contracts
        ]
        return updated.model_copy(deep=True)

    def publish_rate_draft(
        self, contract_id: str, version_id: str, published_by: str
    ) -> RateContractDetail:
        key = (contract_id, version_id)
        draft = self._rate_contract_details.get(key)
        if draft is None:
            raise HTTPException(status_code=404, detail="Rate contract version not found.")
        if draft.version.status != "draft":
            raise HTTPException(status_code=409, detail="Only a draft can be published.")
        draft_start = date.fromisoformat(draft.version.effective_start or "")
        draft_end = date.fromisoformat(draft.version.effective_end or "")
        for other_key, other in list(self._rate_contract_details.items()):
            if other.contract_id != contract_id or other.version.status != "published":
                continue
            other_start = date.fromisoformat(other.version.effective_start) if other.version.effective_start else date.min
            other_end = date.fromisoformat(other.version.effective_end) if other.version.effective_end else date.max
            if not (draft_start <= other_end and other_start <= draft_end):
                continue
            if other_start >= draft_start:
                raise HTTPException(
                    status_code=409,
                    detail=f"Effective dates overlap published version {other.version.version_number}.",
                )
            self._rate_contract_details[other_key] = other.model_copy(
                deep=True,
                update={
                    "version": other.version.model_copy(
                        update={
                            "effective_end": (draft_start - timedelta(days=1)).isoformat(),
                        }
                    ),
                    "freshness_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        published = draft.model_copy(
            deep=True,
            update={
                "version": draft.version.model_copy(
                    update={
                        "status": "published",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                        "published_by": published_by,
                    }
                ),
                "freshness_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._rate_contract_details[key] = published
        lane = published.lane_rates[0]
        fuel = published.fuel_surcharges[0] if published.fuel_surcharges else None
        commitment = published.capacity_commitments[0] if published.capacity_commitments else None
        self._carrier_contracts = [
            row.model_copy(
                update={
                    "contract_name": published.contract_name,
                    "capacity_stops": int(commitment.capacity_quantity if commitment else row.capacity_stops),
                    "rate_per_mile": lane.rate_per_mile,
                    "rate_per_stop": lane.rate_per_stop,
                    "minimum_charge": lane.minimum_charge,
                    "fuel_surcharge_pct": fuel.rate_pct if fuel else 0,
                    "effective_start": published.version.effective_start,
                    "effective_end": published.version.effective_end,
                }
            )
            if row.contract_id == contract_id
            else row
            for row in self._carrier_contracts
        ]
        return published.model_copy(deep=True)

    def delete_rate_draft(self, contract_id: str, version_id: str) -> None:
        key = (contract_id, version_id)
        detail = self._rate_contract_details.get(key)
        if detail is None:
            raise HTTPException(status_code=404, detail="Rate contract version not found.")
        if detail.version.status != "draft":
            raise HTTPException(status_code=409, detail="Published versions cannot be discarded.")
        del self._rate_contract_details[key]
        if not any(key_contract == contract_id for key_contract, _ in self._rate_contract_details):
            self._carrier_contracts = [
                row for row in self._carrier_contracts if row.contract_id != contract_id
            ]

    def list_operating_parameters(self) -> list[OperatingParameterSet]:
        return [OperatingParameterSet(parameter_set_id="default", parameter_set_name="Standard delivery operations", private_vehicle_limit=4, max_route_minutes=600, max_stops_per_route=8, allow_overtime=True)]

    def list_cost_parameters(self) -> list[CostParameterSet]:
        return [CostParameterSet(parameter_set_id="default", cost_per_mile=3, labor_regular_hour=80, overtime_multiplier=1.5, overtime_threshold_minutes=480, fixed_truck_daily_cost=340, max_route_minutes=600, late_delivery_penalty=75, missed_delivery_penalty=400, avg_speed_mph=38, circuity=1.3)]

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

    def delete_scenario(self, scenario_id: str) -> None:
        if scenario_id == "baseline":
            raise HTTPException(status_code=400, detail="The baseline scenario cannot be deleted.")
        if scenario_id not in self._scenario_registry:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        del self._scenario_registry[scenario_id]
        self._result_registry.pop(scenario_id, None)
        self._scenario_created_at.pop(scenario_id, None)

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
        scenario_routes = self._build_scenario_routes(
            variant, scenario_id_for_response, scenario_depot
        )
        if scenario is not None:
            scenario_routes = self._apply_stub_rate_model(raw, scenario, scenario_routes)
        raw["scenario_routes"] = [route.model_dump() for route in scenario_routes]
        raw["transportation_allocation"] = self._transportation_allocation(scenario_routes)
        raw["decision_explanations"] = [
            {
                "customer_id": stop.customer_id,
                "customer_name": stop.customer_name,
                "decision": "Outsourced Carrier",
                "reason": route.decision_reason,
            }
            for route in scenario_routes
            if route.fulfillment_method == "carrier"
            for stop in route.stops
        ]
        return ComparisonResult.model_validate(raw)

    def _apply_stub_rate_model(
        self,
        raw: dict[str, Any],
        scenario: ScenarioDefinition,
        routes: list[Route],
    ) -> list[Route]:
        choices_raw = scenario.parameters.get("transportation_choices")
        choices = choices_raw if isinstance(choices_raw, dict) else {}
        if not choices.get("allow_carrier") or not routes:
            return routes
        pricing_raw = scenario.parameters.get("pricing_context")
        pricing = pricing_raw if isinstance(pricing_raw, dict) else {}
        service_date = str(pricing.get("service_date") or "2026-09-16")
        period_volume = float(pricing.get("projected_period_stops", 54) or 54)
        details_by_contract: dict[str, list[RateContractDetail]] = {}
        for detail in self.list_rate_contract_details():
            details_by_contract.setdefault(detail.contract_id, []).append(detail)
        locked_contract = str(choices.get("contract_id") or "")
        allowed_carriers = {
            str(value)
            for value in choices.get("eligible_carrier_ids", [])
            if value
        }
        if choices.get("carrier_id"):
            allowed_carriers.add(str(choices["carrier_id"]))
        target = routes[-1]
        candidates: list[tuple[float, dict[str, object]]] = []
        for contract in self.list_carrier_contracts():
            if locked_contract and str(choices.get("contract_selection", "locked")) == "locked" and contract.contract_id != locked_contract:
                continue
            if allowed_carriers and contract.carrier_id not in allowed_carriers:
                continue
            effective_details = [
                row
                for row in details_by_contract.get(contract.contract_id, [])
                if contract_status(row.model_dump(mode="json"), service_date)
                == "published"
            ]
            if not effective_details:
                continue
            detail_model = max(
                effective_details, key=lambda row: row.version.version_number
            )
            detail = detail_model.model_dump(mode="json")
            quote = quote_contract(
                detail,
                {
                    "contract_id": contract.contract_id,
                    "version_id": detail["version"]["version_id"],
                    "service_date": service_date,
                    "origin": scenario.depot_id,
                    "destination": "North Metro",
                    "miles": target.total_miles,
                    "stops": len(target.stops),
                    "cases": target.total_cases,
                    "period_volume": period_volume,
                    "accessorial_codes": choices.get("accessorial_codes", []),
                },
            )
            if quote["eligible"]:
                candidates.append((float(quote["total_cost"]), quote))
        if not candidates:
            return routes
        _, quote = min(candidates, key=lambda item: item[0])
        lines = quote["charge_lines"]

        def line_total(*categories: str) -> float:
            return round(
                sum(
                    float(line["amount"])
                    for line in lines
                    if str(line["category"]) in categories
                ),
                2,
            )

        rated = target.model_copy(
            update={
                "total_cost": float(quote["total_cost"]),
                "fulfillment_method": "carrier",
                "carrier_name": str(quote["carrier_name"]),
                "contract_name": str(quote["contract_name"]),
                "contract_version_id": str(quote["contract_version_id"]),
                "rated_service_date": service_date,
                "rate_lane": str(quote["matched_lane"]),
                "rate_book_snapshot_id": str(quote["rate_book_snapshot_id"]),
                "carrier_charge_lines": [
                    RateChargeLine.model_validate(line) for line in lines
                ],
                "decision_reason": "Private-fleet capacity was exhausted; selected the lowest eligible published carrier quote.",
            }
        )
        updated_routes = [*routes[:-1], rated]
        scenario_kpis = raw.get("scenario_kpis")
        if isinstance(scenario_kpis, dict):
            breakdown = scenario_kpis.get("cost_breakdown")
            if isinstance(breakdown, dict):
                private_keys = [
                    "mileage_cost",
                    "labor_cost",
                    "overtime_cost",
                    "fixed_vehicle_cost",
                    "sla_penalty_cost",
                ]
                private_total = sum(float(breakdown.get(key, 0)) for key in private_keys)
                removal_ratio = min(1.0, target.total_cost / private_total) if private_total else 0
                for key in private_keys:
                    breakdown[key] = round(float(breakdown.get(key, 0)) * (1 - removal_ratio), 2)
                breakdown.update(
                    {
                        "carrier_linehaul_cost": line_total("lane", "mileage", "minimum"),
                        "carrier_lane_cost": line_total("lane"),
                        "carrier_stop_cost": line_total("stops"),
                        "carrier_minimum_adjustment": line_total("minimum"),
                        "fuel_surcharge_cost": line_total("fuel"),
                        "accessorial_cost": line_total("accessorial"),
                        "volume_tier_adjustment": line_total("volume_tier"),
                        "commitment_adjustment": line_total("commitment"),
                    }
                )
                new_total = round(
                    sum(float(breakdown.get(key, 0)) for key in private_keys)
                    + line_total(
                        "lane",
                        "mileage",
                        "stops",
                        "volume_tier",
                        "minimum",
                        "fuel",
                        "accessorial",
                        "commitment",
                    ),
                    2,
                )
                breakdown["total_cost"] = new_total
                scenario_kpis["profit"] = round(
                    float(scenario_kpis.get("total_revenue", 0)) - new_total, 2
                )
                baseline_total = self._baseline_kpis.cost_breakdown.total_cost
                deltas = raw.get("kpi_deltas")
                if isinstance(deltas, dict):
                    deltas["total_cost"] = round(new_total - baseline_total, 2)
                    deltas["profit"] = round(
                        float(scenario_kpis["profit"]) - self._baseline_kpis.profit, 2
                    )
                    for key in (
                        "carrier_linehaul_cost",
                        "carrier_lane_cost",
                        "carrier_stop_cost",
                        "carrier_minimum_adjustment",
                        "fuel_surcharge_cost",
                        "accessorial_cost",
                        "volume_tier_adjustment",
                        "commitment_adjustment",
                    ):
                        deltas[key] = breakdown[key]
        raw["rate_book_snapshot_id"] = quote["rate_book_snapshot_id"]
        return updated_routes

    @staticmethod
    def _transportation_allocation(routes: list[Route]) -> list[dict[str, object]]:
        labels = {
            "private_fleet": "Private fleet",
            "private_overtime": "Private overtime",
            "carrier": "Outsourced carrier",
        }
        rows: list[dict[str, object]] = []
        for method, label in labels.items():
            selected = [route for route in routes if route.fulfillment_method == method]
            rows.append(
                {
                    "fulfillment_method": method,
                    "label": label,
                    "deliveries": sum(len(route.stops) for route in selected),
                    "cases": sum(route.total_cases for route in selected),
                    "miles": round(sum(route.total_miles for route in selected), 1),
                    "cost": round(sum(route.total_cost for route in selected), 2),
                }
            )
        rows.append(
            {
                "fulfillment_method": "unserved",
                "label": "Unserved",
                "deliveries": 0,
                "cases": 0,
                "miles": 0,
                "cost": 0,
            }
        )
        return rows

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
