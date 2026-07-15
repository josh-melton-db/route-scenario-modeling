"""One-time Lakebase migration and repeatable synthetic-data seed command."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

from route_opt.baseline import reconstruct_baseline
from route_opt.cost import CostParameters
from route_opt.synthetic import generate_all

from .lakebase_migrations import migrate_lakebase
from .postgres import PostgresService


@dataclass(frozen=True)
class LakebaseSeedReport:
    source: str
    source_counts: dict[str, int]
    persisted_counts: dict[str, int]
    baseline_snapshots: int
    skipped_orphaned_scenario_rows: dict[str, int]


class LakebaseSeedService:
    """Copies a normalized planning dataset into the app-owned Lakebase schema."""

    _REFERENCE_TABLES = {
        "depots": ("depot_master", "depots"),
        "customers": ("location_data", "customers"),
        "fleet": ("fleet_assets", "fleet"),
        "orders": ("fact_delivery_orders", "orders"),
        "cost_parameters": ("cost_parameters", "cost_parameters"),
    }

    def __init__(self, postgres: PostgresService | None = None) -> None:
        self.postgres = postgres or PostgresService()

    def seed(self, dataset: Mapping[str, list[dict[str, object]]], *, source: str) -> LakebaseSeedReport:
        """Upsert reference data, validate it, then rebuild immutable baseline snapshots."""
        migrate_lakebase(self.postgres)
        normalized = self._normalize_dataset(dataset)
        self._validate_reference_rows(normalized)
        self._upsert_reference_rows(normalized)
        self._validate_persisted_reference_rows(normalized)
        skipped_orphaned_scenario_rows = self._upsert_existing_interactive_rows(dataset)
        snapshot_count = self._rebuild_baseline_snapshots(normalized)
        source_counts = {
            target: len(normalized[source_name])
            for target, (source_name, _) in self._REFERENCE_TABLES.items()
        }
        persisted_counts = {
            target: self._count(table_name)
            for target, (_, table_name) in self._REFERENCE_TABLES.items()
        }
        return LakebaseSeedReport(
            source=source,
            source_counts=source_counts,
            persisted_counts=persisted_counts,
            baseline_snapshots=snapshot_count,
            skipped_orphaned_scenario_rows=skipped_orphaned_scenario_rows,
        )

    def seed_synthetic(self, *, seed: int = 42, customer_count: int = 250) -> LakebaseSeedReport:
        return self.seed(
            generate_all(seed=seed, customer_count=customer_count),
            source="route_opt.synthetic",
        )

    def seed_from_uc(self) -> LakebaseSeedReport:
        """Copy the current interactive UC dataset before switching the feature flag."""
        from .sql import SqlService

        sql = SqlService()
        dataset: dict[str, list[dict[str, object]]] = {
            "depot_master": sql.query(
                f"SELECT * FROM {sql.table('dim_depots_augmented')}"
            ),
            "location_data": sql.query(
                f"SELECT * FROM {sql.table('dim_customers_augmented')}"
            ),
            "fleet_assets": sql.query(
                f"SELECT * FROM {sql.table('dim_fleet_assets')}"
            ),
            "fact_delivery_orders": sql.query(
                f"SELECT * FROM {sql.table('fact_delivery_orders')}"
            ),
            "cost_parameters": sql.query(
                f"SELECT * FROM {sql.table('cost_parameters')}"
            ),
            "scenario_definitions": sql.query(
                f"SELECT * FROM {sql.table('scenario_definitions')}"
            ),
            "scenario_parameters": sql.query(
                f"SELECT * FROM {sql.table('scenario_parameters')}"
            ),
            "scenario_customer_overrides": sql.query(
                f"SELECT * FROM {sql.table('scenario_customer_overrides')}"
            ),
            "scenario_fleet_overrides": sql.query(
                f"SELECT * FROM {sql.table('scenario_fleet_overrides')}"
            ),
            "scenario_depot_overrides": sql.query(
                f"SELECT * FROM {sql.table('scenario_depot_overrides')}"
            ),
            "scenario_frequency_overrides": sql.query(
                f"SELECT * FROM {sql.table('scenario_frequency_overrides')}"
            ),
            "scenario_cost_overrides": sql.query(
                f"SELECT * FROM {sql.table('scenario_cost_overrides')}"
            ),
            "app_scenario_results": sql.query(
                f"SELECT * FROM {sql.table('app_scenario_results')}"
            ),
        }
        return self.seed(dataset, source="unity_catalog")

    def _normalize_dataset(
        self,
        dataset: Mapping[str, list[dict[str, object]]],
    ) -> dict[str, list[dict[str, object]]]:
        normalized: dict[str, list[dict[str, object]]] = {}
        for target, (source_name, _) in self._REFERENCE_TABLES.items():
            rows = dataset.get(source_name)
            if rows is None:
                raise ValueError(f"Dataset is missing required source collection: {source_name}")
            normalized[source_name] = [dict(row) for row in rows]
            if target == "orders":
                for row in normalized[source_name]:
                    route_date = row.get("route_date")
                    if route_date is not None:
                        row["route_date"] = str(route_date)
        return normalized

    def _validate_reference_rows(self, dataset: Mapping[str, list[dict[str, object]]]) -> None:
        depots = dataset["depot_master"]
        customers = dataset["location_data"]
        fleet = dataset["fleet_assets"]
        orders = dataset["fact_delivery_orders"]
        costs = dataset["cost_parameters"]
        self._assert_unique(depots, "depot_id", "depots")
        self._assert_unique(customers, "customer_id", "customers")
        self._assert_unique(fleet, "vehicle_id", "fleet")
        self._assert_unique(orders, "order_id", "orders")
        self._assert_unique(costs, "parameter_set_id", "cost_parameters")

        depot_ids = {str(row["depot_id"]) for row in depots}
        customer_ids = {str(row["customer_id"]) for row in customers}
        missing_customer_depots = {
            str(row["depot_id"]) for row in customers if str(row["depot_id"]) not in depot_ids
        }
        missing_fleet_depots = {
            str(row["depot_id"]) for row in fleet if str(row["depot_id"]) not in depot_ids
        }
        missing_order_depots = {
            str(row["depot_id"]) for row in orders if str(row["depot_id"]) not in depot_ids
        }
        missing_order_customers = {
            str(row["customer_id"])
            for row in orders
            if str(row["customer_id"]) not in customer_ids
        }
        if any(
            (
                missing_customer_depots,
                missing_fleet_depots,
                missing_order_depots,
                missing_order_customers,
            )
        ):
            raise ValueError(
                "Reference-data relationship validation failed: "
                f"customer depots={sorted(missing_customer_depots)}, "
                f"fleet depots={sorted(missing_fleet_depots)}, "
                f"order depots={sorted(missing_order_depots)}, "
                f"order customers={sorted(missing_order_customers)}"
            )

    @staticmethod
    def _assert_unique(rows: Iterable[Mapping[str, object]], key: str, label: str) -> None:
        values = [str(row[key]) for row in rows]
        if len(values) != len(set(values)):
            raise ValueError(f"{label} contains duplicate {key} values.")

    def _upsert_reference_rows(self, dataset: Mapping[str, list[dict[str, object]]]) -> None:
        with self.postgres.transaction() as connection:
            self.postgres.executemany(
                f"""
                INSERT INTO {self.postgres.qualified_table("depots")} (
                    depot_id, depot_name, region, sales_territory, lat, lng, operating_calendar,
                    source_system, is_inferred, confidence_level, generated_run_id, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (depot_id) DO UPDATE SET
                    depot_name = EXCLUDED.depot_name,
                    region = EXCLUDED.region,
                    sales_territory = EXCLUDED.sales_territory,
                    lat = EXCLUDED.lat,
                    lng = EXCLUDED.lng,
                    operating_calendar = EXCLUDED.operating_calendar,
                    source_system = EXCLUDED.source_system,
                    is_inferred = EXCLUDED.is_inferred,
                    confidence_level = EXCLUDED.confidence_level,
                    generated_run_id = EXCLUDED.generated_run_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [
                    (
                        row["depot_id"],
                        row["depot_name"],
                        row["region"],
                        row["sales_territory"],
                        row["lat"],
                        row["lng"],
                        row.get("operating_calendar"),
                        row.get("source_system"),
                        row.get("is_inferred", False),
                        row.get("confidence_level"),
                        row.get("generated_run_id"),
                    )
                    for row in dataset["depot_master"]
                ],
                connection=connection,
            )
            self.postgres.executemany(
                f"""
                INSERT INTO {self.postgres.qualified_table("customers")} (
                    customer_id, customer_name, depot_id, region, sales_territory, lat, lng,
                    customer_priority, delivery_frequency, eligible_delivery_days,
                    receiving_window_start, receiving_window_end, service_minutes, special_handling,
                    source_system, is_inferred, confidence_level, generated_run_id, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (customer_id) DO UPDATE SET
                    customer_name = EXCLUDED.customer_name,
                    depot_id = EXCLUDED.depot_id,
                    region = EXCLUDED.region,
                    sales_territory = EXCLUDED.sales_territory,
                    lat = EXCLUDED.lat,
                    lng = EXCLUDED.lng,
                    customer_priority = EXCLUDED.customer_priority,
                    delivery_frequency = EXCLUDED.delivery_frequency,
                    eligible_delivery_days = EXCLUDED.eligible_delivery_days,
                    receiving_window_start = EXCLUDED.receiving_window_start,
                    receiving_window_end = EXCLUDED.receiving_window_end,
                    service_minutes = EXCLUDED.service_minutes,
                    special_handling = EXCLUDED.special_handling,
                    source_system = EXCLUDED.source_system,
                    is_inferred = EXCLUDED.is_inferred,
                    confidence_level = EXCLUDED.confidence_level,
                    generated_run_id = EXCLUDED.generated_run_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [
                    (
                        row["customer_id"],
                        row["customer_name"],
                        row["depot_id"],
                        row["region"],
                        row["sales_territory"],
                        row["lat"],
                        row["lng"],
                        row.get("customer_priority"),
                        row.get("delivery_frequency"),
                        row.get("eligible_delivery_days"),
                        row.get("receiving_window_start"),
                        row.get("receiving_window_end"),
                        row.get("service_minutes"),
                        row.get("special_handling"),
                        row.get("source_system"),
                        row.get("is_inferred", False),
                        row.get("confidence_level"),
                        row.get("generated_run_id"),
                    )
                    for row in dataset["location_data"]
                ],
                connection=connection,
            )
            self.postgres.executemany(
                f"""
                INSERT INTO {self.postgres.qualified_table("fleet")} (
                    vehicle_id, depot_id, vehicle_type, capacity_cases, fixed_truck_daily_cost,
                    cost_per_mile, max_route_minutes, available_days, source_system, is_inferred,
                    confidence_level, generated_run_id, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (vehicle_id) DO UPDATE SET
                    depot_id = EXCLUDED.depot_id,
                    vehicle_type = EXCLUDED.vehicle_type,
                    capacity_cases = EXCLUDED.capacity_cases,
                    fixed_truck_daily_cost = EXCLUDED.fixed_truck_daily_cost,
                    cost_per_mile = EXCLUDED.cost_per_mile,
                    max_route_minutes = EXCLUDED.max_route_minutes,
                    available_days = EXCLUDED.available_days,
                    source_system = EXCLUDED.source_system,
                    is_inferred = EXCLUDED.is_inferred,
                    confidence_level = EXCLUDED.confidence_level,
                    generated_run_id = EXCLUDED.generated_run_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [
                    (
                        row["vehicle_id"],
                        row["depot_id"],
                        row.get("vehicle_type"),
                        row["capacity_cases"],
                        row.get("fixed_truck_daily_cost"),
                        row.get("cost_per_mile"),
                        row.get("max_route_minutes"),
                        row["available_days"],
                        row.get("source_system"),
                        row.get("is_inferred", False),
                        row.get("confidence_level"),
                        row.get("generated_run_id"),
                    )
                    for row in dataset["fleet_assets"]
                ],
                connection=connection,
            )
            self.postgres.executemany(
                f"""
                INSERT INTO {self.postgres.qualified_table("orders")} (
                    order_id, customer_id, depot_id, delivery_day, route_date, demand_cases,
                    product_family, source_system, is_inferred, confidence_level, generated_run_id, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (order_id) DO UPDATE SET
                    customer_id = EXCLUDED.customer_id,
                    depot_id = EXCLUDED.depot_id,
                    delivery_day = EXCLUDED.delivery_day,
                    route_date = EXCLUDED.route_date,
                    demand_cases = EXCLUDED.demand_cases,
                    product_family = EXCLUDED.product_family,
                    source_system = EXCLUDED.source_system,
                    is_inferred = EXCLUDED.is_inferred,
                    confidence_level = EXCLUDED.confidence_level,
                    generated_run_id = EXCLUDED.generated_run_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [
                    (
                        row["order_id"],
                        row["customer_id"],
                        row["depot_id"],
                        row["delivery_day"],
                        row.get("route_date"),
                        row["demand_cases"],
                        row.get("product_family"),
                        row.get("source_system"),
                        row.get("is_inferred", False),
                        row.get("confidence_level"),
                        row.get("generated_run_id"),
                    )
                    for row in dataset["fact_delivery_orders"]
                ],
                connection=connection,
            )
            self.postgres.executemany(
                f"""
                INSERT INTO {self.postgres.qualified_table("cost_parameters")} (
                    parameter_set_id, cost_per_mile, labor_regular_hour, overtime_multiplier,
                    overtime_threshold_minutes, fixed_truck_daily_cost, max_route_minutes,
                    late_delivery_penalty, missed_delivery_penalty, avg_speed_mph, circuity,
                    source_system, is_inferred, confidence_level, generated_run_id, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
                )
                ON CONFLICT (parameter_set_id) DO UPDATE SET
                    cost_per_mile = EXCLUDED.cost_per_mile,
                    labor_regular_hour = EXCLUDED.labor_regular_hour,
                    overtime_multiplier = EXCLUDED.overtime_multiplier,
                    overtime_threshold_minutes = EXCLUDED.overtime_threshold_minutes,
                    fixed_truck_daily_cost = EXCLUDED.fixed_truck_daily_cost,
                    max_route_minutes = EXCLUDED.max_route_minutes,
                    late_delivery_penalty = EXCLUDED.late_delivery_penalty,
                    missed_delivery_penalty = EXCLUDED.missed_delivery_penalty,
                    avg_speed_mph = EXCLUDED.avg_speed_mph,
                    circuity = EXCLUDED.circuity,
                    source_system = EXCLUDED.source_system,
                    is_inferred = EXCLUDED.is_inferred,
                    confidence_level = EXCLUDED.confidence_level,
                    generated_run_id = EXCLUDED.generated_run_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [
                    (
                        row["parameter_set_id"],
                        row["cost_per_mile"],
                        row["labor_regular_hour"],
                        row["overtime_multiplier"],
                        row["overtime_threshold_minutes"],
                        row["fixed_truck_daily_cost"],
                        row["max_route_minutes"],
                        row["late_delivery_penalty"],
                        row["missed_delivery_penalty"],
                        row["avg_speed_mph"],
                        row["circuity"],
                        row.get("source_system"),
                        row.get("is_inferred", False),
                        row.get("confidence_level"),
                        row.get("generated_run_id"),
                    )
                    for row in dataset["cost_parameters"]
                ],
                connection=connection,
            )

    def _validate_persisted_reference_rows(self, dataset: Mapping[str, list[dict[str, object]]]) -> None:
        expected_counts = {
            table_name: len(dataset[source_name])
            for _, (source_name, table_name) in self._REFERENCE_TABLES.items()
        }
        actual_counts = {table_name: self._count(table_name) for table_name in expected_counts}
        too_small = {
            table_name: (expected_counts[table_name], actual_counts[table_name])
            for table_name in expected_counts
            if actual_counts[table_name] < expected_counts[table_name]
        }
        if too_small:
            raise ValueError(f"Lakebase row-count validation failed: {too_small}")
        relationship_checks = {
            "customers_without_depot": f"""
                SELECT COUNT(*) AS count
                FROM {self.postgres.qualified_table("customers")} c
                LEFT JOIN {self.postgres.qualified_table("depots")} d ON d.depot_id = c.depot_id
                WHERE d.depot_id IS NULL
            """,
            "fleet_without_depot": f"""
                SELECT COUNT(*) AS count
                FROM {self.postgres.qualified_table("fleet")} f
                LEFT JOIN {self.postgres.qualified_table("depots")} d ON d.depot_id = f.depot_id
                WHERE d.depot_id IS NULL
            """,
            "orders_without_customer": f"""
                SELECT COUNT(*) AS count
                FROM {self.postgres.qualified_table("orders")} o
                LEFT JOIN {self.postgres.qualified_table("customers")} c ON c.customer_id = o.customer_id
                WHERE c.customer_id IS NULL
            """,
        }
        failed: dict[str, int] = {}
        for name, statement in relationship_checks.items():
            row = self.postgres.query_one(statement)
            count = int(row["count"]) if row else 0
            if count > 0:
                failed[name] = count
        if failed:
            raise ValueError(f"Lakebase relationship validation failed: {failed}")

    def _upsert_existing_interactive_rows(
        self,
        dataset: Mapping[str, list[dict[str, object]]],
    ) -> dict[str, int]:
        """Carry forward valid scenarios while leaving orphaned UC rows untouched."""
        scenario_rows = dataset.get("scenario_definitions", [])
        if not scenario_rows:
            return {}
        scenario_ids = {str(row["scenario_id"]) for row in scenario_rows}
        scenario_scoped_table_names = (
            "scenario_parameters",
            "scenario_customer_overrides",
            "scenario_fleet_overrides",
            "scenario_depot_overrides",
            "scenario_frequency_overrides",
            "scenario_cost_overrides",
            "app_scenario_results",
        )
        scoped_rows: dict[str, list[dict[str, object]]] = {}
        skipped_orphaned_rows: dict[str, int] = {}
        for table_name in scenario_scoped_table_names:
            rows = [dict(row) for row in dataset.get(table_name, [])]
            valid_rows = [row for row in rows if str(row.get("scenario_id", "")) in scenario_ids]
            scoped_rows[table_name] = valid_rows
            skipped_count = len(rows) - len(valid_rows)
            if skipped_count:
                skipped_orphaned_rows[table_name] = skipped_count
        with self.postgres.transaction() as connection:
            self.postgres.executemany(
                f"""
                INSERT INTO {self.postgres.qualified_table("scenario_definitions")} (
                    scenario_id, scenario_name, scenario_type, baseline_scenario_id, depot_id, delivery_day, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (scenario_id) DO UPDATE SET
                    scenario_name = EXCLUDED.scenario_name,
                    scenario_type = EXCLUDED.scenario_type,
                    baseline_scenario_id = EXCLUDED.baseline_scenario_id,
                    depot_id = EXCLUDED.depot_id,
                    delivery_day = EXCLUDED.delivery_day,
                    status = EXCLUDED.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [
                    (
                        row["scenario_id"],
                        row["scenario_name"],
                        row["scenario_type"],
                        row["baseline_scenario_id"],
                        row["depot_id"],
                        row["delivery_day"],
                        row["status"],
                    )
                    for row in scenario_rows
                ],
                connection=connection,
            )
            self.postgres.executemany(
                f"""
                INSERT INTO {self.postgres.qualified_table("scenario_parameters")} (
                    scenario_id, parameter_name, parameter_value
                ) VALUES (%s, %s, %s)
                ON CONFLICT (scenario_id, parameter_name) DO UPDATE SET
                    parameter_value = EXCLUDED.parameter_value
                """,
                [
                    (
                        row["scenario_id"],
                        row["parameter_name"],
                        self.postgres.jsonb(self._decode_parameter_value(row["parameter_value"])),
                    )
                    for row in scoped_rows["scenario_parameters"]
                ],
                connection=connection,
            )
            # The normalized override model is intentionally preserved unchanged.
            from .lakebase_store import LakebaseStore

            LakebaseStore(self.postgres)._write_override_rows(
                {
                    name: scoped_rows[name]
                    for name in (
                        "scenario_customer_overrides",
                        "scenario_fleet_overrides",
                        "scenario_depot_overrides",
                        "scenario_frequency_overrides",
                        "scenario_cost_overrides",
                    )
                },
                connection,
            )
            self.postgres.executemany(
                f"""
                INSERT INTO {self.postgres.qualified_table("scenario_results")} (
                    scenario_id, payload, updated_at
                ) VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (scenario_id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = EXCLUDED.updated_at
                """,
                [
                    (
                        row["scenario_id"],
                        self.postgres.jsonb(self._decode_parameter_value(row["payload_json"])),
                    )
                    for row in scoped_rows["app_scenario_results"]
                ],
                connection=connection,
            )
        return skipped_orphaned_rows

    @staticmethod
    def _decode_parameter_value(value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def _rebuild_baseline_snapshots(self, dataset: Mapping[str, list[dict[str, object]]]) -> int:
        depots = dataset["depot_master"]
        customers = dataset["location_data"]
        orders = dataset["fact_delivery_orders"]
        fleet = dataset["fleet_assets"]
        costs = dataset["cost_parameters"]
        params = CostParameters.from_row(costs[0] if costs else None)
        partitions = sorted(
            {
                (str(row["depot_id"]), str(row["delivery_day"]))
                for row in orders
            }
        )
        with self.postgres.transaction() as connection:
            for depot_id, delivery_day in partitions:
                baseline = reconstruct_baseline(
                    depots=depots,
                    customers=customers,
                    orders=orders,
                    fleet=fleet,
                    depot_id=depot_id,
                    delivery_day=delivery_day,
                    params=params,
                )
                self.postgres.execute(
                    f"""
                    INSERT INTO {self.postgres.qualified_table("baseline_network_snapshots")} (
                        depot_id, delivery_day, network_payload, kpis_payload, generated_at
                    ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (depot_id, delivery_day) DO UPDATE SET
                        network_payload = EXCLUDED.network_payload,
                        kpis_payload = EXCLUDED.kpis_payload,
                        generated_at = EXCLUDED.generated_at
                    """,
                    (
                        depot_id,
                        delivery_day,
                        self.postgres.jsonb(baseline["network"]),
                        self.postgres.jsonb(baseline["kpis"]),
                    ),
                    connection=connection,
                )
        return len(partitions)

    def _count(self, table_name: str) -> int:
        row = self.postgres.query_one(
            f"SELECT COUNT(*) AS count FROM {self.postgres.qualified_table(table_name)}"
        )
        return int(row["count"]) if row else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Lakebase Scenario Studio backend.")
    parser.add_argument(
        "--source",
        choices=("synthetic", "uc"),
        default="synthetic",
        help="Use route_opt.synthetic data or copy the existing UC interactive dataset.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--customer-count", type=int, default=250)
    args = parser.parse_args()
    service = LakebaseSeedService()
    report = (
        service.seed_from_uc()
        if args.source == "uc"
        else service.seed_synthetic(seed=args.seed, customer_count=args.customer_count)
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
