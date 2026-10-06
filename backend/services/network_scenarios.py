from __future__ import annotations

import threading
import uuid
import json
import hashlib
import os
import logging
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Any, cast

from fastapi import HTTPException

from route_opt.network_flow import (
    materialize_express_air_transfers,
    solve_fixed_capacity_network,
)

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
    NetworkChargeAuditPage,
    NetworkRateCoverage,
    NetworkRunDiagnostics,
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
    has_governed_lane_rate, linear_objective_cost, objective_lane_unit_costs, rate_network_flows,
    resolve_network_tariffs,
)
from .network_run_snapshots import NetworkRunSnapshot
from .network_snapshot_codec import (
    apply_table_delta as _apply_table_delta,
    decode_envelope as _decode_snapshot_envelope,
    encode_envelope as _encode_snapshot_envelope,
    manifest_with_deltas as _snapshot_manifest_with_deltas,
)
from .network_assignment_projection import merge_assignment_overlays
from .rates import list_rate_contract_details
from .store_provider import get_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


logger = logging.getLogger(__name__)


def _json_value(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"{", "["}:
        import json

        return json.loads(value)
    return value


def _filter_revision_rows(rows: NetworkRows, scenario: NetworkScenario) -> NetworkRows:
    """Reproduce the canonical loader's immutable plan/horizon filtering."""

    start, end = scenario.horizon_start, scenario.horizon_end
    filtered = deepcopy(rows)
    filters = {
        "demand_plan_daily": lambda row: (
            str(row.get("demand_plan_version_id")) == scenario.demand_plan_version_id
            and start <= str(row.get("service_date", ""))[:10] <= end
        ),
        "facility_capacity_daily": lambda row: (
            str(row.get("capacity_plan_version_id")) == scenario.capacity_plan_version_id
            and start <= str(row.get("service_date", ""))[:10] <= end
        ),
        "facility_supply_daily": lambda row: (
            str(row.get("capacity_plan_version_id")) == scenario.capacity_plan_version_id
            and start <= str(row.get("service_date", ""))[:10] <= end
        ),
        "lane_capacity_daily": lambda row: (
            str(row.get("capacity_plan_version_id")) == scenario.capacity_plan_version_id
            and start <= str(row.get("service_date", ""))[:10] <= end
        ),
        "baseline_network_flow_daily": lambda row: (
            str(row.get("demand_plan_version_id")) == scenario.demand_plan_version_id
            and str(row.get("capacity_plan_version_id")) == scenario.capacity_plan_version_id
            and start <= str(row.get("service_date", ""))[:10] <= end
        ),
    }
    for table, predicate in filters.items():
        if table in filtered:
            filtered[table] = [deepcopy(row) for row in filtered[table] if predicate(row)]
    return filtered


