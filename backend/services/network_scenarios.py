from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, cast

from fastapi import HTTPException

from route_opt.network_flow import solve_fixed_capacity_network

from ..config import get_data_backend
from ..models import (
    NetworkFlowChargeDetail,
    NetworkOverviewContext,
    NetworkScenario,
    NetworkScenarioAssumptions,
    NetworkScenarioCreateRequest,
    NetworkScenarioException,
    NetworkScenarioKpiDeltas,
    NetworkPricingContext,
    NetworkRateCoverage,
    NetworkScenarioResult,
    NetworkScenarioRunResponse,
    NetworkReleaseOverlay,
    NetworkScenarioUpdateRequest,
    NetworkScenarioValidation,
    NetworkScenarioValidationIssue,
    NetworkTariffRule,
    RateContractDetail,
)
from .lakebase_store import lakebase_store
from .network_overview import NetworkRows, network_overview_service
from .network_rating import (
    objective_lane_unit_costs, rate_network_flows, resolve_network_tariffs,
)
from .network_run_snapshots import NetworkRunSnapshot
from .network_assignment_projection import merge_assignment_overlays
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
        self._run_snapshots: dict[str, NetworkRunSnapshot] = {}
        self._lock = threading.RLock()

    @property
    def _uses_lakebase(self) -> bool:
        return get_data_backend() == "lakebase"

    def _table(self, name: str) -> str:
        return lakebase_store.postgres.qualified_table(name)

    @staticmethod
    def _scenario_from_row(row: dict[str, Any]) -> NetworkScenario:
        assumptions = _json_value(row["assumptions"])
        return NetworkScenario.model_validate(
            {
                **row,
                "horizon_start": str(row["horizon_start"]),
                "horizon_end": str(row["horizon_end"]),
                "source_baseline_revision_id": row.get("source_baseline_revision_id") or assumptions.get("source_baseline_revision_id"),
                "assumptions": assumptions,
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

    def run_snapshot(self, run_id: str) -> NetworkRunSnapshot:
        if not self._uses_lakebase:
            with self._lock:
                snapshot = self._run_snapshots.get(run_id)
                if snapshot is None:
                    raise HTTPException(status_code=404, detail="Network run not found.")
                return snapshot.copy()
        row = lakebase_store.postgres.query_one(
            f"SELECT scenario_payload, result_payload, network_rows_payload, "
            f"flow_rows_payload, cost_rows_payload "
            f"FROM {self._table('network_run_snapshots')} WHERE run_id = %s",
            (run_id,),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Network run not found.")
        return NetworkRunSnapshot(
            scenario=NetworkScenario.model_validate(_json_value(row["scenario_payload"])),
            result=NetworkScenarioResult.model_validate(
                _json_value(row["result_payload"])
            ),
            network_rows=cast(
                NetworkRows, _json_value(row["network_rows_payload"])
            ),
            flow_rows=cast(
                list[dict[str, Any]], _json_value(row["flow_rows_payload"])
            ),
            cost_rows=cast(
                list[dict[str, Any]], _json_value(row["cost_rows_payload"])
            ),
        )

    def save_result(
        self,
        scenario: NetworkScenario,
        result: NetworkScenarioResult,
        *,
        network_rows: NetworkRows,
        flow_rows: list[dict[str, Any]],
        cost_rows: list[dict[str, Any]],
    ) -> None:
        if not result.run_id:
            raise ValueError("A solved network result must have a run ID.")
        snapshot = NetworkRunSnapshot(
            scenario=scenario.model_copy(deep=True),
            result=result.model_copy(deep=True),
            network_rows=deepcopy(network_rows),
            flow_rows=deepcopy(flow_rows),
            cost_rows=deepcopy(cost_rows),
        )
        if not self._uses_lakebase:
            with self._lock:
                self._scenarios[scenario.scenario_id] = scenario.model_copy(deep=True)
                self._results[scenario.scenario_id] = result.model_copy(deep=True)
                self._run_snapshots[result.run_id] = snapshot
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
                INSERT INTO {self._table('network_run_snapshots')} (
                  run_id, scenario_id, scenario_payload, result_payload,
                  network_rows_payload, flow_rows_payload, cost_rows_payload,
                  created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    result.run_id,
                    scenario.scenario_id,
                    lakebase_store.postgres.jsonb(
                        snapshot.scenario.model_dump(mode="json")
                    ),
                    lakebase_store.postgres.jsonb(
                        snapshot.result.model_dump(mode="json")
                    ),
                    lakebase_store.postgres.jsonb(snapshot.network_rows),
                    lakebase_store.postgres.jsonb(snapshot.flow_rows),
                    lakebase_store.postgres.jsonb(snapshot.cost_rows),
                    result.generated_at,
                ),
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
                  assigned_units, total_cost, freight_total, tariff_total,
                  tariff_rule_ids, rate_source, contract_id,
                  contract_version_id, rate_book_snapshot_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        float(
                            cost_by_key.get(
                                (str(row["service_date"]), str(row["lane_id"])), {}
                            ).get("freight_total", 0)
                        ),
                        float(
                            cost_by_key.get(
                                (str(row["service_date"]), str(row["lane_id"])), {}
                            ).get("tariff_total", 0)
                        ),
                        lakebase_store.postgres.jsonb(
                            cost_by_key.get(
                                (str(row["service_date"]), str(row["lane_id"])), {}
                            ).get("tariff_rule_ids", [])
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

    @staticmethod
    def _is_baseline_resource(resource_id: str, kind: str) -> bool:
        return resource_id.startswith(f"baseline-plan-{kind}.")

    def get(self, scenario_id: str) -> NetworkScenario:
        if self._is_baseline_resource(scenario_id, "scenario"):
            from .baseline_service import baseline_service
            run_id = scenario_id.replace(
                "baseline-plan-scenario.", "baseline-plan-run.", 1
            )
            return baseline_service.resolve_plan_run(run_id).scenario
        return self.repository.get(scenario_id)

    def create(self, request: NetworkScenarioCreateRequest) -> NetworkScenario:
        name = request.scenario_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Scenario name is required.")
        now = _now()
        source_revision = request.source_baseline_revision_id
        if source_revision is None:
            try:
                from .baseline_service import baseline_service
                source_revision = baseline_service.active_revision_id()
            except (ImportError, AttributeError):
                source_revision = None
        assumptions_payload = request.assumptions.model_dump(mode="json")
        if "tariffs" not in request.assumptions.model_fields_set and source_revision:
            try:
                from .baseline_service import baseline_service

                metadata = baseline_service.option_rows(source_revision).get(
                    "baseline_revision_metadata", []
                )
                if metadata:
                    assumptions_payload["tariffs"] = metadata[0].get("tariffs", [])
            except (ImportError, AttributeError):
                pass
        assumptions_payload["source_baseline_revision_id"] = source_revision
        inherited_assumptions = NetworkScenarioAssumptions.model_validate(
            assumptions_payload
        )
        scenario = NetworkScenario(
            scenario_id=f"NSC_{uuid.uuid4().hex[:10].upper()}",
            scenario_name=name,
            baseline_scenario_id=request.baseline_scenario_id,
            source_baseline_revision_id=source_revision,
            demand_plan_version_id=request.demand_plan_version_id,
            capacity_plan_version_id=request.capacity_plan_version_id,
            horizon_start=request.horizon_start,
            horizon_end=request.horizon_end,
            region_id=request.region_id,
            assumptions=inherited_assumptions,
            created_at=now,
            updated_at=now,
        )
        self._validate_input_references(scenario)
        return self.repository.create(scenario)

    def update(
        self, scenario_id: str, request: NetworkScenarioUpdateRequest
    ) -> NetworkScenario:
        if self._is_baseline_resource(scenario_id, "scenario"):
            raise HTTPException(status_code=409, detail="Baseline planning scenarios are immutable.")
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
        requested_assumptions = request.assumptions
        if requested_assumptions is not None:
            requested_assumptions = requested_assumptions.model_copy(update={
                "source_baseline_revision_id": scenario.source_baseline_revision_id,
                "parent_run_id": scenario.assumptions.parent_run_id,
                "release_overlays": scenario.assumptions.release_overlays,
            })
        changed = name != scenario.scenario_name or (
            requested_assumptions is not None
            and requested_assumptions != scenario.assumptions
        )
        updated = scenario.model_copy(
            update={
                "scenario_name": name,
                "assumptions": requested_assumptions or scenario.assumptions,
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
        if scenario.source_baseline_revision_id:
            try:
                from .baseline_service import baseline_service
                if (
                    baseline_service.is_original_active()
                    and scenario.source_baseline_revision_id
                    == baseline_service.active_revision_id()
                ):
                    return network_overview_service.load_rows(
                        demand_plan_version_id=scenario.demand_plan_version_id,
                        capacity_plan_version_id=scenario.capacity_plan_version_id,
                        horizon_start=date.fromisoformat(scenario.horizon_start),
                        horizon_end=date.fromisoformat(scenario.horizon_end),
                    )
                return baseline_service.get_revision(
                    scenario.source_baseline_revision_id
                ).rows
            except ImportError:
                pass
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
        if self._is_baseline_resource(scenario_id, "scenario"):
            raise HTTPException(status_code=409, detail="Baseline planning scenarios are immutable.")
        scenario = self.get(scenario_id)
        self._validate_input_references(scenario)
        rows = self._rows(scenario)
        facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
        lanes = {str(row["lane_id"]): row for row in rows["dim_network_lanes"]}
        assumptions = scenario.assumptions
        issues: list[NetworkScenarioValidationIssue] = []

        seen_tariff_ids: set[str] = set()
        for rule in assumptions.tariffs:
            if rule.rule_id in seen_tariff_ids:
                issues.append(
                    NetworkScenarioValidationIssue(
                        severity="error",
                        code="duplicate_tariff_rule_id",
                        scope="scenario",
                        entity_id=rule.rule_id,
                        message="Tariff rule IDs must be unique within a scenario.",
                    )
                )
            seen_tariff_ids.add(rule.rule_id)
        for index, left in enumerate(assumptions.tariffs):
            for right in assumptions.tariffs[index + 1 :]:
                if (
                    left.origin_country == right.origin_country
                    and left.destination_country == right.destination_country
                    and left.effective_start <= right.effective_end
                    and right.effective_start <= left.effective_end
                ):
                    issues.append(
                        NetworkScenarioValidationIssue(
                            severity="error",
                            code="overlapping_tariff_rules",
                            scope="scenario",
                            entity_id=right.rule_id,
                            message=(
                                f"Tariff rules {left.rule_id} and {right.rule_id} "
                                "overlap for the same directed country pair."
                            ),
                        )
                    )

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
        if self._is_baseline_resource(scenario_id, "scenario"):
            raise HTTPException(status_code=409, detail="Baseline planning scenarios are immutable.")
        self.get(scenario_id)
        self.repository.delete(scenario_id)

    def result(self, scenario_id: str) -> NetworkScenarioResult:
        self.get(scenario_id)
        return self.repository.result(scenario_id)

    def get_run_snapshot(self, run_id: str) -> NetworkRunSnapshot:
        if self._is_baseline_resource(run_id, "run"):
            from .baseline_service import baseline_service
            return baseline_service.resolve_plan_run(run_id)
        return self.repository.run_snapshot(run_id)

    def run_result(self, run_id: str) -> NetworkScenarioResult:
        return self.get_run_snapshot(run_id).result

    def _rate_flows(
        self,
        rows: NetworkRows,
        flow_rows: list[dict[str, Any]],
        tariff_by_date_lane: dict[tuple[str, str], tuple[float, str]],
        *,
        contracts: list[RateContractDetail] | None = None,
    ) -> tuple[
        list[dict[str, Any]],
        list[NetworkFlowChargeDetail],
        list[NetworkScenarioException],
    ]:
        rated = rate_network_flows(
            rows, flow_rows, tariff_by_date_lane,
            contracts=contracts if contracts is not None else list_rate_contract_details(get_store()),
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
            for lane_id in rated.missing_rate_lane_ids
        ]
        return rated.cost_rows, rated.charge_details, exceptions

    @staticmethod
    def _resolve_tariffs(
        rows: NetworkRows,
        rules: list[NetworkTariffRule],
        horizon_start: str,
        horizon_end: str,
    ) -> dict[tuple[str, str], tuple[float, str]]:
        return resolve_network_tariffs(rows, rules, horizon_start, horizon_end)

    def _solver_lane_unit_costs(
        self,
        rows: NetworkRows,
        service_date: str,
        contracts: list[RateContractDetail] | None = None,
    ) -> dict[str, float]:
        """Build linear freight estimates from governed full-load quotes."""
        return objective_lane_unit_costs(
            rows, service_date,
            contracts if contracts is not None else list_rate_contract_details(get_store()),
        )

    def run(
        self,
        scenario_id: str,
        *,
        rows_override: NetworkRows | None = None,
        release_requests: list[dict[str, Any]] | None = None,
    ) -> NetworkScenarioRunResponse:
        if self._is_baseline_resource(scenario_id, "scenario"):
            raise HTTPException(status_code=409, detail="Baseline planning scenarios are immutable.")
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
        parent = (
            self.get_run_snapshot(scenario.assumptions.parent_run_id)
            if scenario.assumptions.parent_run_id else None
        )
        if rows_override is None and parent is not None:
            rows = deepcopy(parent.network_rows)
            rows["baseline_network_flow_daily"] = deepcopy(parent.flow_rows)
            rows["network_flow_cost_daily"] = deepcopy(parent.cost_rows)
        else:
            rows = deepcopy(rows_override) if rows_override is not None else self._rows(scenario)
        source_rows = deepcopy(rows)
        source_metadata = source_rows.get("baseline_revision_metadata", [])
        pinned_context = (
            source_metadata[0].get("network_pricing_context", {})
            if source_metadata else {}
        )
        if parent is not None and parent.result.pricing_context.pricing_basis == "comparable_pinned_dated_contracts_v1":
            pinned_context = parent.result.pricing_context.model_dump(mode="json")
        contracts = (
            [
                RateContractDetail.model_validate(row)
                for row in pinned_context.get("contract_snapshots", [])
            ]
            if "contract_snapshots" in pinned_context
            else list_rate_contract_details(get_store())
        )
        baseline_tariffs = [
            NetworkTariffRule.model_validate(rule)
            for rule in (
                parent.scenario.assumptions.tariffs if parent is not None
                else source_metadata[0].get("tariffs", []) if source_metadata else []
            )
        ]
        if release_requests is None and scenario.assumptions.release_overlays:
            release_requests = [row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row) for row in scenario.assumptions.release_overlays]
        tariff_by_date_lane = self._resolve_tariffs(
            rows,
            scenario.assumptions.tariffs,
            scenario.horizon_start,
            scenario.horizon_end,
        )
        baseline_tariff_by_date_lane = self._resolve_tariffs(
            source_rows, baseline_tariffs, scenario.horizon_start, scenario.horizon_end
        )
        solve_dates = sorted({
            str(row["service_date"])[:10]
            for row in rows["demand_plan_daily"]
            if str(row["demand_plan_version_id"]) == scenario.demand_plan_version_id
            and scenario.horizon_start <= str(row["service_date"])[:10] <= scenario.horizon_end
        })
        dated_unit_costs = {
            (service_date, lane_id): amount
            for service_date in solve_dates
            for lane_id, amount in self._solver_lane_unit_costs(
                rows, service_date, contracts
            ).items()
        }
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
            lane_unit_costs_by_date_lane=dated_unit_costs,
            tariff_per_case_by_date_lane={
                key: value[0] for key, value in tariff_by_date_lane.items()
            },
            unmet_penalty_per_case=(
                scenario.assumptions.unmet_penalty_per_case
            ),
            release_requests=release_requests,
        )
        if allocation.get("network_lanes") is not None:
            rows["dim_network_lanes"] = allocation["network_lanes"]
        if allocation.get("assignment_overlay_rows") is not None:
            rows["network_customer_assignments_daily"] = merge_assignment_overlays(
                rows.get('network_customer_assignments_daily', []),
                allocation["assignment_overlay_rows"],
            )
        if allocation.get("lane_capacity_rows") is not None:
            rows["lane_capacity_daily"] = allocation["lane_capacity_rows"]
        flow_rows = allocation["flow_rows"]
        cost_rows, charges, exceptions = self._rate_flows(
            rows, flow_rows, tariff_by_date_lane, contracts=contracts
        )
        baseline_flow_rows = [
            deepcopy(row)
            for row in source_rows["baseline_network_flow_daily"]
            if scenario.horizon_start <= str(row["service_date"])[:10] <= scenario.horizon_end
            and str(row["demand_plan_version_id"]) == scenario.demand_plan_version_id
            and str(row["capacity_plan_version_id"]) == scenario.capacity_plan_version_id
        ]
        baseline_cost_rows, baseline_charges, _ = self._rate_flows(
            source_rows, baseline_flow_rows, baseline_tariff_by_date_lane,
            contracts=contracts,
        )
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
        comparable_baseline_rows = deepcopy(source_rows)
        comparable_baseline_rows["baseline_network_flow_daily"] = baseline_flow_rows
        comparable_baseline_rows["network_flow_cost_daily"] = baseline_cost_rows
        baseline = network_overview_service.build_overview(
            comparable_baseline_rows,
            context=context.model_copy(update={"scenario_id": "baseline"}),
        )
        scenario_rows = dict(rows)
        scenario_rows["baseline_network_flow_daily"] = flow_rows
        scenario_rows["network_flow_cost_daily"] = cost_rows
        overview = network_overview_service.build_overview(
            scenario_rows, context=context, scenario_id=scenario.scenario_id
        )
        # The comparison/audit uses the same selected linehaul scope as its
        # KPIs. Complete cost rows remain in the immutable run for promotion.
        scenario_lane_ids = {lane.lane_id for lane in overview.lanes if lane.lane_type == "LINEHAUL"}
        baseline_lane_ids = {lane.lane_id for lane in baseline.lanes if lane.lane_type == "LINEHAUL"}
        comparison_lane_ids = scenario_lane_ids | baseline_lane_ids
        all_rating_charges = baseline_charges + charges
        charges = [row for row in charges if row.lane_id in scenario_lane_ids]
        baseline_charges = [row for row in baseline_charges if row.lane_id in baseline_lane_ids]
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
            for row in source_rows["baseline_network_flow_daily"]
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
        facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
        lanes = {str(row["lane_id"]): row for row in rows["dim_network_lanes"]}
        def is_cross_border_depot_flow(row: dict[str, Any]) -> bool:
            if str(row["lane_id"]) not in comparison_lane_ids:
                return False
            lane = lanes.get(str(row["lane_id"]))
            if lane is None or str(lane["lane_type"]) != "LINEHAUL":
                return False
            origin = facilities.get(str(lane["origin_endpoint_id"]))
            destination = facilities.get(str(lane["destination_endpoint_id"]))
            return bool(
                origin
                and destination
                and origin["facility_type"] == "distribution_center"
                and destination["facility_type"] == "depot"
                and origin.get("country_code") != destination.get("country_code")
            )

        cross_border_assigned_units = sum(
            int(row["assigned_units"])
            for row in flow_rows
            if str(row["lane_id"]) in scenario_lane_ids and is_cross_border_depot_flow(row)
        )
        baseline_cross_border_assigned_units = sum(
            int(row["assigned_units"])
            for row in source_rows["baseline_network_flow_daily"]
            if scenario.horizon_start <= str(row["service_date"])[:10] <= scenario.horizon_end
            and str(row["demand_plan_version_id"]) == scenario.demand_plan_version_id
            and str(row["capacity_plan_version_id"]) == scenario.capacity_plan_version_id
            and str(row["lane_id"]) in baseline_lane_ids
            and is_cross_border_depot_flow(row)
        )
        baseline_tariff_exposure = sum(
            int(row["assigned_units"])
            * tariff_by_date_lane.get(
                (str(row["service_date"])[:10], str(row["lane_id"])), (0.0, "")
            )[0]
            for row in source_rows["baseline_network_flow_daily"]
            if scenario.horizon_start <= str(row["service_date"])[:10] <= scenario.horizon_end
            and str(row["demand_plan_version_id"]) == scenario.demand_plan_version_id
            and str(row["capacity_plan_version_id"]) == scenario.capacity_plan_version_id
            and str(row["lane_id"]) in baseline_lane_ids
        )
        tariff_destination_ids = {
            str(lanes[lane_id]["destination_endpoint_id"])
            for _, lane_id in tariff_by_date_lane
            if lane_id in comparison_lane_ids
        }

        def is_domestic_tariff_alternative(lane_id: str) -> bool:
            if lane_id not in comparison_lane_ids:
                return False
            lane = lanes.get(lane_id)
            if lane is None or str(lane["lane_type"]) != "LINEHAUL":
                return False
            origin = facilities.get(str(lane["origin_endpoint_id"]))
            destination = facilities.get(str(lane["destination_endpoint_id"]))
            return bool(
                origin
                and destination
                and str(lane["destination_endpoint_id"]) in tariff_destination_ids
                and str(origin.get("country_code", ""))
                == str(destination.get("country_code", ""))
            )

        scenario_domestic_units = sum(
            int(row["assigned_units"])
            for row in flow_rows
            if is_domestic_tariff_alternative(str(row["lane_id"]))
        )
        baseline_domestic_units = sum(
            int(row["assigned_units"])
            for row in source_rows["baseline_network_flow_daily"]
            if scenario.horizon_start <= str(row["service_date"])[:10] <= scenario.horizon_end
            and str(row["demand_plan_version_id"])
            == scenario.demand_plan_version_id
            and str(row["capacity_plan_version_id"])
            == scenario.capacity_plan_version_id
            and is_domestic_tariff_alternative(str(row["lane_id"]))
        )
        baseline_freight_total = round(sum(row.freight_total for row in baseline_charges), 2)
        baseline_tariff_total = round(sum(row.tariff_total for row in baseline_charges), 2)
        scenario_freight_total = round(sum(row.freight_total for row in charges), 2)
        scenario_tariff_total = round(sum(row.tariff_total for row in charges), 2)
        published_cost_rows = [
            row for row in source_rows.get("network_flow_cost_daily", [])
            if scenario.horizon_start <= str(row["service_date"])[:10] <= scenario.horizon_end
            and str(row.get("demand_plan_version_id", scenario.demand_plan_version_id))
            == scenario.demand_plan_version_id
            and str(row.get("capacity_plan_version_id", scenario.capacity_plan_version_id))
            == scenario.capacity_plan_version_id
            and str(row["lane_id"]) in baseline_lane_ids
        ]
        original_published_cost = (
            round(sum(float(row.get("total_cost", 0)) for row in published_cost_rows), 2)
            if published_cost_rows else None
        )

        def coverage(rows_: list[NetworkFlowChargeDetail]) -> NetworkRateCoverage:
            governed = [row for row in rows_ if row.rate_source == "governed_contract"]
            fallback = [row for row in rows_ if row.rate_source == "planning_fallback"]
            return NetworkRateCoverage(
                governed_charge_count=len(governed), fallback_charge_count=len(fallback),
                governed_assigned_units=sum(row.assigned_units for row in governed),
                fallback_assigned_units=sum(row.assigned_units for row in fallback),
            )

        rate_snapshot_ids = sorted({
            row.rate_book_snapshot_id for row in all_rating_charges if row.rate_book_snapshot_id
        })
        result = NetworkScenarioResult(
            run_id=f"network-run-{uuid.uuid4()}",
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            generated_at=generated_at,
            overview=overview,
            baseline_overview=baseline,
            kpi_deltas=deltas,
            affected_depot_ids=affected,
            freight_total_cost=scenario_freight_total,
            tariff_total_cost=scenario_tariff_total,
            baseline_tariff_exposure=round(baseline_tariff_exposure, 2),
            cross_border_assigned_units=cross_border_assigned_units,
            baseline_cross_border_assigned_units=baseline_cross_border_assigned_units,
            domestic_shift_units=scenario_domestic_units - baseline_domestic_units,
            charge_details=charges,
            baseline_charge_details=baseline_charges,
            baseline_freight_total_cost=baseline_freight_total,
            baseline_tariff_total_cost=baseline_tariff_total,
            baseline_total_modeled_cost=round(baseline_freight_total + baseline_tariff_total, 2),
            scenario_total_modeled_cost=round(scenario_freight_total + scenario_tariff_total, 2),
            original_published_baseline_cost=original_published_cost,
            baseline_rate_coverage=coverage(baseline_charges),
            scenario_rate_coverage=coverage(charges),
            pricing_context=NetworkPricingContext(
                pricing_basis="comparable_pinned_dated_contracts_v1",
                contract_snapshots=[row.model_dump(mode="json") for row in contracts],
                contract_version_ids=sorted({row.version.version_id for row in contracts}),
                rate_book_snapshot_ids=rate_snapshot_ids,
                baseline_tariffs=baseline_tariffs,
                scenario_tariffs=scenario.assumptions.tariffs,
                objective_cost_basis=(
                    "linear_full_load_per_case_dated_contract; "
                    "reported_charges_are_dated_and_whole_load_rounded"
                ),
            ),
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
            network_rows=rows,
            flow_rows=flow_rows,
            cost_rows=cost_rows,
        )
        return NetworkScenarioRunResponse(scenario=solved, result=result)

    def reassign(
        self, run_id: str, changes: list[Any]
    ) -> NetworkScenarioRunResponse:
        source = self.get_run_snapshot(run_id)
        now = _now()
        overlays = [
            NetworkReleaseOverlay(**{
                "service_date": row.service_date,
                "customer_id": row.customer_id,
                "source_depot_id": row.depot_id,
                "cases": row.cases,
            })
            for row in changes
        ]
        scenario = source.scenario.model_copy(
            update={
                "scenario_id": f"NSC_{uuid.uuid4().hex[:10].upper()}",
                "scenario_name": f"{source.scenario.scenario_name} — reassignment",
                "status": "validated",
                "revision": 1,
                "created_at": now,
                "updated_at": now,
                "solved_at": None,
                "assumptions": source.scenario.assumptions.model_copy(update={
                    "source_baseline_revision_id": source.scenario.source_baseline_revision_id,
                    "parent_run_id": run_id,
                    "release_overlays": overlays,
                }),
            }
        )
        self.repository.create(scenario)
        parent_rows = deepcopy(source.network_rows)
        parent_rows["baseline_network_flow_daily"] = deepcopy(source.flow_rows)
        parent_rows["network_flow_cost_daily"] = deepcopy(source.cost_rows)
        return self.run(
            scenario.scenario_id,
            rows_override=parent_rows,
            release_requests=[row.model_dump(mode="json") for row in overlays],
        )


network_scenario_service = NetworkScenarioService()
