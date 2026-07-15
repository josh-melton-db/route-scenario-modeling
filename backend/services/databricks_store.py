from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException

from ..models import (
    BaselineNetwork,
    ComparisonResult,
    Depot,
    Kpis,
    ScenarioCreateRequest,
    ScenarioDefinition,
    ScenarioLifecycleStatus,
    ScenarioTypeSpec,
    ValidationIssue,
    ValidationResponse,
)
from route_opt.overrides import build_scenario_overrides

from .sql import SqlService, sql_literal
from .stub_store import store as stub_store


def _override_sql_value(value: object) -> str:
    """Render a scalar for an override-table INSERT, preserving numeric/boolean types."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


class DatabricksStore:
    """SQL-backed implementation of the stub-store contract.

    The app still receives the same Pydantic models; the only change is that
    payloads come from UC tables/views instead of local JSON stubs.
    """

    def __init__(self) -> None:
        self.sql = SqlService()

    def list_depots(self) -> list[Depot]:
        rows = self.sql.query(
            f"""
            SELECT depot_id, depot_name, region, sales_territory, lat, lng
            FROM {self.sql.table('dim_depots_augmented')}
            ORDER BY depot_id
            """
        )
        return [
            Depot(
                depot_id=str(row["depot_id"]),
                name=str(row["depot_name"]),
                region=str(row["region"]),
                sales_territory=str(row["sales_territory"]),
                location={"lat": float(row["lat"]), "lng": float(row["lng"])},
            )
            for row in rows
        ]

    def list_days(self) -> list[str]:
        rows = self.sql.query(
            f"SELECT DISTINCT delivery_day FROM {self.sql.table('fact_delivery_orders')} ORDER BY delivery_day"
        )
        return [str(row["delivery_day"]) for row in rows]

    def list_scenario_types(self) -> list[ScenarioTypeSpec]:
        return stub_store.list_scenario_types()

    def get_baseline_network(self, depot_id: str, delivery_day: str) -> BaselineNetwork:
        payload = self.sql.payload_json(
            f"""
            SELECT payload_json
            FROM {self.sql.table('baseline_route_daily_summary')}
            WHERE depot_id = {sql_literal(depot_id)}
              AND delivery_day = {sql_literal(delivery_day)}
            LIMIT 1
            """
        )
        return BaselineNetwork.model_validate(payload)

    def get_baseline_kpis(self, depot_id: str, delivery_day: str) -> Kpis:
        rows = self.sql.query(
            f"""
            SELECT *
            FROM {self.sql.table('scenario_kpis')}
            WHERE scenario_id = 'baseline'
              AND depot_id = {sql_literal(depot_id)}
              AND delivery_day = {sql_literal(delivery_day)}
            LIMIT 1
            """
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Baseline KPI row not found.")
        row = rows[0]
        return Kpis.model_validate(
            {
                "route_count": row["route_count"],
                "driver_count": row["driver_count"],
                "vehicle_count": row["vehicle_count"],
                "total_miles": row["total_miles"],
                "drive_minutes": row["drive_minutes"],
                "service_minutes": row["service_minutes"],
                "total_cases": row["total_cases"],
                "avg_stops_per_route": row["avg_stops_per_route"],
                "avg_capacity_utilization_pct": row["avg_capacity_utilization_pct"],
                "avg_driver_utilization_pct": row["avg_driver_utilization_pct"],
                "overtime_minutes": row["overtime_minutes"],
                "missed_windows": row["missed_windows"],
                "late_minutes": row["late_minutes"],
                "cost_breakdown": {
                    "mileage_cost": row["mileage_cost"],
                    "labor_cost": row["labor_cost"],
                    "overtime_cost": row["overtime_cost"],
                    "fixed_vehicle_cost": row["fixed_vehicle_cost"],
                    "sla_penalty_cost": row["sla_penalty_cost"],
                    "total_cost": row["total_cost"],
                },
            }
        )

    def create_scenario(self, payload: ScenarioCreateRequest) -> tuple[ScenarioDefinition, str]:
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
        self.sql.execute(
            f"""
            INSERT INTO {self.sql.table('scenario_definitions')}
            (scenario_id, scenario_name, scenario_type, baseline_scenario_id, depot_id, delivery_day, status, created_at)
            VALUES (
              {sql_literal(scenario.scenario_id)},
              {sql_literal(scenario.scenario_name)},
              {sql_literal(scenario.scenario_type)},
              {sql_literal(scenario.baseline_scenario_id)},
              {sql_literal(scenario.depot_id)},
              {sql_literal(scenario.delivery_day)},
              'draft',
              current_timestamp()
            )
            """
        )
        for key, value in payload.parameters.items():
            self.sql.execute(
                f"""
                INSERT INTO {self.sql.table('scenario_parameters')}
                (scenario_id, parameter_name, parameter_value)
                VALUES ({sql_literal(scenario_id)}, {sql_literal(key)}, {sql_literal(json.dumps(value))})
                """
            )
        self._materialize_overrides(scenario)
        return scenario, "databricks"

    def _materialize_overrides(self, scenario: ScenarioDefinition) -> None:
        """Write normalized override rows so the scenario materializes real changes."""
        depot = None
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
            depot_rows = self.sql.query(
                f"""
                SELECT depot_id, lat, lng
                FROM {self.sql.table('dim_depots_augmented')}
                WHERE depot_id = {sql_literal(scenario.depot_id)}
                LIMIT 1
                """
            )
            if depot_rows:
                depot = depot_rows[0]
        if needs_customers:
            eligible_customer_ids = [
                str(row["customer_id"])
                for row in self.sql.query(
                    f"""
                    SELECT DISTINCT customer_id
                    FROM {self.sql.table('fact_delivery_orders')}
                    WHERE depot_id = {sql_literal(scenario.depot_id)}
                      AND delivery_day = {sql_literal(scenario.delivery_day)}
                    ORDER BY customer_id
                    """
                )
            ]

        override_tables = build_scenario_overrides(
            scenario_id=scenario.scenario_id,
            scenario_type=scenario.scenario_type,
            depot_id=scenario.depot_id,
            delivery_day=scenario.delivery_day,
            parameters=scenario.parameters,
            depot=depot,
            eligible_customer_ids=eligible_customer_ids,
        )
        for table_name, rows in override_tables.items():
            for row in rows:
                columns = ", ".join(f"`{column}`" for column in row)
                values = ", ".join(_override_sql_value(value) for value in row.values())
                self.sql.execute(
                    f"INSERT INTO {self.sql.table(table_name)} ({columns}) VALUES ({values})"
                )

    def get_scenario_definition(self, scenario_id: str) -> ScenarioDefinition:
        rows = self.sql.query(
            f"""
            SELECT *
            FROM {self.sql.table('scenario_definitions')}
            WHERE scenario_id = {sql_literal(scenario_id)}
            LIMIT 1
            """
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        row = rows[0]
        params = self.sql.query(
            f"""
            SELECT parameter_name, parameter_value
            FROM {self.sql.table('scenario_parameters')}
            WHERE scenario_id = {sql_literal(scenario_id)}
            """
        )
        parameters: dict[str, Any] = {}
        for param in params:
            raw = param["parameter_value"]
            try:
                parameters[str(param["parameter_name"])] = json.loads(raw)
            except Exception:
                parameters[str(param["parameter_name"])] = raw
        return ScenarioDefinition(
            scenario_id=str(row["scenario_id"]),
            scenario_name=str(row["scenario_name"]),
            scenario_type=row["scenario_type"],
            baseline_scenario_id=str(row["baseline_scenario_id"]),
            depot_id=str(row["depot_id"]),
            delivery_day=str(row["delivery_day"]),
            parameters=parameters,
            status=row["status"],
        )

    def set_scenario_status(self, scenario_id: str, status: ScenarioLifecycleStatus) -> None:
        self.sql.execute(
            f"""
            UPDATE {self.sql.table('scenario_definitions')}
            SET status = {sql_literal(status)}
            WHERE scenario_id = {sql_literal(scenario_id)}
            """
        )

    def validate_scenario(self, scenario_id: str) -> ValidationResponse:
        scenario = self.get_scenario_definition(scenario_id)
        spec = next(
            spec for spec in self.list_scenario_types() if spec.scenario_type == scenario.scenario_type
        )
        missing = [
            field.name
            for field in spec.fields
            if field.required and scenario.parameters.get(field.name) in (None, "")
        ]
        hard_constraints: list[ValidationIssue] = []
        soft_penalties: list[ValidationIssue] = []
        estimated_customers = 0
        estimated_routes = 1

        if scenario.scenario_type == "custom":
            changes = scenario.parameters.get("changes") or []
            if not isinstance(changes, list) or not changes:
                cost = scenario.parameters.get("cost")
                if not isinstance(cost, dict) or not any(v is not None for v in cost.values()):
                    hard_constraints.append(
                        ValidationIssue(
                            field="changes",
                            scope="scenario",
                            severity="hard",
                            message="Custom scenarios need at least one change or a cost override.",
                        )
                    )
            else:
                for idx, change in enumerate(changes):
                    if not isinstance(change, dict):
                        hard_constraints.append(
                            ValidationIssue(
                                field=f"changes[{idx}]",
                                scope="scenario",
                                severity="hard",
                                message="Each change must be an object with a kind.",
                            )
                        )
                        continue
                    kind = change.get("kind")
                    if kind == "add_deliveries":
                        deliveries = change.get("deliveries") or []
                        if not deliveries:
                            hard_constraints.append(
                                ValidationIssue(
                                    field=f"changes[{idx}].deliveries",
                                    scope="customer",
                                    severity="hard",
                                    message="Add-deliveries changes require at least one delivery pin.",
                                )
                            )
                        else:
                            estimated_customers += len(deliveries)
                            for d_idx, delivery in enumerate(deliveries):
                                if not isinstance(delivery, dict):
                                    continue
                                for coord in ("lat", "lng"):
                                    if delivery.get(coord) is None:
                                        hard_constraints.append(
                                            ValidationIssue(
                                                field=f"changes[{idx}].deliveries[{d_idx}].{coord}",
                                                scope="customer",
                                                severity="hard",
                                                message=f"Delivery is missing {coord}.",
                                            )
                                        )
                    elif kind == "driver_count_change":
                        delta = int(change.get("driver_delta") or 0)
                        if delta == 0:
                            soft_penalties.append(
                                ValidationIssue(
                                    field=f"changes[{idx}].driver_delta",
                                    scope="scenario",
                                    severity="soft",
                                    message="Driver delta is zero and will not change fleet size.",
                                )
                            )
                        if delta < -3:
                            soft_penalties.append(
                                ValidationIssue(
                                    field=f"changes[{idx}].driver_delta",
                                    scope="scenario",
                                    severity="soft",
                                    message="Removing more than 3 drivers may make the network infeasible.",
                                )
                            )
                        estimated_routes = max(estimated_routes, abs(delta) + 1)
                    elif kind == "delivery_frequency_day_change":
                        if not change.get("target_day"):
                            hard_constraints.append(
                                ValidationIssue(
                                    field=f"changes[{idx}].target_day",
                                    scope="customer",
                                    severity="hard",
                                    message="Day-change requires a target_day.",
                                )
                            )
                        estimated_customers += 6
                    elif kind == "facility_move":
                        location = change.get("new_depot_location")
                        if not isinstance(location, dict) or location.get("lat") is None or location.get("lng") is None:
                            hard_constraints.append(
                                ValidationIssue(
                                    field=f"changes[{idx}].new_depot_location",
                                    scope="depot",
                                    severity="hard",
                                    message="Facility move requires a new depot lat/lng.",
                                )
                            )
                        estimated_routes = max(estimated_routes, 3)
                    else:
                        hard_constraints.append(
                            ValidationIssue(
                                field=f"changes[{idx}].kind",
                                scope="scenario",
                                severity="hard",
                                message=f"Unsupported change kind: {kind}",
                            )
                        )
            if isinstance(scenario.parameters.get("cost"), dict):
                soft_penalties.append(
                    ValidationIssue(
                        field="cost",
                        scope="scenario",
                        severity="soft",
                        message="Cost overrides apply to both baseline and scenario costing for a fair comparison.",
                    )
                )
        else:
            estimated_customers = 0
            estimated_routes = 1

        valid = not missing and not hard_constraints
        if valid:
            self.set_scenario_status(scenario_id, "validated")
        return ValidationResponse(
            scenario_id=scenario_id,
            valid=valid,
            hard_constraints=hard_constraints,
            soft_penalties=soft_penalties,
            missing_fields=missing,
            inferred_fields=[],
            estimated_affected_customers=estimated_customers,
            estimated_affected_routes=estimated_routes,
            summary=(
                "Scenario parameters are complete and ready to run."
                if valid
                else "Scenario is missing required fields or has hard validation errors."
            ),
        )

    def get_target_status(self, scenario_id: str) -> str:
        return "succeeded"

    def get_scenario_result(self, scenario_id: str) -> ComparisonResult:
        payload = self.sql.payload_json(
            f"""
            SELECT payload_json
            FROM {self.sql.table('app_scenario_results')}
            WHERE scenario_id = {sql_literal(scenario_id)}
            LIMIT 1
            """
        )
        return ComparisonResult.model_validate(payload)

    def load_solver_base_tables(self) -> dict[str, list[dict[str, object]]]:
        """Compatibility path retained while Lakebase parity is being verified."""
        return {
            "depots": self.sql.query(f"SELECT * FROM {self.sql.table('dim_depots_augmented')}"),
            "customers": self.sql.query(f"SELECT * FROM {self.sql.table('dim_customers_augmented')}"),
            "fleet": self.sql.query(f"SELECT * FROM {self.sql.table('dim_fleet_assets')}"),
            "orders": self.sql.query(f"SELECT * FROM {self.sql.table('fact_delivery_orders')}"),
            "cost_parameters": self.sql.query(f"SELECT * FROM {self.sql.table('cost_parameters')}"),
        }

    def load_scenario_override_tables(
        self,
        scenario_id: str,
    ) -> dict[str, list[dict[str, object]]]:
        return {
            table_name: self.sql.query(
                f"SELECT * FROM {self.sql.table(table_name)} "
                f"WHERE scenario_id = {sql_literal(scenario_id)}"
            )
            for table_name in (
                "scenario_customer_overrides",
                "scenario_fleet_overrides",
                "scenario_depot_overrides",
                "scenario_frequency_overrides",
                "scenario_cost_overrides",
            )
        }


databricks_store = DatabricksStore()
