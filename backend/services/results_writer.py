from __future__ import annotations

import json
from typing import Any

from ..models import ComparisonResult, ScenarioDefinition
from .sql import SqlService


class ResultsWriter:
    def __init__(self) -> None:
        self.sql = SqlService()

    def persist(self, scenario: ScenarioDefinition, result: ComparisonResult) -> None:
        result_dict = result.model_dump(mode="json")
        scenario_id = scenario.scenario_id

        kpi_rows: list[dict[str, object]] = []
        cost_rows: list[dict[str, object]] = []
        if result_dict["scenario_kpis"]:
            kpis = dict(result_dict["scenario_kpis"])
            cost_breakdown = dict(kpis.pop("cost_breakdown"))
            kpi_rows.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_type": scenario.scenario_type,
                    "depot_id": scenario.depot_id,
                    "delivery_day": scenario.delivery_day,
                    **kpis,
                    **cost_breakdown,
                }
            )
            cost_rows.append(
                {
                    "scenario_id": scenario_id,
                    "depot_id": scenario.depot_id,
                    "delivery_day": scenario.delivery_day,
                    **cost_breakdown,
                }
            )

        deltas = result_dict["kpi_deltas"] or {}
        rows_by_table: dict[str, list[dict[str, object]]] = {
            "app_scenario_results": [
                {"scenario_id": scenario_id, "payload_json": json.dumps(result_dict, sort_keys=True)}
            ],
            "scenario_comparison_summary": [
                {
                    "scenario_id": scenario_id,
                    "scenario_type": scenario.scenario_type,
                    "depot_id": scenario.depot_id,
                    "delivery_day": scenario.delivery_day,
                    "status": result.status,
                    "total_cost_delta": deltas.get("total_cost", 0),
                    "total_miles_delta": deltas.get("total_miles", 0),
                    "route_count_delta": deltas.get("route_count", 0),
                    "impacted_customer_count": len(result.customer_impacts),
                    "summary": result.summary,
                }
            ],
            "scenario_kpis": kpi_rows,
            "scenario_route_delta": [
                {
                    "scenario_id": scenario_id,
                    "route_id": route.route_id,
                    "depot_id": route.depot_id,
                    "delivery_day": route.delivery_day,
                    "total_miles": route.total_miles,
                    "total_cost": route.total_cost,
                    "missed_windows": route.missed_windows,
                }
                for route in result.scenario_routes
            ],
            "scenario_customer_impact": [
                {"scenario_id": scenario_id, **impact.model_dump(mode="json")}
                for impact in result.customer_impacts
            ],
            "scenario_constraint_violations": [
                {"scenario_id": scenario_id, **violation.model_dump(mode="json")}
                for violation in result.constraint_violations
            ],
            "scenario_cost_breakdown": cost_rows,
        }

        for table_name, rows in rows_by_table.items():
            self._replace_rows(table_name, scenario_id, rows)

    def _replace_rows(
        self,
        table_name: str,
        scenario_id: str,
        rows: list[dict[str, object]],
    ) -> None:
        full_name = self.sql.table(table_name)
        self.sql.execute(f"DELETE FROM {full_name} WHERE scenario_id = {_sql_value(scenario_id)}")
        for row in rows:
            columns = ", ".join(f"`{column}`" for column in row)
            values = ", ".join(_sql_value(value) for value in row.values())
            self.sql.execute(f"INSERT INTO {full_name} ({columns}) VALUES ({values})")


def _sql_value(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, sort_keys=True)
    text = str(value).replace("'", "''")
    return f"'{text}'"


results_writer = ResultsWriter()
