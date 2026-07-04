from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from route_opt.baseline import summarize_kpis
from route_opt.compare import compare_scenario
from route_opt.matrix import build_travel_matrix
from route_opt.overrides import apply_overrides
from route_opt.schemas import BASELINE_SCENARIO_ID
from route_opt.solver.payload import OUTPUT_COLUMNS, make_input_row

from ..config import get_route_solver_endpoint, get_workspace_client
from ..models import ComparisonResult, ScenarioDefinition
from .sql import SqlService

BASE_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class ScenarioInputs:
    scenario: dict[str, object]
    depots: list[dict[str, object]]
    customers: list[dict[str, object]]
    fleet: list[dict[str, object]]
    orders: list[dict[str, object]]
    planning_depots: list[dict[str, object]]
    planning_customers: list[dict[str, object]]
    planning_fleet: list[dict[str, object]]
    planning_stops: list[dict[str, object]]
    travel_matrix: list[dict[str, object]]


class SolverService:
    def __init__(self) -> None:
        self.sql = SqlService()
        self._base_cache: tuple[float, dict[str, list[dict[str, object]]]] | None = None

    def prepare_scenario_inputs(self, scenario: ScenarioDefinition) -> ScenarioInputs:
        base = self._load_base_tables()
        scenario_dict = scenario.model_dump()
        materialized = apply_overrides(
            scenario=scenario_dict,
            customers=base["customers"],
            depots=base["depots"],
            fleet=base["fleet"],
            orders=base["orders"],
            override_tables=base["override_tables"],  # type: ignore[arg-type]
        )
        planning_depots = materialized["scenario_planning_depots"]
        planning_customers = materialized["scenario_planning_customers"]
        planning_fleet = materialized["scenario_planning_fleet"]
        planning_stops = materialized["scenario_planning_stops"]

        travel_matrix: list[dict[str, object]] = []
        for depot in planning_depots:
            _, arc_rows = build_travel_matrix(
                scenario_id=scenario.scenario_id,
                depot=depot,
                stops=[
                    row
                    for row in planning_customers
                    if row["scenario_id"] == scenario.scenario_id and row["depot_id"] == depot["depot_id"]
                ],
                delivery_day=scenario.delivery_day,
            )
            travel_matrix.extend(arc_rows)

        return ScenarioInputs(
            scenario=scenario_dict,
            depots=base["depots"],
            customers=base["customers"],
            fleet=base["fleet"],
            orders=base["orders"],
            planning_depots=planning_depots,
            planning_customers=planning_customers,
            planning_fleet=planning_fleet,
            planning_stops=planning_stops,
            travel_matrix=travel_matrix,
        )

    def invoke_endpoint(
        self,
        *,
        scenario_id: str,
        depot_id: str,
        delivery_day: str,
        planning_depots: list[dict[str, object]],
        planning_customers: list[dict[str, object]],
        planning_fleet: list[dict[str, object]],
        planning_stops: list[dict[str, object]],
        travel_matrix: list[dict[str, object]],
    ) -> dict[str, list[dict[str, object]]]:
        row = make_input_row(
            scenario_id=scenario_id,
            depot_id=depot_id,
            delivery_day=delivery_day,
            planning_depots=planning_depots,
            planning_customers=planning_customers,
            planning_fleet=planning_fleet,
            planning_stops=planning_stops,
            travel_matrix=travel_matrix,
        )
        response = get_workspace_client().serving_endpoints.query(
            name=get_route_solver_endpoint(),
            dataframe_records=[row],
        )
        output_row = _first_prediction(response)
        return {
            column: json.loads(output_row[column]) if isinstance(output_row[column], str) else output_row[column]
            for column in OUTPUT_COLUMNS
        }

    def solve_and_compare(self, scenario: ScenarioDefinition) -> ComparisonResult:
        inputs = self.prepare_scenario_inputs(scenario)
        solution = self._solve_inputs(
            scenario_id=scenario.scenario_id,
            delivery_day=scenario.delivery_day,
            planning_depots=inputs.planning_depots,
            planning_customers=inputs.planning_customers,
            planning_fleet=inputs.planning_fleet,
            planning_stops=inputs.planning_stops,
            travel_matrix=inputs.travel_matrix,
        )
        baseline = self._optimized_baseline_result(scenario, inputs)
        baseline_depot = next(row for row in inputs.depots if row["depot_id"] == scenario.depot_id)
        scenario_depot = next(
            row for row in inputs.planning_depots if row["depot_id"] == scenario.depot_id
        )
        result = compare_scenario(
            scenario=inputs.scenario,
            baseline_result=baseline,
            solution=solution,
            baseline_depot=baseline_depot,
            scenario_depot=scenario_depot,
        )
        return ComparisonResult.model_validate(result)

    def _optimized_baseline_result(
        self,
        scenario: ScenarioDefinition,
        inputs: ScenarioInputs,
    ) -> dict[str, object]:
        baseline_scenario = {
            "scenario_id": BASELINE_SCENARIO_ID,
            "scenario_name": "Baseline",
            "scenario_type": "baseline",
            "baseline_scenario_id": BASELINE_SCENARIO_ID,
            "depot_id": scenario.depot_id,
            "delivery_day": scenario.delivery_day,
            "status": "completed",
            "parameters": {},
        }
        materialized = apply_overrides(
            scenario=baseline_scenario,
            customers=inputs.customers,
            depots=inputs.depots,
            fleet=inputs.fleet,
            orders=inputs.orders,
            override_tables={},
        )
        baseline_depots = materialized["scenario_planning_depots"]
        baseline_customers = materialized["scenario_planning_customers"]
        baseline_fleet = materialized["scenario_planning_fleet"]
        baseline_stops = materialized["scenario_planning_stops"]
        baseline_matrix: list[dict[str, object]] = []
        for depot in baseline_depots:
            _, arc_rows = build_travel_matrix(
                scenario_id=BASELINE_SCENARIO_ID,
                depot=depot,
                stops=[
                    row
                    for row in baseline_customers
                    if row["scenario_id"] == BASELINE_SCENARIO_ID and row["depot_id"] == depot["depot_id"]
                ],
                delivery_day=scenario.delivery_day,
            )
            baseline_matrix.extend(arc_rows)
        solution = self._solve_inputs(
            scenario_id=BASELINE_SCENARIO_ID,
            delivery_day=scenario.delivery_day,
            planning_depots=baseline_depots,
            planning_customers=baseline_customers,
            planning_fleet=baseline_fleet,
            planning_stops=baseline_stops,
            travel_matrix=baseline_matrix,
        )
        return {
            "routes": solution["routes"],
            "route_stops": solution["route_stops"],
            "kpis": summarize_kpis(solution["routes"]),
        }

    def _solve_inputs(
        self,
        *,
        scenario_id: str,
        delivery_day: str,
        planning_depots: list[dict[str, object]],
        planning_customers: list[dict[str, object]],
        planning_fleet: list[dict[str, object]],
        planning_stops: list[dict[str, object]],
        travel_matrix: list[dict[str, object]],
    ) -> dict[str, list[dict[str, object]]]:
        solution: dict[str, list[dict[str, object]]] = {
            "routes": [],
            "route_stops": [],
            "unassigned_stops": [],
            "diagnostics": [],
        }
        for depot in planning_depots:
            depot_id = str(depot["depot_id"])
            partition_solution = self.invoke_endpoint(
                scenario_id=scenario_id,
                depot_id=depot_id,
                delivery_day=delivery_day,
                planning_depots=[depot],
                planning_customers=[
                    row
                    for row in planning_customers
                    if row["depot_id"] == depot_id
                ],
                planning_fleet=[
                    row
                    for row in planning_fleet
                    if row["depot_id"] == depot_id
                ],
                planning_stops=[
                    row
                    for row in planning_stops
                    if row["depot_id"] == depot_id
                ],
                travel_matrix=[
                    row
                    for row in travel_matrix
                    if row["depot_id"] == depot_id
                ],
            )
            for column in OUTPUT_COLUMNS:
                solution[column].extend(partition_solution[column])
        return solution

    def _load_base_tables(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._base_cache and now - self._base_cache[0] < BASE_CACHE_TTL_SECONDS:
            return self._base_cache[1]

        base: dict[str, Any] = {
            "depots": self.sql.query(f"SELECT * FROM {self.sql.table('dim_depots_augmented')}"),
            "customers": self.sql.query(f"SELECT * FROM {self.sql.table('dim_customers_augmented')}"),
            "fleet": self.sql.query(f"SELECT * FROM {self.sql.table('dim_fleet_assets')}"),
            "orders": self.sql.query(f"SELECT * FROM {self.sql.table('fact_delivery_orders')}"),
            "override_tables": {
                table_name: self.sql.query(f"SELECT * FROM {self.sql.table(table_name)}")
                for table_name in [
                    "scenario_customer_overrides",
                    "scenario_fleet_overrides",
                    "scenario_depot_overrides",
                    "scenario_frequency_overrides",
                ]
            },
        }
        self._base_cache = (now, base)
        return base


def _first_prediction(response: object) -> dict[str, object]:
    candidates = [
        getattr(response, "predictions", None),
        getattr(response, "outputs", None),
    ]
    as_dict = getattr(response, "as_dict", None)
    if callable(as_dict):
        raw = as_dict()
        candidates.extend([raw.get("predictions"), raw.get("outputs")])

    for candidate in candidates:
        if isinstance(candidate, list) and candidate:
            first = candidate[0]
            if isinstance(first, dict):
                return first
    raise HTTPException(status_code=502, detail="Solver endpoint returned no prediction rows.")


solver_service = SolverService()
