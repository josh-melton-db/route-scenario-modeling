from __future__ import annotations

import math
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any, cast

from fastapi import HTTPException

from route_opt.network_flow import solve_fixed_capacity_network
from route_opt.rates import contract_status, quote_contract

from ..config import get_data_backend
from ..models import (
    NetworkFlowChargeDetail,
    NetworkOverviewContext,
    NetworkScenario,
    NetworkScenarioAssumptions,
    NetworkScenarioCreateRequest,
    NetworkScenarioException,
    NetworkScenarioKpiDeltas,
    NetworkScenarioResult,
    NetworkScenarioRunResponse,
    NetworkScenarioUpdateRequest,
    NetworkScenarioValidation,
    NetworkScenarioValidationIssue,
    RateChargeLine,
    RateContractDetail,
)
from .lakebase_store import lakebase_store
from .network_overview import (
    NetworkRows,
    estimate_lane_daily_cost,
    network_overview_service,
)
from .rates import list_rate_contract_details
from .store_provider import get_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_value(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"{", "["}:
        import json

        return json.loads(value)
    return value


class NetworkScenarioRepository:
    """Lakebase-backed scenario state with an in-memory local fallback."""

    def __init__(self) -> None:
        self._scenarios: dict[str, NetworkScenario] = {}
        self._results: dict[str, NetworkScenarioResult] = {}
        self._lock = threading.RLock()

    @property
    def _uses_lakebase(self) -> bool:
        return get_data_backend() == "lakebase"

    def _table(self, name: str) -> str:
        return lakebase_store.postgres.qualified_table(name)

    @staticmethod
    def _scenario_from_row(row: dict[str, Any]) -> NetworkScenario:
        return NetworkScenario.model_validate(
            {
                **row,
                "assumptions": _json_value(row["assumptions"]),
                "validation": _json_value(row.get("validation")),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "solved_at": (
                    str(row["solved_at"]) if row.get("solved_at") else None
                ),
            }
        )

    def list(self) -> list[NetworkScenario]:
        if not self._uses_lakebase:
            with self._lock:
                return sorted(
                    (row.model_copy(deep=True) for row in self._scenarios.values()),
                    key=lambda row: row.updated_at,
                    reverse=True,
                )
        rows = lakebase_store.postgres.query(
            f"SELECT * FROM {self._table('network_scenarios')} "
            "ORDER BY updated_at DESC"
        )
        return [self._scenario_from_row(row) for row in rows]

    def get(self, scenario_id: str) -> NetworkScenario:
        if not self._uses_lakebase:
            with self._lock:
                scenario = self._scenarios.get(scenario_id)
                if scenario is None:
                    raise HTTPException(
                        status_code=404, detail="Network scenario not found."
                    )
                return scenario.model_copy(deep=True)
        row = lakebase_store.postgres.query_one(
            f"SELECT * FROM {self._table('network_scenarios')} "
            "WHERE scenario_id = %s",
            (scenario_id,),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Network scenario not found.")
        return self._scenario_from_row(row)

    def create(self, scenario: NetworkScenario) -> NetworkScenario:
        if not self._uses_lakebase:
            with self._lock:
                self._scenarios[scenario.scenario_id] = scenario.model_copy(deep=True)
            return scenario
        lakebase_store.postgres.execute(
            f"""
            INSERT INTO {self._table('network_scenarios')} (
              scenario_id, scenario_name, baseline_scenario_id,
              demand_plan_version_id, capacity_plan_version_id,
              horizon_start, horizon_end, region_id, status, revision,
              assumptions, validation, created_at, updated_at, solved_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s)
            """,
            (
                scenario.scenario_id,
                scenario.scenario_name,
                scenario.baseline_scenario_id,
                scenario.demand_plan_version_id,
                scenario.capacity_plan_version_id,
                scenario.horizon_start,
                scenario.horizon_end,
                scenario.region_id,
                scenario.status,
                scenario.revision,
                lakebase_store.postgres.jsonb(
                    scenario.assumptions.model_dump(mode="json")
                ),
                None,
                scenario.created_at,
                scenario.updated_at,
                None,
            ),
        )
        return scenario

    def save(self, scenario: NetworkScenario, *, clear_result: bool = False) -> None:
        if not self._uses_lakebase:
            with self._lock:
                self._scenarios[scenario.scenario_id] = scenario.model_copy(deep=True)
                if clear_result:
                    self._results.pop(scenario.scenario_id, None)
            return
        with lakebase_store.postgres.transaction() as connection:
            lakebase_store.postgres.execute(
                f"""
                UPDATE {self._table('network_scenarios')}
                SET scenario_name = %s, status = %s, revision = %s,
                    assumptions = %s, validation = %s, updated_at = %s,
                    solved_at = %s
                WHERE scenario_id = %s
                """,
                (
                    scenario.scenario_name,
                    scenario.status,
                    scenario.revision,
                    lakebase_store.postgres.jsonb(
                        scenario.assumptions.model_dump(mode="json")
                    ),
                    (
                        lakebase_store.postgres.jsonb(
                            scenario.validation.model_dump(mode="json")
                        )
                        if scenario.validation
                        else None
                    ),
                    scenario.updated_at,
                    scenario.solved_at,
                    scenario.scenario_id,
                ),
                connection=connection,
            )
            if clear_result:
                for table_name in (
                    "network_flow_results",
                    "network_flow_charge_details",
                    "network_scenario_exceptions",
                    "network_scenario_results",
                ):
                    lakebase_store.postgres.execute(
                        f"DELETE FROM {self._table(table_name)} WHERE scenario_id = %s",
                        (scenario.scenario_id,),
                        connection=connection,
                    )

    def delete(self, scenario_id: str) -> None:
        if not self._uses_lakebase:
            with self._lock:
                self._scenarios.pop(scenario_id, None)
                self._results.pop(scenario_id, None)
            return
        with lakebase_store.postgres.transaction() as connection:
            for table_name in (
                "network_flow_results",
                "network_flow_charge_details",
                "network_scenario_exceptions",
                "network_scenario_results",
                "network_scenarios",
            ):
                lakebase_store.postgres.execute(
                    f"DELETE FROM {self._table(table_name)} WHERE scenario_id = %s",
                    (scenario_id,),
                    connection=connection,
                )

    def result(self, scenario_id: str) -> NetworkScenarioResult:
        if not self._uses_lakebase:
            with self._lock:
                result = self._results.get(scenario_id)
                if result is None:
                    raise HTTPException(
                        status_code=404,
                        detail="This network scenario has not been solved yet.",
                    )
                return result.model_copy(deep=True)
        row = lakebase_store.postgres.query_one(
            f"SELECT result_payload FROM {self._table('network_scenario_results')} "
            "WHERE scenario_id = %s",
            (scenario_id,),
        )
        if row is None:
            raise HTTPException(
                status_code=404, detail="This network scenario has not been solved yet."
            )
        return NetworkScenarioResult.model_validate(_json_value(row["result_payload"]))

    def save_result(
        self,
        scenario: NetworkScenario,
        result: NetworkScenarioResult,
        *,
        flow_rows: list[dict[str, Any]],
        cost_rows: list[dict[str, Any]],
    ) -> None:
        if not self._uses_lakebase:
            with self._lock:
                self._scenarios[scenario.scenario_id] = scenario.model_copy(deep=True)
                self._results[scenario.scenario_id] = result.model_copy(deep=True)
            return
        cost_by_key = {
            (str(row["service_date"]), str(row["lane_id"])): row
            for row in cost_rows
        }
        with lakebase_store.postgres.transaction() as connection:
            self.save(scenario)
            for table_name in (
                "network_flow_results",
                "network_flow_charge_details",
                "network_scenario_exceptions",
            ):
                lakebase_store.postgres.execute(
                    f"DELETE FROM {self._table(table_name)} WHERE scenario_id = %s",
                    (scenario.scenario_id,),
                    connection=connection,
                )
            lakebase_store.postgres.execute(
                f"""
                INSERT INTO {self._table('network_scenario_results')} (
                  scenario_id, revision, result_payload, generated_at
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (scenario_id) DO UPDATE SET
                  revision = EXCLUDED.revision,
                  result_payload = EXCLUDED.result_payload,
                  generated_at = EXCLUDED.generated_at
                """,
                (
                    scenario.scenario_id,
                    scenario.revision,
                    lakebase_store.postgres.jsonb(result.model_dump(mode="json")),
                    result.generated_at,
                ),
                connection=connection,
            )
            lakebase_store.postgres.executemany(
                f"""
                INSERT INTO {self._table('network_flow_results')} (
                  scenario_id, revision, service_date, lane_id, lane_type,
                  assigned_units, total_cost, rate_source, contract_id,
                  contract_version_id, rate_book_snapshot_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        scenario.scenario_id,
                        scenario.revision,
                        str(row["service_date"]),
                        str(row["lane_id"]),
                        str(row["lane_type"]),
                        int(row["assigned_units"]),
                        float(
                            cost_by_key.get(
                                (str(row["service_date"]), str(row["lane_id"])),
                                {},
                            ).get("total_cost", 0)
                        ),
                        cost_by_key.get(
                            (str(row["service_date"]), str(row["lane_id"])), {}
                        ).get("rate_source"),
                        cost_by_key.get(
                            (str(row["service_date"]), str(row["lane_id"])), {}
                        ).get("contract_id"),
                        cost_by_key.get(
                            (str(row["service_date"]), str(row["lane_id"])), {}
                        ).get("contract_version_id"),
                        cost_by_key.get(
                            (str(row["service_date"]), str(row["lane_id"])), {}
                        ).get("rate_book_snapshot_id"),
                    )
                    for row in flow_rows
                ],
                connection=connection,
            )
            lakebase_store.postgres.executemany(
                f"""
                INSERT INTO {self._table('network_flow_charge_details')} (
                  scenario_id, revision, service_date, lane_id, payload
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        scenario.scenario_id,
                        scenario.revision,
                        row.service_date,
                        row.lane_id,
                        lakebase_store.postgres.jsonb(row.model_dump(mode="json")),
                    )
                    for row in result.charge_details
                ],
                connection=connection,
            )
            lakebase_store.postgres.executemany(
                f"""
                INSERT INTO {self._table('network_scenario_exceptions')} (
                  scenario_id, revision, exception_id, payload
                ) VALUES (%s, %s, %s, %s)
                """,
                [
                    (
                        scenario.scenario_id,
                        scenario.revision,
                        row.exception_id,
                        lakebase_store.postgres.jsonb(row.model_dump(mode="json")),
                    )
                    for row in result.exceptions
                ],
                connection=connection,
            )