def _effective_facility_rows(
    rows: NetworkRows, scenario: NetworkScenario
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Materialize the exact facility bounds used by a solved snapshot."""

    start, end = scenario.horizon_start, scenario.horizon_end
    capacity_id = scenario.capacity_plan_version_id
    facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}

    def selected(row: dict[str, Any]) -> bool:
        return (
            str(row.get("capacity_plan_version_id")) == capacity_id
            and start <= str(row.get("service_date", ""))[:10] <= end
        )

    capacity_rows = deepcopy(rows.get("facility_capacity_daily", []))
    for row in capacity_rows:
        if selected(row):
            row["normal_capacity_units"] = int(row["capacity_units"])
            row["effective_bound_applied"] = True
            retained = scenario.assumptions.facility_capacity_retained_pct.get(
                str(row["facility_id"]), 100
            )
            if str(row["facility_id"]) in scenario.assumptions.disabled_facility_ids:
                retained = 0
            row["capacity_units"] = int(float(row["capacity_units"]) * retained / 100)

    supply_rows = [
        {**deepcopy(row), "supply_source": "canonical_daily_supply"}
        for row in rows.get("facility_supply_daily", [])
    ]
    supply_keys = {
        (str(row.get("capacity_plan_version_id")), str(row.get("service_date"))[:10],
         str(row.get("facility_id")))
        for row in supply_rows
    }
    fallback_rows = [
            {
                "capacity_plan_version_id": row["capacity_plan_version_id"],
                "service_date": row["service_date"],
                "facility_id": row["facility_id"],
                "supply_units": row["capacity_units"],
                "supply_source": "legacy_handling_capacity_fallback",
            }
            for row in rows.get("facility_capacity_daily", [])
            if str(facilities.get(str(row["facility_id"]), {}).get("facility_type"))
            == "distribution_center"
            and (
                str(row.get("capacity_plan_version_id")),
                str(row.get("service_date"))[:10],
                str(row.get("facility_id")),
            ) not in supply_keys
        ]
    supply_rows.extend(fallback_rows)
    for row in supply_rows:
        if selected(row):
            row["normal_supply_units"] = int(row["supply_units"])
            row["effective_bound_applied"] = True
            retained = scenario.assumptions.facility_supply_retained_pct.get(
                str(row["facility_id"]), 100
            )
            row["supply_units"] = int(float(row["supply_units"]) * retained / 100)
    return (
        capacity_rows,
        supply_rows,
        "legacy_handling_capacity_fallback" if fallback_rows else "canonical_daily_supply",
    )


def _restore_normal_facility_rows(rows: NetworkRows) -> None:
    """Undo prior effective bounds before reapplying inherited assumptions."""

    for row in rows.get("facility_capacity_daily", []):
        if row.get("effective_bound_applied") is True and row.get("normal_capacity_units") is not None:
            row["capacity_units"] = int(row["normal_capacity_units"])
            row.pop("effective_bound_applied", None)
    for row in rows.get("facility_supply_daily", []):
        if row.get("effective_bound_applied") is True and row.get("normal_supply_units") is not None:
            row["supply_units"] = int(row["normal_supply_units"])
            row.pop("effective_bound_applied", None)


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
        from .demo_state_gate import demo_state_gate

        with demo_state_gate.admission():
            return self._create(scenario)

    def _create(self, scenario: NetworkScenario) -> NetworkScenario:
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

    def save(
        self,
        scenario: NetworkScenario,
        *,
        clear_result: bool = False,
        expected_revision: int | None = None,
        connection: Any | None = None,
    ) -> None:
        if not self._uses_lakebase:
            with self._lock:
                current = self._scenarios.get(scenario.scenario_id)
                if expected_revision is not None and (
                    current is None or current.revision != expected_revision
                ):
                    raise HTTPException(status_code=409, detail="Scenario revision is stale.")
                self._scenarios[scenario.scenario_id] = scenario.model_copy(deep=True)
                if clear_result:
                    self._results.pop(scenario.scenario_id, None)
            return
        if connection is None:
            with lakebase_store.postgres.transaction() as acquired:
                self.save(
                    scenario,
                    clear_result=clear_result,
                    expected_revision=expected_revision,
                    connection=acquired,
                )
            return
        revision_clause = " AND revision = %s" if expected_revision is not None else ""
        params: tuple[Any, ...] = (
            scenario.scenario_name,
            scenario.status,
            scenario.revision,
            lakebase_store.postgres.jsonb(scenario.assumptions.model_dump(mode="json")),
            (
                lakebase_store.postgres.jsonb(scenario.validation.model_dump(mode="json"))
                if scenario.validation else None
            ),
            scenario.updated_at,
            scenario.solved_at,
            scenario.scenario_id,
            *((expected_revision,) if expected_revision is not None else ()),
        )
        changed = lakebase_store.postgres.execute(
                f"""
                UPDATE {self._table('network_scenarios')}
                SET scenario_name = %s, status = %s, revision = %s,
                    assumptions = %s, validation = %s, updated_at = %s,
                    solved_at = %s
                WHERE scenario_id = %s{revision_clause}
                """,
                params,
                connection=connection,
            )
        if expected_revision is not None and changed != 1:
            raise HTTPException(status_code=409, detail="Scenario revision is stale.")
        if clear_result:
            for table_name in (
                "network_flow_results", "network_flow_charge_details",
                "network_scenario_exceptions", "network_scenario_results",
            ):
                lakebase_store.postgres.execute(
                    f"DELETE FROM {self._table(table_name)} WHERE scenario_id = %s",
                    (scenario.scenario_id,), connection=connection,
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

    def clear_all(self) -> int:
        """Delete scenarios and immutable run artifacts after workers are idle."""
        if not self._uses_lakebase:
            with self._lock:
                count = len(self._scenarios)
                self._scenarios.clear()
                self._results.clear()
                self._run_snapshots.clear()
                return count
        with lakebase_store.postgres.transaction() as connection:
            count_row = lakebase_store.postgres.query_one(
                f"SELECT COUNT(*) AS count FROM {self._table('network_scenarios')}",
                connection=connection,
            )
            for table_name in (
                "network_run_charge_details", "network_run_snapshots",
                "network_flow_charge_details", "network_flow_results",
                "network_scenario_exceptions", "network_scenario_results",
                "network_scenarios",
            ):
                lakebase_store.postgres.execute(
                    f"DELETE FROM {self._table(table_name)}", connection=connection
                )
        return int((count_row or {}).get("count", 0))

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
            f"SELECT scenario_payload, result_payload, network_rows_manifest, "
            f"snapshot_envelope, snapshot_codec, snapshot_uncompressed_bytes, snapshot_sha256 "
            f"FROM {self._table('network_run_snapshots')} WHERE run_id = %s",
            (run_id,),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Network run not found.")
        scenario = NetworkScenario.model_validate(_json_value(row["scenario_payload"]))
        manifest = _json_value(row.get("network_rows_manifest"))
        network_rows: NetworkRows | None = (
            self._reconstruct_network_rows(scenario, manifest) if manifest else None
        )
        if row.get("snapshot_envelope") is not None:
            flow_rows, cost_rows = _decode_snapshot_envelope(
                row["snapshot_envelope"],
                codec=str(row.get("snapshot_codec") or ""),
                uncompressed_bytes=int(row.get("snapshot_uncompressed_bytes") or -1),
                expected_sha256=str(row.get("snapshot_sha256") or ""),
            )
        else:
            legacy = lakebase_store.postgres.query_one(
                f"SELECT network_rows_payload, flow_rows_payload, cost_rows_payload "
                f"FROM {self._table('network_run_snapshots')} WHERE run_id = %s",
                (run_id,),
            ) or {}
            flow_rows = cast(
                list[dict[str, Any]], _json_value(legacy.get("flow_rows_payload", []))
            )
            cost_rows = cast(
                list[dict[str, Any]], _json_value(legacy.get("cost_rows_payload", []))
            )
            if network_rows is None:
                network_rows = cast(
                    NetworkRows, _json_value(legacy.get("network_rows_payload", {}))
                )
        if network_rows is None:
            raise RuntimeError("Network snapshot is missing its row manifest.")
        return NetworkRunSnapshot(
            scenario=scenario,
            result=NetworkScenarioResult.model_validate(
                _json_value(row["result_payload"])
            ),
            network_rows=network_rows,
            flow_rows=flow_rows,
            cost_rows=cost_rows,
        )

    def _reconstruct_network_rows(
        self, scenario: NetworkScenario, manifest: dict[str, Any]
    ) -> NetworkRows:
        kind = manifest.get("base_kind")
        if kind == "parent_run":
            parent = self.run_snapshot(str(manifest["parent_run_id"]))
            rows = deepcopy(parent.network_rows)
            rows["baseline_network_flow_daily"] = deepcopy(parent.flow_rows)
            rows["network_flow_cost_daily"] = deepcopy(parent.cost_rows)
        elif kind == "baseline_revision":
            from .baseline_service import baseline_service

            rows = baseline_service.get_revision(str(manifest["revision_id"])).rows
            if manifest.get("filter_plan_horizon"):
                rows = _filter_revision_rows(rows, scenario)
        else:
            raise RuntimeError(f"Unsupported network snapshot base kind: {kind!r}")
        for table, delta in manifest.get("table_deltas", {}).items():
            rows[str(table)] = _apply_table_delta(rows.get(str(table), []), delta)
        for table, replacement in manifest.get("table_replacements", {}).items():
            rows[str(table)] = deepcopy(replacement)
        return rows

    def save_result(
        self,
        scenario: NetworkScenario,
        result: NetworkScenarioResult,
        *,
        network_rows: NetworkRows,
        flow_rows: list[dict[str, Any]],
        cost_rows: list[dict[str, Any]],
        expected_revision: int,
        source_rows: NetworkRows | None = None,
        snapshot_manifest: dict[str, Any] | None = None,
    ) -> bool:
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
                from .network_run_jobs import network_run_manager
                try:
                    cancelled = (
                        network_run_manager.repository.get(result.run_id).status
                        == "cancelled"
                    )
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    cancelled = False
                if cancelled:
                    raise HTTPException(status_code=409, detail="Network run was cancelled.")
                self._run_snapshots[result.run_id] = snapshot
                current = self._scenarios.get(scenario.scenario_id)
                if current is None or current.revision != expected_revision:
                    return False
                self._scenarios[scenario.scenario_id] = scenario.model_copy(deep=True)
                self._results[scenario.scenario_id] = result.model_copy(deep=True)
            return True
        cost_by_key = {
            (str(row["service_date"]), str(row["lane_id"])): row
            for row in cost_rows
        }
        with lakebase_store.postgres.transaction() as connection:
            job = lakebase_store.postgres.query_one(
                f"SELECT status FROM {self._table('network_run_jobs')} "
                "WHERE run_id=%s FOR UPDATE",
                (result.run_id,), connection=connection,
            )
            if job and job["status"] == "cancelled":
                raise HTTPException(status_code=409, detail="Network run was cancelled.")
            manifest = deepcopy(snapshot_manifest)
            envelope: bytes | None = None
            envelope_size: int | None = None
            envelope_hash: str | None = None
            if manifest is not None:
                manifest = _snapshot_manifest_with_deltas(
                    manifest, source_rows or {}, network_rows
                )
                envelope, envelope_size, envelope_hash = _encode_snapshot_envelope(
                    snapshot.flow_rows, snapshot.cost_rows
                )
            lakebase_store.postgres.execute(
                f"""
                INSERT INTO {self._table('network_run_snapshots')} (
                  run_id, scenario_id, scenario_payload, result_payload,
                  network_rows_payload, network_rows_manifest, flow_rows_payload, cost_rows_payload,
                  snapshot_envelope, snapshot_codec, snapshot_uncompressed_bytes, snapshot_sha256,
                  created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    lakebase_store.postgres.jsonb(
                        {} if manifest is not None else snapshot.network_rows
                    ),
                    (
                        lakebase_store.postgres.jsonb(manifest)
                        if manifest is not None else None
                    ),
                    lakebase_store.postgres.jsonb([] if envelope is not None else snapshot.flow_rows),
                    lakebase_store.postgres.jsonb([] if envelope is not None else snapshot.cost_rows),
                    envelope,
                    "zlib-json-v1" if envelope is not None else None,
                    envelope_size,
                    envelope_hash,
                    result.generated_at,
                ),
                connection=connection,
            )
            charge_rows = [
                (result.run_id, side, row.service_date, row.lane_id, row.total_cost,
                 row.rate_source, row.contract_id, row.assigned_units,
                 lakebase_store.postgres.jsonb(row.model_dump(mode="json")))
                for side, charges in (
                    ("scenario", result.charge_details),
                    ("baseline", result.baseline_charge_details),
                )
                for row in charges
            ]
            lakebase_store.postgres.executemany(
                f"""INSERT INTO {self._table('network_run_charge_details')} (
                    run_id, side, service_date, lane_id, total_cost, rate_source,
                    contract_id, assigned_units, payload
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                charge_rows, connection=connection,
            )
            changed = lakebase_store.postgres.execute(
                f"""UPDATE {self._table('network_scenarios')}
                    SET status=%s, validation=%s, updated_at=%s, solved_at=%s
                    WHERE scenario_id=%s AND revision=%s""",
                (
                    scenario.status,
                    lakebase_store.postgres.jsonb(scenario.validation.model_dump(mode="json"))
                    if scenario.validation else None,
                    scenario.updated_at, scenario.solved_at,
                    scenario.scenario_id, expected_revision,
                ), connection=connection,
            )
            if changed != 1:
                lakebase_store.postgres.execute(
                    f"UPDATE {self._table('network_run_jobs')} SET status='stale', "
                    "completed_at=NOW(), lease_expires_at=NULL, error_code='stale_revision', "
                    "error_message='Scenario changed while this revision was solving.' "
                    "WHERE run_id=%s",
                    (result.run_id,), connection=connection,
                )
                return False
            for table_name in (
                "network_flow_results", "network_flow_charge_details",
                "network_scenario_exceptions",
            ):
                lakebase_store.postgres.execute(
                    f"DELETE FROM {self._table(table_name)} WHERE scenario_id = %s",
                    (scenario.scenario_id,), connection=connection,
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
            lakebase_store.postgres.execute(
                f"UPDATE {self._table('network_run_jobs')} SET status='completion_pending', "
                "lease_expires_at=NULL, diagnostics=%s WHERE run_id=%s",
                (
                    lakebase_store.postgres.jsonb(
                        result.diagnostics.model_dump(mode='json')
                    ) if result.diagnostics else None,
                    result.run_id,
                ), connection=connection,
            )
        return True

    def finalize_result_diagnostics(
        self, run_id: str, diagnostics: NetworkRunDiagnostics
    ) -> None:
        """Freeze post-commit diagnostics into the newly created run snapshot."""

        if not self._uses_lakebase:
            with self._lock:
                snapshot = self._run_snapshots.get(run_id)
                if snapshot is None:
                    return
                result = snapshot.result.model_copy(deep=True)
                result.diagnostics = diagnostics.model_copy(deep=True)
                self._run_snapshots[run_id] = NetworkRunSnapshot(
                    scenario=snapshot.scenario,
                    result=result,
                    network_rows=snapshot.network_rows,
                    flow_rows=snapshot.flow_rows,
                    cost_rows=snapshot.cost_rows,
                )
                if self._results.get(result.scenario_id, None) is not None:
                    current = self._results[result.scenario_id]
                    if current.run_id == run_id:
                        self._results[result.scenario_id] = result.model_copy(deep=True)
            return
        lakebase_store.postgres.execute(
            f"UPDATE {self._table('network_run_snapshots')} "
            "SET result_payload=jsonb_set(result_payload, '{diagnostics}', %s, true) "
            "WHERE run_id=%s",
            (lakebase_store.postgres.jsonb(diagnostics.model_dump(mode="json")), run_id),
        )

    def charge_audit(
        self,
        run_id: str,
        *,
        side: str,
        offset: int,
        limit: int,
        query: str = "",
    ) -> NetworkChargeAuditPage:
        """Read charges from an immutable run snapshot, including legacy payloads."""
        if self._uses_lakebase:
            needle = f"%{query.strip()}%"
            where = "run_id=%s AND side=%s"
            params: list[Any] = [run_id, side]
            if query.strip():
                where += " AND (lane_id ILIKE %s OR COALESCE(contract_id,'') ILIKE %s)"
                params.extend([needle, needle])
            summary = lakebase_store.postgres.query_one(
                f"""SELECT COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE rate_source='governed_contract') AS governed_count,
                    COUNT(*) FILTER (WHERE rate_source='planning_fallback') AS fallback_count,
                    COALESCE(SUM(assigned_units) FILTER (WHERE rate_source='governed_contract'),0) AS governed_units,
                    COALESCE(SUM(assigned_units) FILTER (WHERE rate_source='planning_fallback'),0) AS fallback_units
                    FROM {self._table('network_run_charge_details')} WHERE {where}""",
                tuple(params),
            )
            if summary and int(summary["total"]) > 0:
                page = lakebase_store.postgres.query(
                    f"SELECT payload FROM {self._table('network_run_charge_details')} "
                    f"WHERE {where} ORDER BY total_cost DESC, service_date, lane_id "
                    "OFFSET %s LIMIT %s",
                    tuple([*params, offset, limit]),
                )
                return NetworkChargeAuditPage(
                    items=[NetworkFlowChargeDetail.model_validate(_json_value(r["payload"])) for r in page],
                    total=int(summary["total"]), offset=offset, limit=limit,
                    coverage=NetworkRateCoverage(
                        governed_charge_count=int(summary["governed_count"]),
                        fallback_charge_count=int(summary["fallback_count"]),
                        governed_assigned_units=int(summary["governed_units"]),
                        fallback_assigned_units=int(summary["fallback_units"]),
                    ),
                )
        snapshot = self.run_snapshot(run_id)
        charges = (
            snapshot.result.baseline_charge_details
            if side == "baseline"
            else snapshot.result.charge_details
        )
        needle = query.strip().lower()
        if needle:
            charges = [
                row for row in charges
                if needle in row.lane_id.lower()
                or needle in (row.contract_id or "").lower()
            ]
        ordered = sorted(
            charges,
            key=lambda row: (-row.total_cost, row.service_date, row.lane_id),
        )
        governed = [row for row in ordered if row.rate_source == "governed_contract"]
        fallback = [row for row in ordered if row.rate_source == "planning_fallback"]
        return NetworkChargeAuditPage(
            items=[row.model_copy(deep=True) for row in ordered[offset:offset + limit]],
            total=len(ordered),
            offset=offset,
            limit=limit,
            coverage=NetworkRateCoverage(
                governed_charge_count=len(governed),
                fallback_charge_count=len(fallback),
                governed_assigned_units=sum(row.assigned_units for row in governed),
                fallback_assigned_units=sum(row.assigned_units for row in fallback),
            ),
        )

    def prune_history(self, scenario_id: str, *, retain: int) -> int:
        """Delete only old, terminal, unreferenced accelerator run artifacts."""

        retain = max(1, retain)
        if not self._uses_lakebase:
            with self._lock:
                snapshots = sorted(
                    (
                        row for row in self._run_snapshots.values()
                        if row.scenario.scenario_id == scenario_id
                    ),
                    key=lambda row: row.result.generated_at,
                    reverse=True,
                )
                protected = {
                    row.scenario.assumptions.parent_run_id
                    for row in self._run_snapshots.values()
                    if row.scenario.assumptions.parent_run_id
                }
                protected.update(
                    row.assumptions.parent_run_id
                    for row in self._scenarios.values()
                    if row.assumptions.parent_run_id
                )
                doomed = [
                    row.result.run_id for row in snapshots[retain:]
                    if row.result.run_id and row.result.run_id not in protected
                ]
                for run_id in doomed:
                    self._run_snapshots.pop(run_id, None)
                return len(doomed)

        rows = lakebase_store.postgres.query(
            f"""SELECT run_id FROM {self._table('network_run_snapshots')}
                WHERE scenario_id=%s
                  AND run_id NOT IN (
                    SELECT COALESCE(run_id, '') FROM {self._table('network_baseline_revisions')}
                  )
                  AND run_id NOT IN (
                    SELECT COALESCE(parent_run_id, '') FROM {self._table('network_run_jobs')}
                  )
                  AND run_id NOT IN (
                    SELECT COALESCE(assumptions->>'parent_run_id', '')
                    FROM {self._table('network_scenarios')}
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM {self._table('network_run_jobs')} jobs
                    WHERE jobs.run_id={self._table('network_run_snapshots')}.run_id
                      AND jobs.status NOT IN ('succeeded','failed','cancelled','stale')
                  )
                ORDER BY created_at DESC OFFSET %s""",
            (scenario_id, retain),
        )
        run_ids = [str(row["run_id"]) for row in rows]
        if not run_ids:
            return 0
        with lakebase_store.postgres.transaction() as connection:
            lakebase_store.postgres.execute(
                f"DELETE FROM {self._table('network_run_charge_details')} WHERE run_id=ANY(%s)",
                (run_ids,), connection=connection,
            )
            lakebase_store.postgres.execute(
                f"DELETE FROM {self._table('network_run_snapshots')} WHERE run_id=ANY(%s)",
                (run_ids,), connection=connection,
            )
            lakebase_store.postgres.execute(
                f"DELETE FROM {self._table('network_run_jobs')} WHERE run_id=ANY(%s) "
                "AND status IN ('succeeded','failed','cancelled','stale')",
                (run_ids,), connection=connection,
            )
        return len(run_ids)

    def record_api_response(
        self, run_id: str, *, encoding_seconds: float, payload_bytes: int
    ) -> None:
        """Persist measured compact response encoding diagnostics."""

        if not self._uses_lakebase:
            with self._lock:
                snapshot = self._run_snapshots.get(run_id)
                if snapshot is None or snapshot.result.diagnostics is None:
                    return
                result = snapshot.result.model_copy(deep=True)
                result.diagnostics.stage_seconds["api_response_encoding"] = round(
                    encoding_seconds, 6
                )
                result.diagnostics.api_response_bytes = payload_bytes
                self._run_snapshots[run_id] = NetworkRunSnapshot(
                    scenario=snapshot.scenario,
                    result=result,
                    network_rows=snapshot.network_rows,
                    flow_rows=snapshot.flow_rows,
                    cost_rows=snapshot.cost_rows,
                )
            return
        row = lakebase_store.postgres.query_one(
            f"SELECT diagnostics FROM {self._table('network_run_jobs')} WHERE run_id=%s",
            (run_id,),
        )
        if row is None or not row.get("diagnostics"):
            return
        diagnostics = NetworkRunDiagnostics.model_validate(_json_value(row["diagnostics"]))
        diagnostics.stage_seconds["api_response_encoding"] = round(
            encoding_seconds, 6
        )
        diagnostics.api_response_bytes = payload_bytes
        lakebase_store.postgres.execute(
            f"UPDATE {self._table('network_run_jobs')} SET diagnostics=%s WHERE run_id=%s",
            (lakebase_store.postgres.jsonb(diagnostics.model_dump(mode="json")), run_id),
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
        if source_revision:
            try:
                from .baseline_service import baseline_service

                metadata = baseline_service.get_revision(source_revision).rows.get(
                    "baseline_revision_metadata", []
                )
                if metadata:
                    inherited = metadata[0]
                    for field in (
                        "tariffs",
                        "facility_capacity_retained_pct",
                        "facility_supply_retained_pct",
                        "dc_transfer_requests",
                    ):
                        if field not in request.assumptions.model_fields_set:
                            assumptions_payload[field] = inherited.get(
                                field, assumptions_payload.get(field)
                            )
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
        if scenario.revision != request.expected_revision:
            raise HTTPException(status_code=409, detail="Scenario revision is stale.")
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
        self.repository.save(
            updated, clear_result=changed, expected_revision=request.expected_revision
        )
        return updated

    def _rows(self, scenario: NetworkScenario) -> NetworkRows:
        if scenario.source_baseline_revision_id:
            try:
                from .baseline_service import baseline_service
                revision = baseline_service.get_revision(
                    scenario.source_baseline_revision_id
                )
                original_id, _ = baseline_service.repository.ids()
                return (
                    _filter_revision_rows(revision.rows, scenario)
                    if scenario.source_baseline_revision_id == original_id
                    else revision.rows
                )
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
        for facility_id in assumptions.facility_capacity_retained_pct:
            if facility_id not in facilities:
                issues.append(
                    NetworkScenarioValidationIssue(
                        severity="error",
                        code="unknown_capacity_facility",
                        scope="facility",
                        entity_id=facility_id,
                        message="Capacity adjustment facility does not exist in the canonical network.",
                    )
                )
        for facility_id in assumptions.facility_supply_retained_pct:
            facility = facilities.get(facility_id)
            if facility is None or str(facility.get("facility_type")) != "distribution_center":
                issues.append(
                    NetworkScenarioValidationIssue(
                        severity="error",
                        code="unknown_supply_facility",
                        scope="facility",
                        entity_id=facility_id,
                        message="Supply adjustments require a canonical distribution center.",
                    )
                )
        seen_transfer_ids: set[str] = set()
        for transfer in assumptions.dc_transfer_requests:
            if transfer.transfer_id in seen_transfer_ids:
                issues.append(
                    NetworkScenarioValidationIssue(
                        severity="error", code="duplicate_transfer_id",
                        scope="scenario", entity_id=transfer.transfer_id,
                        message="DC transfer IDs must be unique within a scenario.",
                    )
                )
            seen_transfer_ids.add(transfer.transfer_id)
            for endpoint_id in (transfer.origin_dc_id, transfer.destination_dc_id):
                endpoint = facilities.get(endpoint_id)
                if endpoint is None or str(endpoint.get("facility_type")) != "distribution_center":
                    issues.append(
                        NetworkScenarioValidationIssue(
                            severity="error", code="invalid_transfer_endpoint",
                            scope="facility", entity_id=endpoint_id,
                            message="DC transfer endpoints must be canonical distribution centers.",
                        )
                    )
            if not scenario.horizon_start <= transfer.departure_date <= scenario.horizon_end:
                issues.append(
                    NetworkScenarioValidationIssue(
                        severity="error", code="transfer_departure_outside_horizon",
                        scope="scenario", entity_id=transfer.transfer_id,
                        message="DC transfer departure must fall inside the scenario horizon.",
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

        contracts = list_rate_contract_details(get_store())
        service_dates: list[str] = []
        current_date = date.fromisoformat(scenario.horizon_start)
        horizon_end = date.fromisoformat(scenario.horizon_end)
        while current_date <= horizon_end:
            service_dates.append(current_date.isoformat())
            current_date += timedelta(days=1)
        missing_rate_lanes = {
            str(lane["lane_id"])
            for lane in rows["dim_network_lanes"]
            if lane["lane_type"] == "LINEHAUL"
            and str(lane["lane_id"]) not in assumptions.disabled_lane_ids
            and any(
                not has_governed_lane_rate(contracts, service_date, lane, facilities)
                for service_date in service_dates
            )
        }
        if missing_rate_lanes:
            issues.append(
                NetworkScenarioValidationIssue(
                    severity="warning",
                    code="planning_rate_fallback",
                    scope="rate",
                    message=(
                        f"{len(missing_rate_lanes)} permitted linehaul lanes do not have a "
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
        self.repository.save(updated, expected_revision=scenario.revision)
        return updated

    def delete(self, scenario_id: str) -> None:
        if self._is_baseline_resource(scenario_id, "scenario"):
            raise HTTPException(status_code=409, detail="Baseline planning scenarios are immutable.")
        self.get(scenario_id)
        self.repository.delete(scenario_id)

    def result(self, scenario_id: str) -> NetworkScenarioResult:
        if self._is_baseline_resource(scenario_id, "scenario"):
            from .baseline_service import baseline_service
            run_id = scenario_id.replace(
                "baseline-plan-scenario.", "baseline-plan-run.", 1
            )
            return baseline_service.resolve_plan_run(run_id).result
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
        run_id: str | None = None,
        expected_revision: int | None = None,
        rows_override: NetworkRows | None = None,
        release_requests: list[dict[str, Any]] | None = None,
    ) -> NetworkScenarioRunResponse:
        run_started = perf_counter()
        stage_seconds: dict[str, float] = {}
        stage_started = run_started

        def mark(stage: str) -> None:
            nonlocal stage_started
            now = perf_counter()
            stage_seconds[stage] = round(now - stage_started, 6)
            stage_started = now

        if self._is_baseline_resource(scenario_id, "scenario"):
            raise HTTPException(status_code=409, detail="Baseline planning scenarios are immutable.")
        scenario = self.get(scenario_id)
        if expected_revision is not None and scenario.revision != expected_revision:
            raise HTTPException(status_code=409, detail="Scenario revision is stale.")
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
        _restore_normal_facility_rows(rows)
        normal_rows = deepcopy(rows)
        mark("input_loading_and_copying")
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
        transfer_requests = [
            row.model_dump(mode="json")
            for row in scenario.assumptions.dc_transfer_requests
        ]
        if transfer_requests:
            materialized = materialize_express_air_transfers(
                rows,
                transfer_requests,
                capacity_plan_version_id=scenario.capacity_plan_version_id,
            )
            rows["dim_network_lanes"] = materialized["network_lanes"]
            rows["lane_capacity_daily"] = materialized["lane_capacity_rows"]
        tariff_by_date_lane = self._resolve_tariffs(
            rows,
            scenario.assumptions.tariffs,
            scenario.horizon_start,
            scenario.horizon_end,
        )
        baseline_tariff_by_date_lane = self._resolve_tariffs(
            source_rows, baseline_tariffs, scenario.horizon_start, scenario.horizon_end
        )
        mark("contract_and_tariff_resolution")
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
        mark("objective_cost_preparation")
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
            facility_capacity_retained_pct=(
                scenario.assumptions.facility_capacity_retained_pct
            ),
            facility_supply_retained_pct=(
                scenario.assumptions.facility_supply_retained_pct
            ),
            dc_transfer_requests=transfer_requests,
        )
        mark("network_solve")
        if allocation.get("network_lanes") is not None:
            rows["dim_network_lanes"] = allocation["network_lanes"]
        if allocation.get("assignment_overlay_rows") is not None:
            rows["network_customer_assignments_daily"] = merge_assignment_overlays(
                rows.get('network_customer_assignments_daily', []),
                allocation["assignment_overlay_rows"],
            )
        if allocation.get("lane_capacity_rows") is not None:
            rows["lane_capacity_daily"] = allocation["lane_capacity_rows"]
        if allocation.get("facility_capacity_rows") is not None:
            rows["facility_capacity_daily"] = allocation["facility_capacity_rows"]
        if allocation.get("facility_supply_rows") is not None:
            rows["facility_supply_daily"] = allocation["facility_supply_rows"]
        rows["network_transfer_movements"] = deepcopy(
            allocation.get("transfer_movements", [])
        )
        if (
            allocation.get("facility_capacity_rows") is None
            or allocation.get("facility_supply_rows") is None
        ):
            effective_capacity, effective_supply, supply_source = _effective_facility_rows(
                normal_rows, scenario
            )
            if allocation.get("facility_capacity_rows") is None:
                rows["facility_capacity_daily"] = effective_capacity
            if allocation.get("facility_supply_rows") is None:
                rows["facility_supply_daily"] = effective_supply
            rows["facility_supply_provenance"] = [{"source": supply_source}]
        flow_rows = allocation["flow_rows"]
        cost_rows, charges, exceptions = self._rate_flows(
            rows, flow_rows, tariff_by_date_lane, contracts=contracts
        )
        mark("scenario_rating")
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
        mark("baseline_rating")
        for unmet in allocation["unmet_rows"]:
            if int(unmet["unmet_units"]) <= 0:
                continue
            shortage_cause = str(unmet.get("shortage_cause", "unknown"))
            if shortage_cause not in {"supply", "handling", "lane"}:
                shortage_cause = "unknown"
            cause_message = {
                "supply": "available distribution-center stock",
                "handling": "facility handling throughput",
                "lane": "permitted lane capacity",
                "unknown": "supplied facility and lane capacity",
            }[shortage_cause]
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
                        f"within {cause_message}."
                    ),
                    demand_units=int(unmet["demand_units"]),
                    assigned_units=int(unmet["assigned_units"]),
                    unmet_units=int(unmet["unmet_units"]),
                    shortage_cause=cast(Any, shortage_cause),
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
            scenario_rows,
            context=context,
            scenario_id=scenario.scenario_id,
            facility_capacity_retained_pct={
                **scenario.assumptions.facility_capacity_retained_pct,
                **{facility_id: 0 for facility_id in scenario.assumptions.disabled_facility_ids},
            },
            facility_supply_retained_pct=scenario.assumptions.facility_supply_retained_pct,
        )
        mark("overview_construction")
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
        optimization_objective_cost = linear_objective_cost(
            flow_rows, dated_unit_costs, tariff_by_date_lane
        )
        objective_gap = round(
            scenario_freight_total + scenario_tariff_total - optimization_objective_cost,
            2,
        )
        objective_gap_pct = (
            round(objective_gap / optimization_objective_cost * 100, 2)
            if optimization_objective_cost > 0 else None
        )
        transfer_charges = {
            (row.service_date, row.lane_id): row for row in charges
            if row.lane_id.startswith("XFER_")
        }
        transfer_movements = []
        for movement in allocation.get("transfer_movements", []):
            charge = transfer_charges.get(
                (movement["departure_date"], movement["lane_id"])
            )
            freight = charge.freight_total if charge else 0.0
            tariff = charge.tariff_total if charge else 0.0
            transfer_movements.append({
                **movement,
                "freight_cost": freight,
                "tariff_cost": tariff,
                "total_cost": round(freight + tariff, 2),
                "tariff_rule_ids": charge.tariff_rule_ids if charge else [],
            })
        result = NetworkScenarioResult(
            run_id=run_id or f"network-run-{uuid.uuid4()}",
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
            optimization_objective_cost=optimization_objective_cost,
            objective_to_rated_cost_gap=objective_gap,
            objective_to_rated_cost_gap_pct=objective_gap_pct,
            objective_gap_material=(
                objective_gap_pct is not None and abs(objective_gap_pct) >= 5.0
            ),
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
            exception_evidence_status="available",
            exceptions=exceptions,
            transfer_movements=transfer_movements,
        )
        mark("result_assembly")
        summary_payload = result.model_dump(
            mode="json", exclude={"charge_details", "baseline_charge_details"}
        )
        serialization_started = perf_counter()
        summary_json = json.dumps(summary_payload, separators=(",", ":"))
        snapshot_json_bytes = len(json.dumps(
            {"network_rows": rows, "flow_rows": flow_rows, "cost_rows": cost_rows},
            separators=(",", ":"), default=str,
        ).encode())
        serialization_seconds = round(perf_counter() - serialization_started, 6)
        result.diagnostics = NetworkRunDiagnostics(
            stage_seconds={
                **stage_seconds,
                "persistence": 0.0,
                "api_serialization": serialization_seconds,
            },
            scenario_charge_count=len(charges),
            baseline_charge_count=len(baseline_charges),
            solver_day_count=len(solve_dates),
            summary_json_bytes=len(summary_json.encode()),
            snapshot_json_bytes=snapshot_json_bytes,
        )
        solved = scenario.model_copy(
            update={
                "status": "solved",
                "updated_at": generated_at,
                "solved_at": generated_at,
            }
        )
        persistence_started = perf_counter()
        snapshot_manifest: dict[str, Any] | None = None
        if parent is not None and scenario.assumptions.parent_run_id:
            snapshot_manifest = {
                "format": "network_rows_reference_v1",
                "base_kind": "parent_run",
                "parent_run_id": scenario.assumptions.parent_run_id,
            }
        elif scenario.source_baseline_revision_id:
            try:
                from .baseline_service import baseline_service

                original_id, _ = baseline_service.repository.ids()
                snapshot_manifest = {
                    "format": "network_rows_reference_v1",
                    "base_kind": "baseline_revision",
                    "revision_id": scenario.source_baseline_revision_id,
                    "filter_plan_horizon": (
                        scenario.source_baseline_revision_id == original_id
                    ),
                }
            except Exception:
                logger.exception(
                    "Falling back to full network snapshot run_id=%s", result.run_id
                )
        became_current = self.repository.save_result(
            solved,
            result,
            network_rows=rows,
            flow_rows=flow_rows,
            cost_rows=cost_rows,
            expected_revision=expected_revision or scenario.revision,
            source_rows=source_rows,
            snapshot_manifest=snapshot_manifest,
        )
        persistence_seconds = round(perf_counter() - persistence_started, 6)
        if result.diagnostics:
            result.diagnostics.stage_seconds["persistence"] = persistence_seconds
            try:
                result.diagnostics.retention_pruned_runs = self.repository.prune_history(
                    scenario.scenario_id,
                    retain=max(1, int(os.getenv("NETWORK_RUN_RETENTION_PER_SCENARIO", "50"))),
                )
            except Exception:
                logger.exception(
                    "Network run retention failed scenario_id=%s run_id=%s",
                    scenario.scenario_id, result.run_id,
                )
            self.repository.finalize_result_diagnostics(
                result.run_id or "", result.diagnostics
            )
        current = solved if became_current else self.get(scenario_id)
        return NetworkScenarioRunResponse(scenario=current, result=result)

    def charge_audit(
        self, run_id: str, *, side: str, offset: int, limit: int, query: str = ""
    ) -> NetworkChargeAuditPage:
        return self.repository.charge_audit(
            run_id, side=side, offset=offset, limit=limit, query=query
        )

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

    def prepare_reassignment(
        self, run_id: str, changes: list[Any]
    ) -> tuple[NetworkScenario, str]:
        """Freeze a deterministic child scenario for durable reassignment."""

        source = self.get_run_snapshot(run_id)
        frozen = sorted(
            [
                {
                    "change_id": str(row.change_id),
                    "service_date": row.service_date,
                    "customer_id": row.customer_id,
                    "source_depot_id": row.depot_id,
                    "cases": row.cases,
                }
                for row in changes
            ],
            key=lambda row: row["change_id"],
        )
        digest = hashlib.sha256(
            json.dumps(
                {"parent_run_id": run_id, "changes": frozen},
                sort_keys=True, separators=(",", ":"),
            ).encode()
        ).hexdigest()
        scenario_id = f"NSC_REASSIGN_{digest[:12].upper()}"
        try:
            return self.get(scenario_id), f"network-reassignment:{digest}"
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        now = _now()
        overlays = [
            NetworkReleaseOverlay(
                service_date=row["service_date"],
                customer_id=row["customer_id"],
                source_depot_id=row["source_depot_id"],
                cases=row["cases"],
            )
            for row in frozen
        ]
        scenario = source.scenario.model_copy(
            update={
                "scenario_id": scenario_id,
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
        return scenario, f"network-reassignment:{digest}"


network_scenario_service = NetworkScenarioService()
