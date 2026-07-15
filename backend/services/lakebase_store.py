"""Parameterized Lakebase implementation of the interactive-store contract."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Literal, Mapping, cast

from fastapi import HTTPException

from route_opt.overrides import build_scenario_overrides

from ..models import (
    BaselineNetwork,
    ComparisonResult,
    Depot,
    Kpis,
    LatLng,
    RunStage,
    RunStartResponse,
    RunStatus,
    RunStatusResponse,
    ScenarioCreateRequest,
    ScenarioDefinition,
    ScenarioLifecycleStatus,
    ScenarioType,
    ScenarioTypeSpec,
    ValidationResponse,
)
from .postgres import PostgresService
from .run_state import STAGE_DETAILS, STAGE_ORDER, progress_for_stage
from .scenario_validation import validate_scenario_definition
from .stub_store import store as stub_store


def _plain_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _plain_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _plain_value(value) for key, value in row.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"{", "["}:
        return json.loads(value)
    return value


class LakebaseStore:
    """Lakebase-backed storage for every normal interactive app read and write."""

    def __init__(self, postgres: PostgresService | None = None) -> None:
        self.postgres = postgres or PostgresService()

    def _table(self, name: str) -> str:
        return self.postgres.qualified_table(name)

    def list_depots(self) -> list[Depot]:
        rows = self.postgres.query(
            f"""
            SELECT depot_id, depot_name, region, sales_territory, lat, lng
            FROM {self._table("depots")}
            ORDER BY depot_id
            """
        )
        return [
            Depot(
                depot_id=str(row["depot_id"]),
                name=str(row["depot_name"]),
                region=str(row["region"]),
                sales_territory=str(row["sales_territory"]),
                location=LatLng(lat=float(row["lat"]), lng=float(row["lng"])),
            )
            for row in rows
        ]

    def list_days(self) -> list[str]:
        rows = self.postgres.query(
            f"SELECT DISTINCT delivery_day FROM {self._table('orders')} ORDER BY delivery_day"
        )
        return [str(row["delivery_day"]) for row in rows]

    def list_scenario_types(self) -> list[ScenarioTypeSpec]:
        # Scenario-type metadata is product configuration, not interactive data.
        return stub_store.list_scenario_types()

    def get_baseline_network(self, depot_id: str, delivery_day: str) -> BaselineNetwork:
        row = self.postgres.query_one(
            f"""
            SELECT network_payload
            FROM {self._table("baseline_network_snapshots")}
            WHERE depot_id = %s AND delivery_day = %s
            """,
            (depot_id, delivery_day),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Baseline network snapshot not found.")
        return BaselineNetwork.model_validate(_json_value(row["network_payload"]))

    def get_baseline_kpis(self, depot_id: str, delivery_day: str) -> Kpis:
        row = self.postgres.query_one(
            f"""
            SELECT kpis_payload
            FROM {self._table("baseline_network_snapshots")}
            WHERE depot_id = %s AND delivery_day = %s
            """,
            (depot_id, delivery_day),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Baseline KPI snapshot not found.")
        return Kpis.model_validate(_json_value(row["kpis_payload"]))

    def create_scenario(self, payload: ScenarioCreateRequest) -> tuple[ScenarioDefinition, str]:
        scenario = ScenarioDefinition(
            scenario_id=f"scn_{uuid.uuid4().hex[:12]}",
            scenario_name=payload.scenario_name,
            scenario_type=payload.scenario_type,
            baseline_scenario_id=payload.baseline_scenario_id,
            depot_id=payload.depot_id,
            delivery_day=payload.delivery_day,
            parameters=payload.parameters,
            status="draft",
        )
        with self.postgres.transaction() as connection:
            self.postgres.execute(
                f"""
                INSERT INTO {self._table("scenario_definitions")}
                    (scenario_id, scenario_name, scenario_type, baseline_scenario_id, depot_id, delivery_day, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    scenario.scenario_id,
                    scenario.scenario_name,
                    scenario.scenario_type,
                    scenario.baseline_scenario_id,
                    scenario.depot_id,
                    scenario.delivery_day,
                    scenario.status,
                ),
                connection=connection,
            )
            parameter_rows = [
                (scenario.scenario_id, key, self.postgres.jsonb(value))
                for key, value in scenario.parameters.items()
            ]
            self.postgres.executemany(
                f"""
                INSERT INTO {self._table("scenario_parameters")}
                    (scenario_id, parameter_name, parameter_value)
                VALUES (%s, %s, %s)
                ON CONFLICT (scenario_id, parameter_name)
                DO UPDATE SET parameter_value = EXCLUDED.parameter_value
                """,
                parameter_rows,
                connection=connection,
            )
            self._materialize_overrides(scenario, connection)
        return scenario, "lakebase"

    def _materialize_overrides(self, scenario: ScenarioDefinition, connection: Any) -> None:
        depot: dict[str, Any] | None = None
        eligible_customer_ids: list[str] = []
        needs_depot = scenario.scenario_type in {
            "ma_new_customers",
            "new_customer_growth",
            "facility_move",
            "custom",
        }
        needs_customers = scenario.scenario_type in {
            "delivery_frequency_day_change",
            "custom",
        }
        if needs_depot:
            depot = self.postgres.query_one(
                f"""
                SELECT depot_id, lat, lng
                FROM {self._table("depots")}
                WHERE depot_id = %s
                """,
                (scenario.depot_id,),
                connection=connection,
            )
        if needs_customers:
            rows = self.postgres.query(
                f"""
                SELECT DISTINCT customer_id
                FROM {self._table("orders")}
                WHERE depot_id = %s AND delivery_day = %s
                ORDER BY customer_id
                """,
                (scenario.depot_id, scenario.delivery_day),
                connection=connection,
            )
            eligible_customer_ids = [str(row["customer_id"]) for row in rows]

        override_tables = build_scenario_overrides(
            scenario_id=scenario.scenario_id,
            scenario_type=scenario.scenario_type,
            depot_id=scenario.depot_id,
            delivery_day=scenario.delivery_day,
            parameters=scenario.parameters,
            depot=_plain_row(depot) if depot else None,
            eligible_customer_ids=eligible_customer_ids,
        )
        self._write_override_rows(override_tables, connection)

    def _write_override_rows(
        self,
        override_tables: Mapping[str, list[dict[str, object]]],
        connection: Any,
    ) -> None:
        self.postgres.executemany(
            f"""
            INSERT INTO {self._table("scenario_customer_overrides")} (
                scenario_id, customer_id, override_type, customer_name, depot_id, lat, lng,
                delivery_day, demand_cases, service_minutes, receiving_window_start, receiving_window_end
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scenario_id, customer_id, override_type) DO UPDATE SET
                customer_name = EXCLUDED.customer_name,
                depot_id = EXCLUDED.depot_id,
                lat = EXCLUDED.lat,
                lng = EXCLUDED.lng,
                delivery_day = EXCLUDED.delivery_day,
                demand_cases = EXCLUDED.demand_cases,
                service_minutes = EXCLUDED.service_minutes,
                receiving_window_start = EXCLUDED.receiving_window_start,
                receiving_window_end = EXCLUDED.receiving_window_end
            """,
            [
                (
                    row["scenario_id"],
                    row["customer_id"],
                    row["override_type"],
                    row.get("customer_name"),
                    row.get("depot_id"),
                    row.get("lat"),
                    row.get("lng"),
                    row.get("delivery_day"),
                    row.get("demand_cases"),
                    row.get("service_minutes"),
                    row.get("receiving_window_start"),
                    row.get("receiving_window_end"),
                )
                for row in override_tables.get("scenario_customer_overrides", [])
            ],
            connection=connection,
        )
        self.postgres.executemany(
            f"""
            INSERT INTO {self._table("scenario_fleet_overrides")} (
                scenario_id, depot_id, delivery_day, driver_delta, vehicle_delta, allow_overtime
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (scenario_id, depot_id, delivery_day) DO UPDATE SET
                driver_delta = EXCLUDED.driver_delta,
                vehicle_delta = EXCLUDED.vehicle_delta,
                allow_overtime = EXCLUDED.allow_overtime
            """,
            [
                (
                    row["scenario_id"],
                    row["depot_id"],
                    row["delivery_day"],
                    row.get("driver_delta", 0),
                    row.get("vehicle_delta", 0),
                    row.get("allow_overtime", True),
                )
                for row in override_tables.get("scenario_fleet_overrides", [])
            ],
            connection=connection,
        )
        self.postgres.executemany(
            f"""
            INSERT INTO {self._table("scenario_depot_overrides")} (
                scenario_id, depot_id, new_lat, new_lng, preserve_service_windows
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (scenario_id, depot_id) DO UPDATE SET
                new_lat = EXCLUDED.new_lat,
                new_lng = EXCLUDED.new_lng,
                preserve_service_windows = EXCLUDED.preserve_service_windows
            """,
            [
                (
                    row["scenario_id"],
                    row["depot_id"],
                    row["new_lat"],
                    row["new_lng"],
                    row.get("preserve_service_windows", True),
                )
                for row in override_tables.get("scenario_depot_overrides", [])
            ],
            connection=connection,
        )
        self.postgres.executemany(
            f"""
            INSERT INTO {self._table("scenario_frequency_overrides")} (
                scenario_id, customer_id, baseline_day, scenario_day
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (scenario_id, customer_id, baseline_day) DO UPDATE SET
                scenario_day = EXCLUDED.scenario_day
            """,
            [
                (
                    row["scenario_id"],
                    row["customer_id"],
                    row["baseline_day"],
                    row["scenario_day"],
                )
                for row in override_tables.get("scenario_frequency_overrides", [])
            ],
            connection=connection,
        )
        self.postgres.executemany(
            f"""
            INSERT INTO {self._table("scenario_cost_overrides")} (
                scenario_id, cost_per_mile, labor_regular_hour, overtime_multiplier,
                overtime_threshold_minutes, fixed_truck_daily_cost, late_delivery_penalty,
                missed_delivery_penalty
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scenario_id) DO UPDATE SET
                cost_per_mile = EXCLUDED.cost_per_mile,
                labor_regular_hour = EXCLUDED.labor_regular_hour,
                overtime_multiplier = EXCLUDED.overtime_multiplier,
                overtime_threshold_minutes = EXCLUDED.overtime_threshold_minutes,
                fixed_truck_daily_cost = EXCLUDED.fixed_truck_daily_cost,
                late_delivery_penalty = EXCLUDED.late_delivery_penalty,
                missed_delivery_penalty = EXCLUDED.missed_delivery_penalty
            """,
            [
                (
                    row["scenario_id"],
                    row.get("cost_per_mile"),
                    row.get("labor_regular_hour"),
                    row.get("overtime_multiplier"),
                    row.get("overtime_threshold_minutes"),
                    row.get("fixed_truck_daily_cost"),
                    row.get("late_delivery_penalty"),
                    row.get("missed_delivery_penalty"),
                )
                for row in override_tables.get("scenario_cost_overrides", [])
            ],
            connection=connection,
        )

    def get_scenario_definition(self, scenario_id: str) -> ScenarioDefinition:
        return self._scenario_definition(scenario_id)

    def _scenario_definition(
        self,
        scenario_id: str,
        *,
        connection: Any | None = None,
    ) -> ScenarioDefinition:
        row = self.postgres.query_one(
            f"""
            SELECT scenario_id, scenario_name, scenario_type, baseline_scenario_id, depot_id, delivery_day, status
            FROM {self._table("scenario_definitions")}
            WHERE scenario_id = %s
            """,
            (scenario_id,),
            connection=connection,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        parameter_rows = self.postgres.query(
            f"""
            SELECT parameter_name, parameter_value
            FROM {self._table("scenario_parameters")}
            WHERE scenario_id = %s
            ORDER BY parameter_name
            """,
            (scenario_id,),
            connection=connection,
        )
        return ScenarioDefinition(
            scenario_id=str(row["scenario_id"]),
            scenario_name=str(row["scenario_name"]),
            scenario_type=cast(ScenarioType, str(row["scenario_type"])),
            baseline_scenario_id=str(row["baseline_scenario_id"]),
            depot_id=str(row["depot_id"]),
            delivery_day=str(row["delivery_day"]),
            parameters={
                str(item["parameter_name"]): _json_value(item["parameter_value"])
                for item in parameter_rows
            },
            status=cast(ScenarioLifecycleStatus, str(row["status"])),
        )

    def set_scenario_status(self, scenario_id: str, status: ScenarioLifecycleStatus) -> None:
        updated = self.postgres.execute(
            f"""
            UPDATE {self._table("scenario_definitions")}
            SET status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE scenario_id = %s
            """,
            (status, scenario_id),
        )
        if updated == 0:
            raise HTTPException(status_code=404, detail="Scenario not found.")

    def validate_scenario(self, scenario_id: str) -> ValidationResponse:
        scenario = self.get_scenario_definition(scenario_id)
        validation = validate_scenario_definition(scenario, self.list_scenario_types())
        if validation.valid:
            self.set_scenario_status(scenario_id, "validated")
        return validation

    def get_target_status(self, scenario_id: str) -> str:
        row = self.postgres.query_one(
            f"SELECT payload ->> 'status' AS status FROM {self._table('scenario_results')} WHERE scenario_id = %s",
            (scenario_id,),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Scenario result not found.")
        return str(row["status"])

    def get_scenario_result(self, scenario_id: str) -> ComparisonResult:
        row = self.postgres.query_one(
            f"SELECT payload FROM {self._table('scenario_results')} WHERE scenario_id = %s",
            (scenario_id,),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Scenario result not found.")
        return ComparisonResult.model_validate(_json_value(row["payload"]))

    def load_solver_base_tables(self) -> dict[str, list[dict[str, object]]]:
        table_map = {
            "depots": ("depots", "depot_id"),
            "customers": ("customers", "customer_id"),
            "fleet": ("fleet", "vehicle_id"),
            "orders": ("orders", "order_id"),
            "cost_parameters": ("cost_parameters", "parameter_set_id"),
        }
        return {
            key: [
                _plain_row(row)
                for row in self.postgres.query(
                    f"SELECT * FROM {self._table(table_name)} ORDER BY {order_by}"
                )
            ]
            for key, (table_name, order_by) in table_map.items()
        }

    def load_scenario_override_tables(self, scenario_id: str) -> dict[str, list[dict[str, object]]]:
        names = {
            "scenario_customer_overrides": "customer_id, override_type",
            "scenario_fleet_overrides": "depot_id, delivery_day",
            "scenario_depot_overrides": "depot_id",
            "scenario_frequency_overrides": "customer_id, baseline_day",
            "scenario_cost_overrides": "scenario_id",
        }
        return {
            name: [
                _plain_row(row)
                for row in self.postgres.query(
                    f"SELECT * FROM {self._table(name)} WHERE scenario_id = %s ORDER BY {order_by}",
                    (scenario_id,),
                )
            ]
            for name, order_by in names.items()
        }

    def persist_result(self, scenario: ScenarioDefinition, result: ComparisonResult) -> None:
        """Replace all result families atomically with batched Postgres writes."""
        result_dict = result.model_dump(mode="json")
        scenario_id = scenario.scenario_id
        deltas = result_dict["kpi_deltas"] or {}
        kpis = dict(result_dict["scenario_kpis"] or {})
        cost_breakdown = dict(kpis.pop("cost_breakdown", {}))
        with self.postgres.transaction() as connection:
            for table_name in (
                "scenario_route_delta",
                "scenario_customer_impact",
                "scenario_constraint_violations",
                "scenario_cost_breakdown",
                "scenario_kpis",
                "scenario_comparison_summary",
            ):
                self.postgres.execute(
                    f"DELETE FROM {self._table(table_name)} WHERE scenario_id = %s",
                    (scenario_id,),
                    connection=connection,
                )
            self.postgres.execute(
                f"""
                INSERT INTO {self._table("scenario_results")} (scenario_id, payload, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (scenario_id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = EXCLUDED.updated_at
                """,
                (scenario_id, self.postgres.jsonb(result_dict)),
                connection=connection,
            )
            self.postgres.execute(
                f"""
                INSERT INTO {self._table("scenario_comparison_summary")} (
                    scenario_id, scenario_type, depot_id, delivery_day, status, total_cost_delta,
                    total_miles_delta, route_count_delta, impacted_customer_count, summary
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    scenario_id,
                    scenario.scenario_type,
                    scenario.depot_id,
                    scenario.delivery_day,
                    result.status,
                    deltas.get("total_cost", 0),
                    deltas.get("total_miles", 0),
                    deltas.get("route_count", 0),
                    len(result.customer_impacts),
                    result.summary,
                ),
                connection=connection,
            )
            if kpis:
                self.postgres.execute(
                    f"""
                    INSERT INTO {self._table("scenario_kpis")} (
                        scenario_id, scenario_type, depot_id, delivery_day, route_count, driver_count,
                        vehicle_count, total_miles, drive_minutes, service_minutes, total_cases,
                        avg_stops_per_route, avg_capacity_utilization_pct, avg_driver_utilization_pct,
                        overtime_minutes, missed_windows, late_minutes, mileage_cost, labor_cost,
                        overtime_cost, fixed_vehicle_cost, sla_penalty_cost, total_cost
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        scenario_id,
                        scenario.scenario_type,
                        scenario.depot_id,
                        scenario.delivery_day,
                        kpis["route_count"],
                        kpis["driver_count"],
                        kpis["vehicle_count"],
                        kpis["total_miles"],
                        kpis["drive_minutes"],
                        kpis["service_minutes"],
                        kpis["total_cases"],
                        kpis["avg_stops_per_route"],
                        kpis["avg_capacity_utilization_pct"],
                        kpis["avg_driver_utilization_pct"],
                        kpis["overtime_minutes"],
                        kpis["missed_windows"],
                        kpis["late_minutes"],
                        cost_breakdown["mileage_cost"],
                        cost_breakdown["labor_cost"],
                        cost_breakdown["overtime_cost"],
                        cost_breakdown["fixed_vehicle_cost"],
                        cost_breakdown["sla_penalty_cost"],
                        cost_breakdown["total_cost"],
                    ),
                    connection=connection,
                )
                self.postgres.execute(
                    f"""
                    INSERT INTO {self._table("scenario_cost_breakdown")} (
                        scenario_id, depot_id, delivery_day, mileage_cost, labor_cost, overtime_cost,
                        fixed_vehicle_cost, sla_penalty_cost, total_cost
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        scenario_id,
                        scenario.depot_id,
                        scenario.delivery_day,
                        cost_breakdown["mileage_cost"],
                        cost_breakdown["labor_cost"],
                        cost_breakdown["overtime_cost"],
                        cost_breakdown["fixed_vehicle_cost"],
                        cost_breakdown["sla_penalty_cost"],
                        cost_breakdown["total_cost"],
                    ),
                    connection=connection,
                )
            self.postgres.executemany(
                f"""
                INSERT INTO {self._table("scenario_route_delta")} (
                    scenario_id, route_id, depot_id, delivery_day, total_miles, total_cost, missed_windows
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        scenario_id,
                        route.route_id,
                        route.depot_id,
                        route.delivery_day,
                        route.total_miles,
                        route.total_cost,
                        route.missed_windows,
                    )
                    for route in result.scenario_routes
                ],
                connection=connection,
            )
            self.postgres.executemany(
                f"""
                INSERT INTO {self._table("scenario_customer_impact")} (scenario_id, customer_id, payload)
                VALUES (%s, %s, %s)
                """,
                [
                    (
                        scenario_id,
                        impact.customer_id,
                        self.postgres.jsonb(impact.model_dump(mode="json")),
                    )
                    for impact in result.customer_impacts
                ],
                connection=connection,
            )
            self.postgres.executemany(
                f"""
                INSERT INTO {self._table("scenario_constraint_violations")} (
                    scenario_id, violation_id, payload
                ) VALUES (%s, %s, %s)
                """,
                [
                    (
                        scenario_id,
                        violation.violation_id,
                        self.postgres.jsonb(violation.model_dump(mode="json")),
                    )
                    for violation in result.constraint_violations
                ],
                connection=connection,
            )

    def find_active_run(self, scenario_id: str, endpoint_url: str | None) -> RunStartResponse | None:
        row = self.postgres.query_one(
            f"""
            SELECT run_id, scenario_id, status, message
            FROM {self._table("solve_runs")}
            WHERE scenario_id = %s AND status IN ('queued', 'running')
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (scenario_id,),
        )
        if row is None:
            return None
        return RunStartResponse(
            run_id=str(row["run_id"]),
            scenario_id=str(row["scenario_id"]),
            status=cast(RunStatus, str(row["status"])),
            message=str(row["message"]),
            databricks_run_url=endpoint_url,
        )

    def create_solve_run(
        self,
        scenario: ScenarioDefinition,
        endpoint_url: str | None,
    ) -> RunStartResponse:
        with self.postgres.transaction() as connection:
            # Lock one scenario row so repeated clicks and the auto-run response
            # cannot enqueue concurrent solves for the same scenario.
            self.postgres.query_one(
                f"SELECT scenario_id FROM {self._table('scenario_definitions')} WHERE scenario_id = %s FOR UPDATE",
                (scenario.scenario_id,),
                connection=connection,
            )
            existing = self.postgres.query_one(
                f"""
                SELECT run_id, scenario_id, status, message
                FROM {self._table("solve_runs")}
                WHERE scenario_id = %s AND status IN ('queued', 'running')
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (scenario.scenario_id,),
                connection=connection,
            )
            if existing is not None:
                return RunStartResponse(
                    run_id=str(existing["run_id"]),
                    scenario_id=str(existing["scenario_id"]),
                    status=cast(RunStatus, str(existing["status"])),
                    message=str(existing["message"]),
                    databricks_run_url=endpoint_url,
                )

            run_id = f"run_{uuid.uuid4().hex[:12]}"
            message = "Optimization run has been queued for durable processing."
            self.postgres.execute(
                f"""
                INSERT INTO {self._table("solve_runs")} (run_id, scenario_id, status, stage_id, message)
                VALUES (%s, %s, 'queued', 'queued', %s)
                """,
                (run_id, scenario.scenario_id, message),
                connection=connection,
            )
            self.postgres.executemany(
                f"""
                INSERT INTO {self._table("solve_run_stages")} (run_id, stage_id, stage_status, message)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (
                        run_id,
                        stage_id,
                        "running" if stage_id == "queued" else "pending",
                        STAGE_DETAILS[stage_id][1],
                    )
                    for stage_id in STAGE_ORDER
                ],
                connection=connection,
            )
            self.postgres.execute(
                f"""
                UPDATE {self._table("solve_run_stages")}
                SET started_at = CURRENT_TIMESTAMP
                WHERE run_id = %s AND stage_id = 'queued'
                """,
                (run_id,),
                connection=connection,
            )
        return RunStartResponse(
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            status="queued",
            message=message,
            databricks_run_url=endpoint_url,
        )

    def claim_solve_run(self, run_id: str, worker_id: str) -> ScenarioDefinition | None:
        with self.postgres.transaction() as connection:
            row = self.postgres.query_one(
                f"""
                UPDATE {self._table("solve_runs")}
                SET status = 'running',
                    worker_id = %s,
                    lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes',
                    updated_at = CURRENT_TIMESTAMP
                WHERE run_id = %s
                  AND status NOT IN ('succeeded', 'infeasible', 'failed')
                  AND (
                    worker_id IS NULL
                    OR worker_id = %s
                    OR lease_expires_at IS NULL
                    OR lease_expires_at <= CURRENT_TIMESTAMP
                  )
                RETURNING scenario_id
                """,
                (worker_id, run_id, worker_id),
                connection=connection,
            )
            if row is None:
                return None
            return self._scenario_definition(str(row["scenario_id"]), connection=connection)

    def record_create_duration(self, run_id: str, duration_ms: int) -> None:
        self.postgres.execute(
            f"""
            UPDATE {self._table("solve_runs")}
            SET create_duration_ms = %s, updated_at = CURRENT_TIMESTAMP
            WHERE run_id = %s
            """,
            (max(0, duration_ms), run_id),
        )

    def start_run_stage(self, run_id: str, stage_id: str, message: str, worker_id: str) -> None:
        if stage_id not in STAGE_ORDER:
            raise ValueError(f"Unknown solve-run stage: {stage_id}")
        with self.postgres.transaction() as connection:
            changed = self.postgres.execute(
                f"""
                UPDATE {self._table("solve_runs")}
                SET status = 'running',
                    stage_id = %s,
                    message = %s,
                    lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes',
                    updated_at = CURRENT_TIMESTAMP
                WHERE run_id = %s AND worker_id = %s
                """,
                (stage_id, message, run_id, worker_id),
                connection=connection,
            )
            if changed == 0:
                raise RuntimeError("Solve-run worker lease was lost.")
            self.postgres.execute(
                f"""
                UPDATE {self._table("solve_run_stages")}
                SET stage_status = 'completed',
                    completed_at = CURRENT_TIMESTAMP,
                    duration_ms = CAST(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)) * 1000 AS INTEGER)
                WHERE run_id = %s AND stage_status = 'running' AND stage_id <> %s
                """,
                (run_id, stage_id),
                connection=connection,
            )
            self.postgres.execute(
                f"""
                UPDATE {self._table("solve_run_stages")}
                SET stage_status = 'running',
                    message = %s,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    completed_at = NULL,
                    duration_ms = NULL
                WHERE run_id = %s AND stage_id = %s
                """,
                (message, run_id, stage_id),
                connection=connection,
            )

    def record_run_validation(
        self,
        run_id: str,
        validation: ValidationResponse,
        worker_id: str,
    ) -> None:
        self.postgres.execute(
            f"""
            UPDATE {self._table("solve_runs")}
            SET validation_payload = %s,
                lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes',
                updated_at = CURRENT_TIMESTAMP
            WHERE run_id = %s AND worker_id = %s
            """,
            (self.postgres.jsonb(validation.model_dump(mode="json")), run_id, worker_id),
        )

    def complete_run_stage(self, run_id: str, stage_id: str, worker_id: str) -> None:
        with self.postgres.transaction() as connection:
            self.postgres.execute(
                f"""
                UPDATE {self._table("solve_run_stages")}
                SET stage_status = 'completed',
                    completed_at = CURRENT_TIMESTAMP,
                    duration_ms = CAST(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)) * 1000 AS INTEGER)
                WHERE run_id = %s AND stage_id = %s
                """,
                (run_id, stage_id),
                connection=connection,
            )
            self.postgres.execute(
                f"""
                UPDATE {self._table("solve_runs")}
                SET lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes',
                    updated_at = CURRENT_TIMESTAMP
                WHERE run_id = %s AND worker_id = %s
                """,
                (run_id, worker_id),
                connection=connection,
            )

    def complete_solve_run(
        self,
        run_id: str,
        status: str,
        message: str,
        worker_id: str,
    ) -> None:
        if status not in {"succeeded", "infeasible"}:
            raise ValueError(f"Unexpected terminal solve status: {status}")
        with self.postgres.transaction() as connection:
            self.postgres.execute(
                f"""
                UPDATE {self._table("solve_runs")}
                SET status = %s,
                    stage_id = 'persist',
                    message = %s,
                    completed_at = CURRENT_TIMESTAMP,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE run_id = %s AND worker_id = %s
                """,
                (status, message, run_id, worker_id),
                connection=connection,
            )

    def fail_solve_run(
        self,
        run_id: str,
        stage_id: str,
        message: str,
        worker_id: str,
        *,
        validation: ValidationResponse | None = None,
    ) -> None:
        with self.postgres.transaction() as connection:
            self.postgres.execute(
                f"""
                UPDATE {self._table("solve_run_stages")}
                SET stage_status = 'failed',
                    message = %s,
                    completed_at = CURRENT_TIMESTAMP,
                    duration_ms = CAST(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)) * 1000 AS INTEGER)
                WHERE run_id = %s AND stage_id = %s
                """,
                (message, run_id, stage_id),
                connection=connection,
            )
            self.postgres.execute(
                f"""
                UPDATE {self._table("solve_runs")}
                SET status = 'failed',
                    stage_id = %s,
                    message = %s,
                    validation_payload = COALESCE(%s, validation_payload),
                    error = %s,
                    completed_at = CURRENT_TIMESTAMP,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE run_id = %s AND worker_id = %s
                """,
                (
                    stage_id,
                    message,
                    self.postgres.jsonb(validation.model_dump(mode="json")) if validation else None,
                    message,
                    run_id,
                    worker_id,
                ),
                connection=connection,
            )

    def get_solve_run_status(self, run_id: str, endpoint_url: str | None) -> RunStatusResponse:
        run = self.postgres.query_one(
            f"""
            SELECT run_id, scenario_id, status, stage_id, message, create_duration_ms,
                   validation_payload, started_at, completed_at
            FROM {self._table("solve_runs")}
            WHERE run_id = %s
            """,
            (run_id,),
        )
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        stage_rows = self.postgres.query(
            f"""
            SELECT stage_id, stage_status, message, duration_ms
            FROM {self._table("solve_run_stages")}
            WHERE run_id = %s
            ORDER BY CASE stage_id
                WHEN 'queued' THEN 1 WHEN 'precheck' THEN 2 WHEN 'prepare' THEN 3
                WHEN 'solve' THEN 4 WHEN 'compare' THEN 5 WHEN 'persist' THEN 6 ELSE 99 END
            """,
            (run_id,),
        )
        stages_by_id = {str(row["stage_id"]): row for row in stage_rows}
        stages = [
            RunStage(
                stage_id=stage_id,
                label=STAGE_DETAILS[stage_id][0],
                status=cast(
                    Literal["pending", "running", "completed", "failed"],
                    str(stages_by_id.get(stage_id, {}).get("stage_status", "pending")),
                ),
                message=str(stages_by_id.get(stage_id, {}).get("message", STAGE_DETAILS[stage_id][1])),
                duration_ms=stages_by_id.get(stage_id, {}).get("duration_ms"),
            )
            for stage_id in STAGE_ORDER
        ]
        validation_payload = run["validation_payload"]
        stage_durations_ms = {
            "create": run["create_duration_ms"],
            **{
                stage_id: stages_by_id.get(stage_id, {}).get("duration_ms")
                for stage_id in STAGE_ORDER
            },
        }
        return RunStatusResponse(
            run_id=str(run["run_id"]),
            scenario_id=str(run["scenario_id"]),
            status=cast(RunStatus, str(run["status"])),
            progress_pct=progress_for_stage(str(run["status"]), str(run["stage_id"])),
            message=str(run["message"]),
            stages=stages,
            started_at=_plain_value(run["started_at"]),
            completed_at=_plain_value(run["completed_at"]) if run["completed_at"] else None,
            databricks_run_url=endpoint_url,
            validation=(
                ValidationResponse.model_validate(_json_value(validation_payload))
                if validation_payload is not None
                else None
            ),
            stage_durations_ms=stage_durations_ms,
        )

    def resumable_run_ids(self) -> list[str]:
        rows = self.postgres.query(
            f"""
            SELECT run_id
            FROM {self._table("solve_runs")}
            WHERE status = 'queued'
               OR (status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at <= CURRENT_TIMESTAMP))
            ORDER BY started_at
            """
        )
        return [str(row["run_id"]) for row in rows]


lakebase_store = LakebaseStore()