class NetworkScenarioService:
    def __init__(self, repository: NetworkScenarioRepository | None = None) -> None:
        self.repository = repository or NetworkScenarioRepository()

    def list(self) -> list[NetworkScenario]:
        return self.repository.list()

    def get(self, scenario_id: str) -> NetworkScenario:
        return self.repository.get(scenario_id)

    def create(self, request: NetworkScenarioCreateRequest) -> NetworkScenario:
        name = request.scenario_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Scenario name is required.")
        now = _now()
        scenario = NetworkScenario(
            scenario_id=f"NSC_{uuid.uuid4().hex[:10].upper()}",
            scenario_name=name,
            baseline_scenario_id=request.baseline_scenario_id,
            demand_plan_version_id=request.demand_plan_version_id,
            capacity_plan_version_id=request.capacity_plan_version_id,
            horizon_start=request.horizon_start,
            horizon_end=request.horizon_end,
            region_id=request.region_id,
            assumptions=request.assumptions,
            created_at=now,
            updated_at=now,
        )
        self._validate_input_references(scenario)
        return self.repository.create(scenario)

    def update(
        self, scenario_id: str, request: NetworkScenarioUpdateRequest
    ) -> NetworkScenario:
        scenario = self.get(scenario_id)
        if scenario.status == "published":
            raise HTTPException(
                status_code=409, detail="Published network scenarios are immutable."
            )
        name = (
            request.scenario_name.strip()
            if request.scenario_name is not None
            else scenario.scenario_name
        )
        if not name:
            raise HTTPException(status_code=422, detail="Scenario name is required.")
        changed = name != scenario.scenario_name or (
            request.assumptions is not None
            and request.assumptions != scenario.assumptions
        )
        updated = scenario.model_copy(
            update={
                "scenario_name": name,
                "assumptions": request.assumptions or scenario.assumptions,
                "status": "draft" if changed else scenario.status,
                "revision": scenario.revision + 1 if changed else scenario.revision,
                "validation": None if changed else scenario.validation,
                "updated_at": _now(),
                "solved_at": None if changed else scenario.solved_at,
            }
        )
        self._validate_input_references(updated)
        self.repository.save(updated, clear_result=changed)
        return updated

    def _rows(self, scenario: NetworkScenario) -> NetworkRows:
        return network_overview_service.load_rows(
            demand_plan_version_id=scenario.demand_plan_version_id,
            capacity_plan_version_id=scenario.capacity_plan_version_id,
            horizon_start=date.fromisoformat(scenario.horizon_start),
            horizon_end=date.fromisoformat(scenario.horizon_end),
        )

    def _validate_input_references(self, scenario: NetworkScenario) -> None:
        options = network_overview_service.get_options()
        demand = next(
            (
                row
                for row in options.demand_plans
                if row.plan_version_id == scenario.demand_plan_version_id
            ),
            None,
        )
        capacity = next(
            (
                row
                for row in options.capacity_plans
                if row.plan_version_id == scenario.capacity_plan_version_id
            ),
            None,
        )
        if demand is None:
            raise HTTPException(status_code=404, detail="Demand plan version not found.")
        if capacity is None:
            raise HTTPException(status_code=404, detail="Capacity plan version not found.")
        if scenario.region_id not in {row.region_id for row in options.regions}:
            raise HTTPException(status_code=404, detail="Network region not found.")
        if scenario.horizon_end < scenario.horizon_start:
            raise HTTPException(
                status_code=422, detail="Horizon end must not precede start."
            )
        if (
            scenario.horizon_start < demand.horizon_start
            or scenario.horizon_end > demand.horizon_end
            or scenario.horizon_start < capacity.horizon_start
            or scenario.horizon_end > capacity.horizon_end
        ):
            raise HTTPException(
                status_code=422,
                detail="Scenario horizon must be covered by both published input plans.",
            )

    def validate(self, scenario_id: str) -> NetworkScenario:
        scenario = self.get(scenario_id)
        self._validate_input_references(scenario)
        rows = self._rows(scenario)
        facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
        lanes = {str(row["lane_id"]): row for row in rows["dim_network_lanes"]}
        assumptions = scenario.assumptions
        issues: list[NetworkScenarioValidationIssue] = []

        for facility_id in assumptions.disabled_facility_ids:
            if facility_id not in facilities:
                issues.append(
                    NetworkScenarioValidationIssue(
                        severity="error",
                        code="unknown_facility",
                        scope="facility",
                        entity_id=facility_id,
                        message="Disabled facility does not exist in the canonical network.",
                    )
                )
        changed_lane_ids = set(assumptions.disabled_lane_ids) | set(
            assumptions.lane_cost_adjustments_pct
        )
        for lane_id in changed_lane_ids:
            lane = lanes.get(lane_id)
            if lane is None:
                issues.append(
                    NetworkScenarioValidationIssue(
                        severity="error",
                        code="unknown_lane",
                        scope="lane",
                        entity_id=lane_id,
                        message="Changed lane does not exist in the canonical network.",
                    )
                )
            elif str(lane["lane_type"]) != "LINEHAUL":
                issues.append(
                    NetworkScenarioValidationIssue(
                        severity="error",
                        code="unsupported_lane_layer",
                        scope="lane",
                        entity_id=lane_id,
                        message="Network scenario lane changes currently apply to linehaul only.",
                    )
                )

        if len(assumptions.disabled_facility_ids) == len(facilities):
            issues.append(
                NetworkScenarioValidationIssue(
                    severity="warning",
                    code="all_facilities_disabled",
                    scope="scenario",
                    message="All facilities are disabled; all demand will be reported unmet.",
                )
            )

        non_gl_lanes = {
            str(row["lane_id"])
            for row in rows["dim_network_lanes"]
            if row["lane_type"] == "LINEHAUL"
            and str(facilities[str(row["origin_endpoint_id"])]["region_id"])
            != "REGION_GREAT_LAKES"
        }
        if non_gl_lanes:
            issues.append(
                NetworkScenarioValidationIssue(
                    severity="warning",
                    code="planning_rate_fallback",
                    scope="rate",
                    message=(
                        f"{len(non_gl_lanes)} permitted linehaul lanes do not have a "
                        "published canonical rate-book match and will use an explicit "
                        "planning fallback."
                    ),
                )
            )
        errors = [row for row in issues if row.severity == "error"]
        validation = NetworkScenarioValidation(
            valid=not errors,
            issues=issues,
            summary=(
                f"Ready to solve with {len(issues)} advisory issue(s)."
                if not errors
                else f"Resolve {len(errors)} blocking validation issue(s)."
            ),
            validated_at=_now(),
        )
        updated = scenario.model_copy(
            update={
                "status": "validated" if validation.valid else "draft",
                "validation": validation,
                "updated_at": _now(),
            }
        )
        self.repository.save(updated)
        return updated

    def delete(self, scenario_id: str) -> None:
        self.get(scenario_id)
        self.repository.delete(scenario_id)

    def result(self, scenario_id: str) -> NetworkScenarioResult:
        self.get(scenario_id)
        return self.repository.result(scenario_id)

    @staticmethod
    def _governed_contract(
        contracts: list[RateContractDetail], service_date: str
    ) -> RateContractDetail | None:
        candidates = [
            row
            for row in contracts
            if row.contract_id == "GL_STANDARD_2026"
            and contract_status(row.model_dump(mode="json"), service_date)
            == "published"
        ]
        return max(candidates, key=lambda row: row.version.version_number, default=None)

    def _rate_flows(
        self,
        rows: NetworkRows,
        flow_rows: list[dict[str, Any]],
    ) -> tuple[
        list[dict[str, Any]],
        list[NetworkFlowChargeDetail],
        list[NetworkScenarioException],
    ]:
        lanes = {str(row["lane_id"]): row for row in rows["dim_network_lanes"]}
        facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
        contracts = list_rate_contract_details(get_store())
        cost_rows: list[dict[str, Any]] = []
        charge_details: list[NetworkFlowChargeDetail] = []
        missing_rate_lanes: set[str] = set()

        for flow in flow_rows:
            assigned = int(flow["assigned_units"])
            lane_id = str(flow["lane_id"])
            service_date = str(flow["service_date"])
            lane = lanes[lane_id]
            total_cost = estimate_lane_daily_cost(lane, assigned)
            rate_source = "planning_fallback"
            contract_id = None
            contract_version_id = None
            snapshot_id = None

            if lane["lane_type"] == "LINEHAUL" and assigned > 0:
                loads = max(1, math.ceil(assigned / 900))
                origin = facilities[str(lane["origin_endpoint_id"])]
                contract = (
                    self._governed_contract(contracts, service_date)
                    if str(origin["region_id"]) == "REGION_GREAT_LAKES"
                    else None
                )
                charge_lines: list[RateChargeLine] = []
                if contract is not None:
                    quote = quote_contract(
                        contract.model_dump(mode="json"),
                        {
                            "service_date": service_date,
                            "origin": str(lane["origin_endpoint_id"]),
                            "destination": str(lane["destination_endpoint_id"]),
                            "miles": float(lane["distance_miles"]),
                            "stops": 1,
                            "cases": min(assigned, 900),
                            "period_volume": loads,
                            "commitment_policy": "honor",
                        },
                    )
                    if quote["matched_lane_rule_id"]:
                        total_cost = round(float(quote["total_cost"]) * loads, 2)
                        rate_source = "governed_contract"
                        contract_id = contract.contract_id
                        contract_version_id = contract.version.version_id
                        snapshot_id = str(quote["rate_book_snapshot_id"])
                        charge_lines = [
                            RateChargeLine.model_validate(
                                {
                                    **line,
                                    "formula": f"{loads} loads × ({line['formula']})",
                                    "quantity": float(line["quantity"]) * loads,
                                    "amount": round(float(line["amount"]) * loads, 2),
                                }
                            )
                            for line in cast(list[dict[str, Any]], quote["charge_lines"])
                        ]
                if rate_source == "planning_fallback":
                    missing_rate_lanes.add(lane_id)
                    linehaul_per_load = max(
                        450.0, float(lane["distance_miles"]) * 3.4
                    )
                    base = linehaul_per_load * loads
                    fuel = base * 0.12
                    charge_lines = [
                        RateChargeLine(
                            category="mileage",
                            label="Planning linehaul estimate",
                            formula=(
                                f"{loads} loads × max($450, "
                                f"{float(lane['distance_miles']):,.1f} mi × $3.40)"
                            ),
                            quantity=loads,
                            unit="load",
                            rate=round(linehaul_per_load, 4),
                            amount=round(base, 2),
                            rule_id="PLANNING_LINEHAUL_FALLBACK",
                        ),
                        RateChargeLine(
                            category="fuel",
                            label="Planning fuel estimate",
                            formula=f"12% × ${base:,.2f}",
                            quantity=base,
                            unit="USD",
                            rate=12,
                            amount=round(fuel, 2),
                            rule_id="PLANNING_FUEL_FALLBACK",
                        ),
                    ]
                charge_details.append(
                    NetworkFlowChargeDetail(
                        service_date=service_date,
                        lane_id=lane_id,
                        assigned_units=assigned,
                        loads=loads,
                        rate_source=cast(Any, rate_source),
                        contract_id=contract_id,
                        contract_version_id=contract_version_id,
                        rate_book_snapshot_id=snapshot_id,
                        total_cost=total_cost,
                        charge_lines=charge_lines,
                    )
                )

            cost_rows.append(
                {
                    "service_date": service_date,
                    "lane_id": lane_id,
                    "total_cost": round(total_cost, 2),
                    "rate_source": rate_source,
                    "contract_id": contract_id,
                    "contract_version_id": contract_version_id,
                    "rate_book_snapshot_id": snapshot_id,
                }
            )

        exceptions = [
            NetworkScenarioException(
                exception_id=f"RATE_{lane_id}",
                exception_type="missing_rate",
                severity="warning",
                entity_type="lane",
                entity_id=lane_id,
                message=(
                    "No published canonical linehaul rate matched; the stored "
                    "planning fallback charge lines were used."
                ),
            )
            for lane_id in sorted(missing_rate_lanes)
        ]
        return cost_rows, charge_details, exceptions

    def run(self, scenario_id: str) -> NetworkScenarioRunResponse:
        scenario = self.get(scenario_id)
        if scenario.status != "validated" or not (
            scenario.validation and scenario.validation.valid
        ):
            scenario = self.validate(scenario_id)
        if not scenario.validation or not scenario.validation.valid:
            raise HTTPException(
                status_code=409,
                detail="Resolve blocking validation issues before running the plan.",
            )
        rows = self._rows(scenario)
        allocation = solve_fixed_capacity_network(
            rows,
            demand_plan_version_id=scenario.demand_plan_version_id,
            capacity_plan_version_id=scenario.capacity_plan_version_id,
            horizon_start=scenario.horizon_start,
            horizon_end=scenario.horizon_end,
            region_id=scenario.region_id,
            disabled_facility_ids=set(
                scenario.assumptions.disabled_facility_ids
            ),
            disabled_lane_ids=set(scenario.assumptions.disabled_lane_ids),
            lane_cost_adjustments_pct=(
                scenario.assumptions.lane_cost_adjustments_pct
            ),
            unmet_penalty_per_case=(
                scenario.assumptions.unmet_penalty_per_case
            ),
        )
        flow_rows = allocation["flow_rows"]
        cost_rows, charges, exceptions = self._rate_flows(rows, flow_rows)
        for unmet in allocation["unmet_rows"]:
            if int(unmet["unmet_units"]) <= 0:
                continue
            exceptions.append(
                NetworkScenarioException(
                    exception_id=(
                        f"UNMET_{unmet['service_date']}_{unmet['depot_id']}"
                    ),
                    exception_type="unmet_demand",
                    severity="critical",
                    service_date=str(unmet["service_date"]),
                    entity_type="facility",
                    entity_id=str(unmet["depot_id"]),
                    message=(
                        f"{int(unmet['unmet_units']):,} cases cannot be assigned "
                        "within supplied facility and lane capacity."
                    ),
                    demand_units=int(unmet["demand_units"]),
                    assigned_units=int(unmet["assigned_units"]),
                    unmet_units=int(unmet["unmet_units"]),
                )
            )

        context = NetworkOverviewContext(
            scenario_id=scenario.scenario_id,
            demand_plan_version_id=scenario.demand_plan_version_id,
            capacity_plan_version_id=scenario.capacity_plan_version_id,
            horizon_start=scenario.horizon_start,
            horizon_end=scenario.horizon_end,
            region_id=scenario.region_id,
            lane_type="LINEHAUL",
            metric="assigned_flow",
        )
        baseline = network_overview_service.build_overview(
            rows, context=context.model_copy(update={"scenario_id": "baseline"})
        )
        scenario_rows = dict(rows)
        scenario_rows["baseline_network_flow_daily"] = flow_rows
        scenario_rows["network_flow_cost_daily"] = cost_rows
        overview = network_overview_service.build_overview(
            scenario_rows, context=context, scenario_id=scenario.scenario_id
        )
        deltas = NetworkScenarioKpiDeltas(
            **{
                field: round(
                    getattr(overview.kpis, field)
                    - getattr(baseline.kpis, field),
                    2,
                )
                for field in (
                    "demand_units",
                    "assigned_units",
                    "unmet_units",
                    "total_cost",
                    "cost_per_unit",
                    "on_time_pct",
                    "utilization_pct",
                )
            }
        )
        baseline_by_key = {
            (str(row["service_date"]), str(row["lane_id"])): int(
                row["assigned_units"]
            )
            for row in rows["baseline_network_flow_daily"]
        }
        lane_destinations = {
            str(row["lane_id"]): str(row["destination_endpoint_id"])
            for row in rows["dim_network_lanes"]
            if row["lane_type"] == "LINEHAUL"
            and str(row["destination_endpoint_id"]).startswith("DPT_")
        }
        affected = sorted(
            {
                lane_destinations[str(row["lane_id"])]
                for row in flow_rows
                if str(row["lane_id"]) in lane_destinations
                and int(row["assigned_units"])
                != baseline_by_key.get(
                    (str(row["service_date"]), str(row["lane_id"])), 0
                )
            }
        )
        generated_at = _now()
        result = NetworkScenarioResult(
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            generated_at=generated_at,
            overview=overview,
            baseline_overview=baseline,
            kpi_deltas=deltas,
            affected_depot_ids=affected,
            charge_details=charges,
            exceptions=exceptions,
        )
        solved = scenario.model_copy(
            update={
                "status": "solved",
                "updated_at": generated_at,
                "solved_at": generated_at,
            }
        )
        self.repository.save_result(
            solved,
            result,
            flow_rows=flow_rows,
            cost_rows=cost_rows,
        )
        return NetworkScenarioRunResponse(scenario=solved, result=result)


network_scenario_service = NetworkScenarioService()
