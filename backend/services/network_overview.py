from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache
from typing import Any, cast

from fastapi import HTTPException

from route_opt.network_synthetic import national_dataset_cached
from ..config import get_data_backend
from ..models import (
    NetworkFacilityAggregate,
    NetworkFacilityOption,
    NetworkInsight,
    NetworkLaneAggregate,
    NetworkLaneType,
    NetworkMetric,
    NetworkMetricOption,
    NetworkOptions,
    NetworkOverview,
    NetworkOverviewContext,
    NetworkOverviewKpis,
    NetworkPlanVersionOption,
    NetworkRegionOption,
)
from .sql import SqlService, sql_literal

NetworkRows = dict[str, list[dict[str, Any]]]


@lru_cache(maxsize=1)
def _local_network_rows() -> NetworkRows:
    return cast(NetworkRows, national_dataset_cached(seed=42))


def _as_string(value: object) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())  # type: ignore[union-attr]
    return str(value)


def _round_money(value: float) -> float:
    return round(max(0.0, value), 2)


def _percent(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 100, 1) if denominator > 0 else 0.0


def estimate_lane_daily_cost(lane: Mapping[str, Any], assigned_units: int) -> float:
    """Return a deterministic planning cost for the read-only baseline.

    Phase 2 has no route/load assignment yet, so linehaul loads are inferred from
    900-case equipment and local-delivery cost is represented at customer-lane
    grain. Phase 3 replaces these estimates with governed rate snapshots.
    """

    if assigned_units <= 0:
        return 0.0
    distance = float(lane["distance_miles"])
    lane_type = str(lane["lane_type"])
    if lane_type == "LINEHAUL":
        loads = max(1, math.ceil(assigned_units / 900))
        return max(450.0, distance * 3.40) * loads * 1.12
    if lane_type == "MARKET":
        return assigned_units * 0.08 + distance * 2.25
    return max(35.0, distance * 3.0 + assigned_units * 0.55)


def _lane_on_time_pct(utilization_pct: float, transit_minutes: int) -> float:
    utilization_penalty = max(0.0, utilization_pct - 82.0) * 0.28
    transit_penalty = max(0, transit_minutes - 240) / 180 * 0.6
    return round(max(80.0, min(99.4, 99.2 - utilization_penalty - transit_penalty)), 1)


