from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException

from ..models import (
    BaselineNetwork,
    ComparisonResult,
    CreateScenarioResponse,
    Depot,
    Kpis,
    ScenarioCreateRequest,
    ScenarioDefinition,
    ScenarioLifecycleStatus,
    ScenarioTypeSpec,
    ValidationResponse,
)
from .sql import SqlService, sql_literal
from .stub_store import store as stub_store


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
        return scenario, "databricks"

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
        if not missing:
            self.set_scenario_status(scenario_id, "validated")
        return ValidationResponse(
            scenario_id=scenario_id,
            valid=not missing,
            hard_constraints=[],
            soft_penalties=[],
            missing_fields=missing,
            inferred_fields=[],
            estimated_affected_customers=0,
            estimated_affected_routes=1,
            summary="Scenario parameters are complete and ready to run."
            if not missing
            else "Scenario is missing required fields.",
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


databricks_store = DatabricksStore()
