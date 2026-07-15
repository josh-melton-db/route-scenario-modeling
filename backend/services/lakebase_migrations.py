"""Additive, idempotent schema migrations for the Lakebase application schema."""

from __future__ import annotations

from typing import Iterable

from .postgres import PostgresService

MIGRATION_VERSION = "2026_07_15_lakebase_scenario_studio_v2"


def _statements(postgres: PostgresService) -> Iterable[str]:
    table = postgres.qualified_table
    schema = postgres.schema
    yield f'CREATE SCHEMA IF NOT EXISTS "{schema}"'
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("schema_migrations")} (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("depots")} (
            depot_id TEXT PRIMARY KEY,
            depot_name TEXT NOT NULL,
            region TEXT NOT NULL,
            sales_territory TEXT NOT NULL,
            lat DOUBLE PRECISION NOT NULL,
            lng DOUBLE PRECISION NOT NULL,
            operating_calendar TEXT,
            source_system TEXT,
            is_inferred BOOLEAN NOT NULL DEFAULT FALSE,
            confidence_level TEXT,
            generated_run_id TEXT,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("customers")} (
            customer_id TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            depot_id TEXT NOT NULL REFERENCES {table("depots")} (depot_id),
            region TEXT NOT NULL,
            sales_territory TEXT NOT NULL,
            lat DOUBLE PRECISION NOT NULL,
            lng DOUBLE PRECISION NOT NULL,
            customer_priority TEXT,
            delivery_frequency INTEGER,
            eligible_delivery_days TEXT,
            receiving_window_start TEXT,
            receiving_window_end TEXT,
            service_minutes INTEGER,
            special_handling TEXT,
            source_system TEXT,
            is_inferred BOOLEAN NOT NULL DEFAULT FALSE,
            confidence_level TEXT,
            generated_run_id TEXT,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("fleet")} (
            vehicle_id TEXT PRIMARY KEY,
            depot_id TEXT NOT NULL REFERENCES {table("depots")} (depot_id),
            vehicle_type TEXT,
            capacity_cases INTEGER NOT NULL,
            fixed_truck_daily_cost DOUBLE PRECISION,
            cost_per_mile DOUBLE PRECISION,
            max_route_minutes INTEGER,
            available_days TEXT NOT NULL,
            source_system TEXT,
            is_inferred BOOLEAN NOT NULL DEFAULT FALSE,
            confidence_level TEXT,
            generated_run_id TEXT,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("orders")} (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL REFERENCES {table("customers")} (customer_id),
            depot_id TEXT NOT NULL REFERENCES {table("depots")} (depot_id),
            delivery_day TEXT NOT NULL,
            route_date DATE,
            demand_cases INTEGER NOT NULL,
            product_family TEXT,
            source_system TEXT,
            is_inferred BOOLEAN NOT NULL DEFAULT FALSE,
            confidence_level TEXT,
            generated_run_id TEXT,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("cost_parameters")} (
            parameter_set_id TEXT PRIMARY KEY,
            cost_per_mile DOUBLE PRECISION NOT NULL,
            labor_regular_hour DOUBLE PRECISION NOT NULL,
            overtime_multiplier DOUBLE PRECISION NOT NULL,
            overtime_threshold_minutes INTEGER NOT NULL,
            fixed_truck_daily_cost DOUBLE PRECISION NOT NULL,
            max_route_minutes INTEGER NOT NULL,
            late_delivery_penalty DOUBLE PRECISION NOT NULL,
            missed_delivery_penalty DOUBLE PRECISION NOT NULL,
            avg_speed_mph DOUBLE PRECISION NOT NULL,
            circuity DOUBLE PRECISION NOT NULL,
            source_system TEXT,
            is_inferred BOOLEAN NOT NULL DEFAULT FALSE,
            confidence_level TEXT,
            generated_run_id TEXT,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("baseline_network_snapshots")} (
            depot_id TEXT NOT NULL REFERENCES {table("depots")} (depot_id),
            delivery_day TEXT NOT NULL,
            network_payload JSONB NOT NULL,
            kpis_payload JSONB NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (depot_id, delivery_day)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_definitions")} (
            scenario_id TEXT PRIMARY KEY,
            scenario_name TEXT NOT NULL,
            scenario_type TEXT NOT NULL,
            baseline_scenario_id TEXT NOT NULL,
            depot_id TEXT NOT NULL REFERENCES {table("depots")} (depot_id),
            delivery_day TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_parameters")} (
            scenario_id TEXT NOT NULL REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            parameter_name TEXT NOT NULL,
            parameter_value JSONB NOT NULL,
            PRIMARY KEY (scenario_id, parameter_name)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_customer_overrides")} (
            scenario_id TEXT NOT NULL REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            customer_id TEXT NOT NULL,
            override_type TEXT NOT NULL,
            customer_name TEXT,
            depot_id TEXT,
            lat DOUBLE PRECISION,
            lng DOUBLE PRECISION,
            delivery_day TEXT,
            demand_cases INTEGER,
            service_minutes INTEGER,
            receiving_window_start TEXT,
            receiving_window_end TEXT,
            PRIMARY KEY (scenario_id, customer_id, override_type)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_fleet_overrides")} (
            scenario_id TEXT NOT NULL REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            depot_id TEXT NOT NULL,
            delivery_day TEXT NOT NULL,
            driver_delta INTEGER NOT NULL DEFAULT 0,
            vehicle_delta INTEGER NOT NULL DEFAULT 0,
            allow_overtime BOOLEAN NOT NULL DEFAULT TRUE,
            PRIMARY KEY (scenario_id, depot_id, delivery_day)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_depot_overrides")} (
            scenario_id TEXT NOT NULL REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            depot_id TEXT NOT NULL,
            new_lat DOUBLE PRECISION NOT NULL,
            new_lng DOUBLE PRECISION NOT NULL,
            preserve_service_windows BOOLEAN NOT NULL DEFAULT TRUE,
            PRIMARY KEY (scenario_id, depot_id)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_frequency_overrides")} (
            scenario_id TEXT NOT NULL REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            customer_id TEXT NOT NULL,
            baseline_day TEXT NOT NULL,
            scenario_day TEXT NOT NULL,
            PRIMARY KEY (scenario_id, customer_id, baseline_day)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_cost_overrides")} (
            scenario_id TEXT PRIMARY KEY REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            cost_per_mile DOUBLE PRECISION,
            labor_regular_hour DOUBLE PRECISION,
            overtime_multiplier DOUBLE PRECISION,
            overtime_threshold_minutes INTEGER,
            fixed_truck_daily_cost DOUBLE PRECISION,
            late_delivery_penalty DOUBLE PRECISION,
            missed_delivery_penalty DOUBLE PRECISION
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_results")} (
            scenario_id TEXT PRIMARY KEY REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_comparison_summary")} (
            scenario_id TEXT PRIMARY KEY REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            scenario_type TEXT NOT NULL,
            depot_id TEXT NOT NULL,
            delivery_day TEXT NOT NULL,
            status TEXT NOT NULL,
            total_cost_delta DOUBLE PRECISION NOT NULL DEFAULT 0,
            total_miles_delta DOUBLE PRECISION NOT NULL DEFAULT 0,
            route_count_delta INTEGER NOT NULL DEFAULT 0,
            impacted_customer_count INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_kpis")} (
            scenario_id TEXT PRIMARY KEY REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            scenario_type TEXT NOT NULL,
            depot_id TEXT NOT NULL,
            delivery_day TEXT NOT NULL,
            route_count INTEGER NOT NULL,
            driver_count INTEGER NOT NULL,
            vehicle_count INTEGER NOT NULL,
            total_miles DOUBLE PRECISION NOT NULL,
            drive_minutes INTEGER NOT NULL,
            service_minutes INTEGER NOT NULL,
            total_cases INTEGER NOT NULL,
            avg_stops_per_route DOUBLE PRECISION NOT NULL,
            avg_capacity_utilization_pct DOUBLE PRECISION NOT NULL,
            avg_driver_utilization_pct DOUBLE PRECISION NOT NULL,
            overtime_minutes INTEGER NOT NULL,
            missed_windows INTEGER NOT NULL,
            late_minutes INTEGER NOT NULL,
            mileage_cost DOUBLE PRECISION NOT NULL,
            labor_cost DOUBLE PRECISION NOT NULL,
            overtime_cost DOUBLE PRECISION NOT NULL,
            fixed_vehicle_cost DOUBLE PRECISION NOT NULL,
            sla_penalty_cost DOUBLE PRECISION NOT NULL,
            total_cost DOUBLE PRECISION NOT NULL
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_route_delta")} (
            scenario_id TEXT NOT NULL REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            route_id TEXT NOT NULL,
            depot_id TEXT NOT NULL,
            delivery_day TEXT NOT NULL,
            total_miles DOUBLE PRECISION NOT NULL,
            total_cost DOUBLE PRECISION NOT NULL,
            missed_windows INTEGER NOT NULL,
            PRIMARY KEY (scenario_id, route_id)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_customer_impact")} (
            scenario_id TEXT NOT NULL REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            customer_id TEXT NOT NULL,
            payload JSONB NOT NULL,
            PRIMARY KEY (scenario_id, customer_id)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_constraint_violations")} (
            scenario_id TEXT NOT NULL REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            violation_id TEXT NOT NULL,
            payload JSONB NOT NULL,
            PRIMARY KEY (scenario_id, violation_id)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("scenario_cost_breakdown")} (
            scenario_id TEXT PRIMARY KEY REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            depot_id TEXT NOT NULL,
            delivery_day TEXT NOT NULL,
            mileage_cost DOUBLE PRECISION NOT NULL,
            labor_cost DOUBLE PRECISION NOT NULL,
            overtime_cost DOUBLE PRECISION NOT NULL,
            fixed_vehicle_cost DOUBLE PRECISION NOT NULL,
            sla_penalty_cost DOUBLE PRECISION NOT NULL,
            total_cost DOUBLE PRECISION NOT NULL
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("solve_runs")} (
            run_id TEXT PRIMARY KEY,
            scenario_id TEXT NOT NULL REFERENCES {table("scenario_definitions")} (scenario_id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            message TEXT NOT NULL,
            create_duration_ms INTEGER,
            validation_payload JSONB,
            error TEXT,
            worker_id TEXT,
            lease_expires_at TIMESTAMPTZ,
            started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("solve_run_stages")} (
            run_id TEXT NOT NULL REFERENCES {table("solve_runs")} (run_id) ON DELETE CASCADE,
            stage_id TEXT NOT NULL,
            stage_status TEXT NOT NULL,
            message TEXT NOT NULL,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            duration_ms INTEGER,
            PRIMARY KEY (run_id, stage_id)
        )
    """
    yield f"ALTER TABLE {table('solve_runs')} ADD COLUMN IF NOT EXISTS validation_payload JSONB"
    yield f"ALTER TABLE {table('solve_runs')} ADD COLUMN IF NOT EXISTS create_duration_ms INTEGER"
    yield f"ALTER TABLE {table('solve_runs')} ADD COLUMN IF NOT EXISTS worker_id TEXT"
    yield f"ALTER TABLE {table('solve_runs')} ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ"
    for table_name in ("depots", "customers", "fleet", "orders", "cost_parameters"):
        yield f"ALTER TABLE {table(table_name)} ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1"
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("editor_sessions")} (
            session_id TEXT PRIMARY KEY,
            principal TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMPTZ NOT NULL,
            committed_at TIMESTAMPTZ,
            discarded_at TIMESTAMPTZ
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("editor_session_rows")} (
            session_id TEXT NOT NULL REFERENCES {table("editor_sessions")} (session_id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            row_id TEXT NOT NULL,
            source_row_version INTEGER,
            row_version INTEGER NOT NULL DEFAULT 1,
            operation TEXT NOT NULL DEFAULT 'unchanged',
            original_data JSONB,
            row_data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (session_id, entity_type, row_id)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("editor_audit_events")} (
            event_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES {table("editor_sessions")} (session_id),
            principal TEXT NOT NULL,
            event_type TEXT NOT NULL,
            entity_type TEXT,
            row_id TEXT,
            before_data JSONB,
            after_data JSONB,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"CREATE INDEX IF NOT EXISTS orders_depot_day_idx ON {table('orders')} (depot_id, delivery_day)"
    yield f"CREATE INDEX IF NOT EXISTS scenarios_depot_day_idx ON {table('scenario_definitions')} (depot_id, delivery_day)"
    yield f"CREATE INDEX IF NOT EXISTS solve_runs_active_idx ON {table('solve_runs')} (status, updated_at)"
    yield f"CREATE INDEX IF NOT EXISTS editor_sessions_principal_idx ON {table('editor_sessions')} (principal, status, expires_at)"
    yield f"CREATE INDEX IF NOT EXISTS editor_session_rows_page_idx ON {table('editor_session_rows')} (session_id, entity_type, operation, row_id)"
    yield f"CREATE INDEX IF NOT EXISTS editor_audit_events_session_idx ON {table('editor_audit_events')} (session_id, created_at)"


def migrate_lakebase(postgres: PostgresService | None = None) -> None:
    """Create or add only app-owned Lakebase objects; no UC resources are touched."""
    service = postgres or PostgresService()
    service.initialize()
    migrations_table = service.qualified_table("schema_migrations")
    try:
        applied = service.query_one(
            f"SELECT 1 AS applied FROM {migrations_table} WHERE version = %s",
            (MIGRATION_VERSION,),
        )
    except Exception as exc:
        # The app service principal creates the schema on its first deployed
        # startup. A later operator-led seed can safely skip DDL once that
        # migration is recorded, rather than requiring table ownership.
        if getattr(exc, "sqlstate", None) not in {"42P01", "3F000"}:
            raise
        applied = None
    if applied is not None:
        return
    with service.transaction() as connection:
        for statement in _statements(service):
            service.execute(statement, connection=connection)
        service.execute(
            f"""
            INSERT INTO {migrations_table} (version)
            VALUES (%s)
            ON CONFLICT (version) DO NOTHING
            """,
            (MIGRATION_VERSION,),
            connection=connection,
        )