class NetworkOverviewService:
    def __init__(self) -> None:
        self._options_cache: tuple[float, NetworkOptions] | None = None

    def _source(self) -> str:
        if get_data_backend() == "stub":
            return "Deterministic synthetic upstream plans"
        return "Unity Catalog canonical network tables"

    def _load_rows(
        self,
        *,
        demand_plan_version_id: str | None = None,
        capacity_plan_version_id: str | None = None,
        horizon_start: date | None = None,
        horizon_end: date | None = None,
    ) -> NetworkRows:
        if get_data_backend() == "stub":
            return _local_network_rows()
        return self._load_sql_rows(
            demand_plan_version_id=demand_plan_version_id,
            capacity_plan_version_id=capacity_plan_version_id,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
        )

    def load_rows(
        self,
        *,
        demand_plan_version_id: str,
        capacity_plan_version_id: str,
        horizon_start: date,
        horizon_end: date,
    ) -> NetworkRows:
        """Load canonical rows for scenario validation and allocation."""

        return self._load_rows(
            demand_plan_version_id=demand_plan_version_id,
            capacity_plan_version_id=capacity_plan_version_id,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
        )

    def build_overview(
        self,
        rows: NetworkRows,
        *,
        context: NetworkOverviewContext,
        scenario_id: str = "baseline",
    ) -> NetworkOverview:
        return self._build_overview(
            rows,
            context=context.model_copy(update={"scenario_id": scenario_id}),
        )

    def _load_option_rows(self) -> NetworkRows:
        if get_data_backend() == "stub":
            return _local_network_rows()
        sql = SqlService()
        return self._run_sql_queries(
            sql,
            {
                "dim_regions": f"SELECT * FROM {sql.table('dim_regions')}",
                "dim_facilities": f"SELECT * FROM {sql.table('dim_facilities')}",
                "demand_plan_versions": (
                    f"SELECT * FROM {sql.table('demand_plan_versions')} "
                    "ORDER BY published_at DESC"
                ),
                "capacity_plan_versions": (
                    f"SELECT * FROM {sql.table('capacity_plan_versions')} "
                    "ORDER BY published_at DESC"
                ),
            },
        )

    @staticmethod
    def _run_sql_queries(
        sql: SqlService,
        statements: Mapping[str, str],
    ) -> NetworkRows:
        with ThreadPoolExecutor(max_workers=min(6, len(statements))) as executor:
            futures = {
                name: executor.submit(sql.query, statement)
                for name, statement in statements.items()
            }
            return {name: future.result() for name, future in futures.items()}

    def _load_sql_rows(
        self,
        *,
        demand_plan_version_id: str | None,
        capacity_plan_version_id: str | None,
        horizon_start: date | None,
        horizon_end: date | None,
    ) -> NetworkRows:
        sql = SqlService()

        def table(name: str) -> str:
            return sql.table(name)

        fact_filter = ""
        flow_filter = ""
        if horizon_start and horizon_end:
            dates = (
                f"service_date BETWEEN {sql_literal(horizon_start.isoformat())} "
                f"AND {sql_literal(horizon_end.isoformat())}"
            )
            fact_filter = f" WHERE {dates}"
            flow_filter = f" WHERE {dates}"
        demand_filter = fact_filter
        if demand_plan_version_id:
            separator = " AND " if demand_filter else " WHERE "
            demand_filter += (
                f"{separator}demand_plan_version_id = "
                f"{sql_literal(demand_plan_version_id)}"
            )
        capacity_filter = fact_filter
        if capacity_plan_version_id:
            separator = " AND " if capacity_filter else " WHERE "
            capacity_filter += (
                f"{separator}capacity_plan_version_id = "
                f"{sql_literal(capacity_plan_version_id)}"
            )
        if demand_plan_version_id:
            separator = " AND " if flow_filter else " WHERE "
            flow_filter += (
                f"{separator}demand_plan_version_id = "
                f"{sql_literal(demand_plan_version_id)}"
            )
        if capacity_plan_version_id:
            separator = " AND " if flow_filter else " WHERE "
            flow_filter += (
                f"{separator}capacity_plan_version_id = "
                f"{sql_literal(capacity_plan_version_id)}"
            )

        statements = {
            "dim_facilities": f"SELECT * FROM {table('dim_facilities')}",
            "dim_markets": f"SELECT * FROM {table('dim_markets')}",
            "dim_network_customers": f"SELECT * FROM {table('dim_network_customers')}",
            "dim_network_lanes": f"SELECT * FROM {table('dim_network_lanes')}",
            "demand_plan_versions": (
                f"SELECT * FROM {table('demand_plan_versions')} ORDER BY published_at DESC"
            ),
            "capacity_plan_versions": (
                f"SELECT * FROM {table('capacity_plan_versions')} ORDER BY published_at DESC"
            ),
            "demand_plan_daily": f"""
                SELECT
                  demand_plan_version_id,
                  CAST(service_date AS STRING) AS service_date,
                  region_id,
                  distribution_center_id,
                  depot_id,
                  market_id,
                  SUM(demand_units) AS demand_units
                FROM {table('demand_plan_daily')}
                {demand_filter}
                GROUP BY ALL
                """,
            "facility_capacity_daily": f"""
                SELECT
                  capacity_plan_version_id,
                  CAST(service_date AS STRING) AS service_date,
                  facility_id,
                  SUM(capacity_units) AS capacity_units
                FROM {table('facility_capacity_daily')}
                {capacity_filter}
                GROUP BY ALL
                """,
            "lane_capacity_daily": f"""
                SELECT
                  capacity_plan_version_id,
                  CAST(service_date AS STRING) AS service_date,
                  lane_id,
                  SUM(capacity_units) AS capacity_units
                FROM {table('lane_capacity_daily')}
                {capacity_filter}
                GROUP BY ALL
                """,
            "baseline_network_flow_daily": f"""
                SELECT
                  demand_plan_version_id,
                  capacity_plan_version_id,
                  CAST(service_date AS STRING) AS service_date,
                  lane_id,
                  lane_type,
                  SUM(assigned_units) AS assigned_units
                FROM {table('baseline_network_flow_daily')}
                {flow_filter}
                GROUP BY ALL
                """,
        }
        return self._run_sql_queries(sql, statements)

    def get_options(self) -> NetworkOptions:
        now = time.monotonic()
        if self._options_cache and now - self._options_cache[0] < 300:
            return self._options_cache[1].model_copy(deep=True)
        rows = self._load_option_rows()
        demand_plans = sorted(
            rows["demand_plan_versions"],
            key=lambda row: _as_string(row["published_at"]),
            reverse=True,
        )
        capacity_plans = sorted(
            rows["capacity_plan_versions"],
            key=lambda row: _as_string(row["published_at"]),
            reverse=True,
        )
        regions = sorted(rows["dim_regions"], key=lambda row: str(row["region_name"]))
        if not demand_plans or not capacity_plans or not regions:
            raise HTTPException(
                status_code=503,
                detail="Canonical network plan metadata is not available.",
            )
        demand_default = demand_plans[0]
        capacity_default = capacity_plans[0]
        freshness = max(
            _as_string(demand_default["published_at"]),
            _as_string(capacity_default["published_at"]),
        )
        options = NetworkOptions(
            regions=[
                NetworkRegionOption(region_id="ALL", region_name="All regions")
            ]
            + [
                NetworkRegionOption(
                    region_id=str(row["region_id"]),
                    region_name=str(row["region_name"]),
                )
                for row in regions
            ],
            facilities=[
                NetworkFacilityOption.model_validate(
                    {
                        key: row.get(key)
                        for key in (
                            "facility_id",
                            "facility_name",
                            "facility_type",
                            "region_id",
                            "parent_facility_id",
                        )
                    }
                )
                for row in sorted(
                    rows["dim_facilities"], key=lambda row: str(row["facility_name"])
                )
            ],
            demand_plans=[self._plan_option(row) for row in demand_plans],
            capacity_plans=[self._plan_option(row) for row in capacity_plans],
            lane_types=["ALL", "LINEHAUL", "MARKET", "DELIVERY"],
            metrics=[
                NetworkMetricOption(
                    metric_id="assigned_flow", label="Assigned flow", unit="cases"
                ),
                NetworkMetricOption(
                    metric_id="utilization", label="Capacity utilization", unit="%"
                ),
                NetworkMetricOption(metric_id="cost", label="Modeled cost", unit="USD"),
                NetworkMetricOption(
                    metric_id="cost_per_unit", label="Cost per case", unit="USD/case"
                ),
            ],
            default_demand_plan_version_id=str(demand_default["plan_version_id"]),
            default_capacity_plan_version_id=str(capacity_default["plan_version_id"]),
            default_horizon_start=_as_string(demand_default["horizon_start"]),
            default_horizon_end=_as_string(demand_default["horizon_end"]),
            default_region_id="ALL",
            source=self._source(),
            freshness_at=freshness,
        )
        self._options_cache = (now, options)
        return options.model_copy(deep=True)

    @staticmethod
    def _plan_option(row: Mapping[str, Any]) -> NetworkPlanVersionOption:
        return NetworkPlanVersionOption(
            plan_version_id=str(row["plan_version_id"]),
            display_name=str(row["display_name"]),
            as_of_date=_as_string(row["as_of_date"]),
            horizon_start=_as_string(row["horizon_start"]),
            horizon_end=_as_string(row["horizon_end"]),
            status="published",
            validation_status="passed",
        )

    def get_overview(
        self,
        *,
        demand_plan_version_id: str | None,
        capacity_plan_version_id: str | None,
        horizon_start: date | None,
        horizon_end: date | None,
        region_id: str | None,
        lane_type: NetworkLaneType,
        metric: NetworkMetric,
    ) -> NetworkOverview:
        options = self.get_options()
        demand_id = demand_plan_version_id or options.default_demand_plan_version_id
        capacity_id = capacity_plan_version_id or options.default_capacity_plan_version_id
        start = horizon_start or date.fromisoformat(options.default_horizon_start)
        end = horizon_end or date.fromisoformat(options.default_horizon_end)
        selected_region = region_id or options.default_region_id
        if end < start:
            raise HTTPException(status_code=400, detail="Horizon end must not precede start.")
        if demand_id not in {row.plan_version_id for row in options.demand_plans}:
            raise HTTPException(status_code=404, detail="Demand plan version not found.")
        if capacity_id not in {row.plan_version_id for row in options.capacity_plans}:
            raise HTTPException(status_code=404, detail="Capacity plan version not found.")
        if selected_region not in {row.region_id for row in options.regions}:
            raise HTTPException(status_code=404, detail="Network region not found.")

        rows = self._load_rows(
            demand_plan_version_id=demand_id,
            capacity_plan_version_id=capacity_id,
            horizon_start=start,
            horizon_end=end,
        )
        return self._build_overview(
            rows,
            context=NetworkOverviewContext(
                demand_plan_version_id=demand_id,
                capacity_plan_version_id=capacity_id,
                horizon_start=start.isoformat(),
                horizon_end=end.isoformat(),
                region_id=selected_region,
                lane_type=lane_type,
                metric=metric,
            ),
        )

    def _build_overview(
        self,
        rows: NetworkRows,
        *,
        context: NetworkOverviewContext,
    ) -> NetworkOverview:
        facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
        markets = {str(row["market_id"]): row for row in rows["dim_markets"]}
        customers = {
            str(row["customer_id"]): row for row in rows["dim_network_customers"]
        }
        lanes = {str(row["lane_id"]): row for row in rows["dim_network_lanes"]}
        start = date.fromisoformat(context.horizon_start)
        end = date.fromisoformat(context.horizon_end)

        def in_horizon(row: Mapping[str, Any]) -> bool:
            row_date = date.fromisoformat(_as_string(row["service_date"])[:10])
            return start <= row_date <= end

        demand_by_depot: defaultdict[str, int] = defaultdict(int)
        total_demand = 0
        for row in rows["demand_plan_daily"]:
            if (
                str(row["demand_plan_version_id"]) != context.demand_plan_version_id
                or (
                    context.region_id != "ALL"
                    and str(row["region_id"]) != context.region_id
                )
                or not in_horizon(row)
            ):
                continue
            units = int(row["demand_units"])
            demand_by_depot[str(row["depot_id"])] += units
            total_demand += units

        facility_capacity: defaultdict[str, int] = defaultdict(int)
        for row in rows["facility_capacity_daily"]:
            if (
                str(row["capacity_plan_version_id"]) == context.capacity_plan_version_id
                and in_horizon(row)
            ):
                facility_capacity[str(row["facility_id"])] += int(row["capacity_units"])

        lane_capacity: defaultdict[str, int] = defaultdict(int)
        for row in rows["lane_capacity_daily"]:
            if (
                str(row["capacity_plan_version_id"]) == context.capacity_plan_version_id
                and in_horizon(row)
            ):
                lane_capacity[str(row["lane_id"])] += int(row["capacity_units"])

        daily_flow: defaultdict[str, list[int]] = defaultdict(list)
        lane_assigned: defaultdict[str, int] = defaultdict(int)
        for row in rows["baseline_network_flow_daily"]:
            if (
                str(row["demand_plan_version_id"]) != context.demand_plan_version_id
                or str(row["capacity_plan_version_id"]) != context.capacity_plan_version_id
                or not in_horizon(row)
            ):
                continue
            lane_id = str(row["lane_id"])
            units = int(row["assigned_units"])
            lane_assigned[lane_id] += units
            daily_flow[lane_id].append(units)

        has_scenario_costs = "network_flow_cost_daily" in rows
        scenario_cost_by_lane: defaultdict[str, float] = defaultdict(float)
        for row in rows.get("network_flow_cost_daily", []):
            if not in_horizon(row):
                continue
            scenario_cost_by_lane[str(row["lane_id"])] += float(row["total_cost"])

        def endpoint(
            endpoint_type: str, endpoint_id: str
        ) -> tuple[str, dict[str, float]]:
            indexes = {
                "facility": facilities,
                "market": markets,
                "customer": customers,
            }
            row = indexes[endpoint_type].get(endpoint_id)
            if row is None:
                raise HTTPException(
                    status_code=500,
                    detail=f"Lane endpoint {endpoint_type}:{endpoint_id} is missing.",
                )
            name_fields = {
                "facility": "facility_name",
                "market": "market_name",
                "customer": "customer_name",
            }
            return str(row[name_fields[endpoint_type]]), {
                "lat": float(row["lat"]),
                "lng": float(row["lng"]),
            }

        lane_aggregates: list[NetworkLaneAggregate] = []
        for lane_id, lane in lanes.items():
            origin = facilities.get(str(lane["origin_endpoint_id"]))
            if origin is None or (
                context.region_id != "ALL"
                and str(origin["region_id"]) != context.region_id
            ):
                continue
            if context.lane_type != "ALL" and lane["lane_type"] != context.lane_type:
                continue
            assigned = lane_assigned[lane_id]
            capacity = lane_capacity[lane_id]
            utilization = _percent(assigned, capacity)
            lane_cost = (
                scenario_cost_by_lane[lane_id]
                if has_scenario_costs
                else sum(
                    estimate_lane_daily_cost(lane, units)
                    for units in daily_flow[lane_id]
                )
            )
            origin_name, origin_location = endpoint(
                str(lane["origin_endpoint_type"]), str(lane["origin_endpoint_id"])
            )
            destination_name, destination_location = endpoint(
                str(lane["destination_endpoint_type"]),
                str(lane["destination_endpoint_id"]),
            )
            is_covered_linehaul = (
                lane["lane_type"] == "LINEHAUL"
                and str(origin["region_id"]) == "REGION_GREAT_LAKES"
            )
            lane_aggregates.append(
                NetworkLaneAggregate(
                    lane_id=lane_id,
                    lane_name=str(lane["lane_name"]),
                    lane_type=cast(Any, str(lane["lane_type"])),
                    origin_endpoint_id=str(lane["origin_endpoint_id"]),
                    origin_endpoint_name=origin_name,
                    origin_endpoint_type=cast(Any, str(lane["origin_endpoint_type"])),
                    origin_location=origin_location,
                    destination_endpoint_id=str(lane["destination_endpoint_id"]),
                    destination_endpoint_name=destination_name,
                    destination_endpoint_type=cast(
                        Any, str(lane["destination_endpoint_type"])
                    ),
                    destination_location=destination_location,
                    mode=str(lane["mode"]),
                    distance_miles=float(lane["distance_miles"]),
                    transit_minutes=int(lane["transit_minutes"]),
                    assigned_units=assigned,
                    capacity_units=capacity,
                    utilization_pct=utilization,
                    total_cost=_round_money(lane_cost),
                    cost_per_unit=_round_money(lane_cost / assigned if assigned else 0),
                    on_time_pct=_lane_on_time_pct(
                        utilization, int(lane["transit_minutes"])
                    ),
                    contract_coverage=(
                        "covered"
                        if is_covered_linehaul
                        else "partial"
                        if lane["lane_type"] == "LINEHAUL"
                        else "not_required"
                    ),
                    contract_id=(
                        "GL_STANDARD_2026" if is_covered_linehaul else None
                    ),
                    contract_version_id=(
                        "GL_STANDARD_2026_V1" if is_covered_linehaul else None
                    ),
                    included_in_network_cost=lane["lane_type"] != "MARKET",
                )
            )
        lane_aggregates.sort(key=lambda row: (-row.assigned_units, row.lane_name))

        children: defaultdict[str, list[str]] = defaultdict(list)
        for facility in facilities.values():
            parent_id = facility.get("parent_facility_id")
            if parent_id:
                children[str(parent_id)].append(str(facility["facility_id"]))

        connected: defaultdict[str, set[str]] = defaultdict(set)
        for lane in lanes.values():
            if lane["lane_type"] != "LINEHAUL":
                continue
            origin_id = str(lane["origin_endpoint_id"])
            destination_id = str(lane["destination_endpoint_id"])
            if origin_id in facilities and destination_id in facilities:
                connected[origin_id].add(destination_id)
                connected[destination_id].add(origin_id)

        facility_aggregates: list[NetworkFacilityAggregate] = []
        local_detail_ids = set(facilities)
        for facility_id, facility in facilities.items():
            if (
                context.region_id != "ALL"
                and str(facility["region_id"]) != context.region_id
            ):
                continue
            if facility["facility_type"] == "distribution_center":
                demand = sum(demand_by_depot[depot_id] for depot_id in children[facility_id])
            else:
                demand = demand_by_depot[facility_id]
            touching = [
                row
                for row in lane_aggregates
                if row.origin_endpoint_id == facility_id
                or row.destination_endpoint_id == facility_id
            ]
            inbound = sum(
                row.assigned_units
                for row in touching
                if row.destination_endpoint_id == facility_id
            )
            outbound = sum(
                row.assigned_units for row in touching if row.origin_endpoint_id == facility_id
            )
            assigned = max(inbound, outbound)
            cost = sum(
                row.total_cost for row in touching if row.origin_endpoint_id == facility_id
            )
            weighted_units = sum(row.assigned_units for row in touching)
            on_time = (
                sum(row.on_time_pct * row.assigned_units for row in touching) / weighted_units
                if weighted_units
                else 99.2
            )
            capacity = facility_capacity[facility_id]
            facility_aggregates.append(
                NetworkFacilityAggregate(
                    facility_id=facility_id,
                    facility_name=str(facility["facility_name"]),
                    facility_type=cast(Any, str(facility["facility_type"])),
                    region_id=str(facility["region_id"]),
                    parent_facility_id=(
                        str(facility["parent_facility_id"])
                        if facility.get("parent_facility_id")
                        else None
                    ),
                    location={"lat": float(facility["lat"]), "lng": float(facility["lng"])},
                    demand_units=demand,
                    assigned_units=assigned,
                    capacity_units=capacity,
                    utilization_pct=_percent(assigned, capacity),
                    total_cost=_round_money(cost),
                    cost_per_unit=_round_money(cost / assigned if assigned else 0),
                    on_time_pct=round(on_time, 1),
                    connected_facility_count=len(connected[facility_id]),
                    depot_count=len(children[facility_id]),
                    depot_analysis_available=(
                        facility["facility_type"] == "depot"
                        and facility_id in local_detail_ids
                    ),
                )
            )
        facility_aggregates.sort(
            key=lambda row: (row.facility_type != "distribution_center", row.facility_name)
        )

        if context.lane_type == "ALL":
            kpi_lanes = [row for row in lane_aggregates if row.lane_type == "DELIVERY"]
            cost_lanes = [row for row in lane_aggregates if row.included_in_network_cost]
            depot_ids = {
                row.facility_id
                for row in facility_aggregates
                if row.facility_type == "depot"
            }
            utilization_numerator = sum(demand_by_depot[depot_id] for depot_id in depot_ids)
            utilization_denominator = sum(facility_capacity[depot_id] for depot_id in depot_ids)
        else:
            kpi_lanes = lane_aggregates
            cost_lanes = lane_aggregates
            utilization_numerator = sum(row.assigned_units for row in lane_aggregates)
            utilization_denominator = sum(row.capacity_units for row in lane_aggregates)
        assigned_units = sum(row.assigned_units for row in kpi_lanes)
        total_cost = sum(row.total_cost for row in cost_lanes)
        on_time_weight = sum(row.assigned_units for row in kpi_lanes)
        on_time = (
            sum(row.on_time_pct * row.assigned_units for row in kpi_lanes) / on_time_weight
            if on_time_weight
            else 100.0
        )
        kpis = NetworkOverviewKpis(
            demand_units=total_demand,
            assigned_units=assigned_units,
            unmet_units=max(0, total_demand - assigned_units),
            total_cost=_round_money(total_cost),
            cost_per_unit=_round_money(total_cost / assigned_units if assigned_units else 0),
            on_time_pct=round(on_time, 1),
            utilization_pct=_percent(utilization_numerator, utilization_denominator),
        )
        insights = self._build_insights(kpis, lane_aggregates)
        freshness = max(
            (
                _as_string(row["published_at"])
                for row in (
                    rows["demand_plan_versions"] + rows["capacity_plan_versions"]
                )
            ),
            default=context.horizon_end,
        )
        return NetworkOverview(
            context=context,
            kpis=kpis,
            facilities=facility_aggregates,
            lanes=lane_aggregates,
            insights=insights,
            summary=(
                f"{assigned_units:,} of {total_demand:,} cases are assigned for "
                f"{context.horizon_start} through {context.horizon_end}."
            ),
            source=self._source(),
            freshness_at=freshness,
        )

    @staticmethod
    def _build_insights(
        kpis: NetworkOverviewKpis,
        lanes: Sequence[NetworkLaneAggregate],
    ) -> list[NetworkInsight]:
        insights: list[NetworkInsight] = []
        active = [row for row in lanes if row.assigned_units > 0]
        if kpis.unmet_units:
            insights.append(
                NetworkInsight(
                    insight_id="unmet-demand",
                    insight_type="unmet_demand",
                    severity="critical",
                    title=f"{kpis.unmet_units:,} cases remain unassigned",
                    summary="Assigned flow does not fully reconcile to the selected demand plan.",
                    entity_type="network",
                    metric_value=kpis.unmet_units,
                    metric_unit="cases",
                )
            )
        if active:
            bottleneck = max(active, key=lambda row: row.utilization_pct)
            insights.append(
                NetworkInsight(
                    insight_id=f"bottleneck-{bottleneck.lane_id}",
                    insight_type="bottleneck",
                    severity="warning" if bottleneck.utilization_pct >= 85 else "info",
                    title=f"{bottleneck.lane_name} has the highest utilization",
                    summary=(
                        f"{bottleneck.assigned_units:,} of {bottleneck.capacity_units:,} "
                        "supplied cases are assigned."
                    ),
                    entity_type="lane",
                    entity_id=bottleneck.lane_id,
                    metric_value=bottleneck.utilization_pct,
                    metric_unit="%",
                )
            )
            contract_gap = next(
                (row for row in active if row.contract_coverage == "partial"),
                None,
            )
            if contract_gap:
                insights.append(
                    NetworkInsight(
                        insight_id=f"contract-{contract_gap.lane_id}",
                        insight_type="contract_gap",
                        severity="warning",
                        title=f"{contract_gap.lane_name} lacks governed linehaul coverage",
                        summary=(
                            "Modeled planning cost is available, but no published canonical "
                            "rate-book lane is attached."
                        ),
                        entity_type="lane",
                        entity_id=contract_gap.lane_id,
                    )
                )
            underused_pool = [row for row in lanes if row.capacity_units > 0]
            if underused_pool:
                underused = min(underused_pool, key=lambda row: row.utilization_pct)
                insights.append(
                    NetworkInsight(
                        insight_id=f"underused-{underused.lane_id}",
                        insight_type="underutilized_capacity",
                        severity="info",
                        title=f"{underused.lane_name} has the most headroom",
                        summary=(
                            f"{max(0, underused.capacity_units - underused.assigned_units):,} "
                            "cases of supplied lane capacity remain."
                        ),
                        entity_type="lane",
                        entity_id=underused.lane_id,
                        metric_value=underused.utilization_pct,
                        metric_unit="%",
                    )
                )
            high_cost = max(active, key=lambda row: row.total_cost)
            insights.append(
                NetworkInsight(
                    insight_id=f"cost-{high_cost.lane_id}",
                    insight_type="high_cost",
                    severity="info",
                    title=f"{high_cost.lane_name} is the highest-cost lane",
                    summary=(
                        f"Modeled cost is ${high_cost.total_cost:,.0f}, or "
                        f"${high_cost.cost_per_unit:,.2f} per case."
                    ),
                    entity_type="lane",
                    entity_id=high_cost.lane_id,
                    metric_value=high_cost.total_cost,
                    metric_unit="USD",
                )
            )
            service_risk = min(active, key=lambda row: row.on_time_pct)
            insights.append(
                NetworkInsight(
                    insight_id=f"service-{service_risk.lane_id}",
                    insight_type="service_risk",
                    severity="warning" if service_risk.on_time_pct < 95 else "info",
                    title=f"{service_risk.lane_name} has the lowest service outlook",
                    summary="Service outlook reflects supplied capacity and planned transit time.",
                    entity_type="lane",
                    entity_id=service_risk.lane_id,
                    metric_value=service_risk.on_time_pct,
                    metric_unit="% on time",
                )
            )
        return insights[:5]


network_overview_service = NetworkOverviewService()
