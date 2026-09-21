"""Additive, idempotent schema migrations for the Lakebase application schema."""

from __future__ import annotations

from typing import Iterable

from .postgres import PostgresService

MIGRATION_VERSION = "2026_09_16_rate_authoring_v6"


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
        CREATE TABLE IF NOT EXISTS {table("carriers")} (
            carrier_id TEXT PRIMARY KEY,
            carrier_name TEXT NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("carrier_contracts")} (
            contract_id TEXT PRIMARY KEY,
            carrier_id TEXT NOT NULL REFERENCES {table("carriers")} (carrier_id),
            contract_name TEXT NOT NULL,
            capacity_stops INTEGER NOT NULL,
            rate_per_mile DOUBLE PRECISION NOT NULL,
            rate_per_stop DOUBLE PRECISION NOT NULL,
            minimum_charge DOUBLE PRECISION NOT NULL,
            fuel_surcharge_pct DOUBLE PRECISION NOT NULL,
            effective_start DATE,
            effective_end DATE,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("contract_versions")} (
            version_id TEXT PRIMARY KEY,
            contract_id TEXT NOT NULL REFERENCES {table("carrier_contracts")} (contract_id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'expired')),
            currency TEXT NOT NULL DEFAULT 'USD',
            effective_start DATE,
            effective_end DATE,
            published_at TIMESTAMPTZ,
            published_by TEXT,
            change_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (contract_id, version_number)
        )
    """
    yield f"ALTER TABLE {table('contract_versions')} ADD COLUMN IF NOT EXISTS change_reason TEXT"
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("contract_lane_rates")} (
            rule_id TEXT PRIMARY KEY,
            version_id TEXT NOT NULL REFERENCES {table("contract_versions")} (version_id) ON DELETE CASCADE,
            lane_name TEXT NOT NULL,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            lane_type TEXT,
            origin_endpoint_id TEXT,
            origin_endpoint_type TEXT,
            destination_endpoint_id TEXT,
            destination_endpoint_type TEXT,
            priority INTEGER NOT NULL DEFAULT 100,
            flat_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
            rate_per_mile DOUBLE PRECISION NOT NULL DEFAULT 0,
            rate_per_stop DOUBLE PRECISION NOT NULL DEFAULT 0,
            included_stops INTEGER NOT NULL DEFAULT 0,
            minimum_charge DOUBLE PRECISION NOT NULL DEFAULT 0,
            mileage_rounding TEXT NOT NULL DEFAULT 'exact'
        )
    """
    yield f"ALTER TABLE {table('contract_lane_rates')} ADD COLUMN IF NOT EXISTS lane_type TEXT"
    yield f"ALTER TABLE {table('contract_lane_rates')} ADD COLUMN IF NOT EXISTS origin_endpoint_id TEXT"
    yield f"ALTER TABLE {table('contract_lane_rates')} ADD COLUMN IF NOT EXISTS origin_endpoint_type TEXT"
    yield f"ALTER TABLE {table('contract_lane_rates')} ADD COLUMN IF NOT EXISTS destination_endpoint_id TEXT"
    yield f"ALTER TABLE {table('contract_lane_rates')} ADD COLUMN IF NOT EXISTS destination_endpoint_type TEXT"
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("contract_fuel_rules")} (
            rule_id TEXT PRIMARY KEY,
            version_id TEXT NOT NULL REFERENCES {table("contract_versions")} (version_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            rate_pct DOUBLE PRECISION NOT NULL,
            basis TEXT NOT NULL,
            effective_start DATE,
            effective_end DATE
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("contract_accessorial_rules")} (
            rule_id TEXT PRIMARY KEY,
            version_id TEXT NOT NULL REFERENCES {table("contract_versions")} (version_id) ON DELETE CASCADE,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            charge_type TEXT NOT NULL,
            rate DOUBLE PRECISION NOT NULL,
            description TEXT NOT NULL,
            UNIQUE (version_id, code)
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("contract_volume_tiers")} (
            rule_id TEXT PRIMARY KEY,
            version_id TEXT NOT NULL REFERENCES {table("contract_versions")} (version_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            period TEXT NOT NULL,
            unit TEXT NOT NULL,
            min_volume DOUBLE PRECISION NOT NULL,
            max_volume DOUBLE PRECISION,
            discount_pct DOUBLE PRECISION NOT NULL DEFAULT 0
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("contract_capacity_commitments")} (
            rule_id TEXT PRIMARY KEY,
            version_id TEXT NOT NULL REFERENCES {table("contract_versions")} (version_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            period TEXT NOT NULL,
            unit TEXT NOT NULL,
            committed_quantity DOUBLE PRECISION NOT NULL,
            capacity_quantity DOUBLE PRECISION NOT NULL,
            current_utilization DOUBLE PRECISION NOT NULL DEFAULT 0,
            shortfall_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
            overage_rate DOUBLE PRECISION NOT NULL DEFAULT 0
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("rate_quotes")} (
            quote_id TEXT PRIMARY KEY,
            scenario_id TEXT,
            route_id TEXT,
            contract_id TEXT NOT NULL REFERENCES {table("carrier_contracts")} (contract_id),
            version_id TEXT NOT NULL REFERENCES {table("contract_versions")} (version_id),
            service_date DATE NOT NULL,
            rate_book_snapshot_id TEXT NOT NULL,
            request_payload JSONB NOT NULL,
            result_payload JSONB NOT NULL,
            total_cost DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("operating_parameters")} (
            parameter_set_id TEXT PRIMARY KEY,
            parameter_set_name TEXT NOT NULL,
            private_vehicle_limit INTEGER NOT NULL,
            max_route_minutes INTEGER NOT NULL,
            max_stops_per_route INTEGER NOT NULL,
            allow_overtime BOOLEAN NOT NULL DEFAULT TRUE,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""
        CREATE TABLE IF NOT EXISTS {table("revenue_parameters")} (
            product_family TEXT PRIMARY KEY,
            revenue_per_case DOUBLE PRECISION NOT NULL CHECK (revenue_per_case >= 0),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    yield f"""INSERT INTO {table("revenue_parameters")} (product_family, revenue_per_case)
        VALUES ('cartons', 6.25)
        ON CONFLICT (product_family) DO NOTHING
    """
    yield f"""INSERT INTO {table("carriers")} (carrier_id, carrier_name) VALUES
        ('GL_LOGISTICS', 'Great Lakes Logistics'),
        ('MIDWEST_EXPRESS', 'Midwest Express')
        ON CONFLICT (carrier_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("carrier_contracts")} (
        contract_id, carrier_id, contract_name, capacity_stops, rate_per_mile,
        rate_per_stop, minimum_charge, fuel_surcharge_pct, effective_start, effective_end
    ) VALUES
        ('GL_STANDARD_2026', 'GL_LOGISTICS', 'GL Standard 2026', 12, 4.25, 45, 350, 12, '2026-01-01', '2026-12-31'),
        ('GL_PRIORITY_2026', 'GL_LOGISTICS', 'GL Priority 2026', 20, 5.10, 55, 425, 10, '2026-01-01', '2026-12-31'),
        ('MW_SPOT_2026', 'MIDWEST_EXPRESS', 'Midwest Spot 2026', 8, 4.70, 50, 400, 14, '2026-01-01', '2026-12-31')
        ON CONFLICT (contract_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_versions")} (
        version_id, contract_id, version_number, status, currency, effective_start,
        effective_end, published_at, published_by
    )
        SELECT contract_id || '_V1', contract_id, 1, 'published', 'USD',
               effective_start, effective_end, COALESCE(effective_start, CURRENT_DATE),
               'Transportation Procurement'
        FROM {table("carrier_contracts")}
        ON CONFLICT (version_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_lane_rates")} (
        rule_id, version_id, lane_name, origin, destination, lane_type,
        origin_endpoint_id, origin_endpoint_type, destination_endpoint_id,
        destination_endpoint_type, priority, flat_rate,
        rate_per_mile, rate_per_stop, included_stops, minimum_charge, mileage_rounding
    )
        SELECT contract_id || '_LANE_NORTH', contract_id || '_V1',
               'North Depot → North Metro', 'DPT_NORTH', 'North Metro', 'MARKET',
               'DPT_NORTH', 'facility', 'MKT_NORTH', 'market', 200,
               GREATEST(50, minimum_charge * 0.22), rate_per_mile, rate_per_stop,
               1, minimum_charge, 'up_to_mile'
        FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_lane_rates")} (
        rule_id, version_id, lane_name, origin, destination, lane_type,
        origin_endpoint_id, origin_endpoint_type, destination_endpoint_id,
        destination_endpoint_type, priority, flat_rate,
        rate_per_mile, rate_per_stop, included_stops, minimum_charge, mileage_rounding
    )
        SELECT contract_id || '_LANE_REGIONAL', contract_id || '_V1',
               'Great Lakes regional fallback', '*', '*', NULL,
               NULL, NULL, NULL, NULL, 10,
               GREATEST(75, minimum_charge * 0.28), rate_per_mile * 1.05,
               rate_per_stop, 0, minimum_charge * 1.1, 'up_to_mile'
        FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""
        UPDATE {table("contract_lane_rates")}
        SET lane_type = 'MARKET',
            origin_endpoint_id = 'DPT_NORTH',
            origin_endpoint_type = 'facility',
            destination_endpoint_id = 'MKT_NORTH',
            destination_endpoint_type = 'market'
        WHERE rule_id LIKE '%_LANE_NORTH'
          AND origin = 'DPT_NORTH'
    """
    yield f"""INSERT INTO {table("contract_fuel_rules")} (
        rule_id, version_id, name, rate_pct, basis, effective_start, effective_end
    )
        SELECT contract_id || '_FUEL_1', contract_id || '_V1',
               'Published diesel surcharge', fuel_surcharge_pct,
               'linehaul_and_minimum', effective_start, effective_end
        FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_accessorial_rules")} (
        rule_id, version_id, code, name, charge_type, rate, description
    )
        SELECT contract_id || '_ACC_LIFTGATE', contract_id || '_V1', 'LIFTGATE',
               'Liftgate service', 'flat', 65,
               'Applied once when a route requires liftgate equipment.'
        FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_accessorial_rules")} (
        rule_id, version_id, code, name, charge_type, rate, description
    )
        SELECT contract_id || '_ACC_INSIDE', contract_id || '_V1', 'INSIDE_DELIVERY',
               'Inside delivery', 'per_stop', 32,
               'Applied for each stop requiring inside delivery.'
        FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_accessorial_rules")} (
        rule_id, version_id, code, name, charge_type, rate, description
    )
        SELECT contract_id || '_ACC_DETENTION', contract_id || '_V1', 'DETENTION',
               'Detention', 'per_hour', 85,
               'Applied to approved detention hours after free time.'
        FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_volume_tiers")} (
        rule_id, version_id, name, period, unit, min_volume, max_volume, discount_pct
    )
        SELECT contract_id || '_TIER_1', contract_id || '_V1', 'Base monthly tier',
               'month', 'stops', 0, 49, 0 FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_volume_tiers")} (
        rule_id, version_id, name, period, unit, min_volume, max_volume, discount_pct
    )
        SELECT contract_id || '_TIER_2', contract_id || '_V1', '50–99 monthly stops',
               'month', 'stops', 50, 99, 2 FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_volume_tiers")} (
        rule_id, version_id, name, period, unit, min_volume, max_volume, discount_pct
    )
        SELECT contract_id || '_TIER_3', contract_id || '_V1', '100+ monthly stops',
               'month', 'stops', 100, NULL, 4 FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("contract_capacity_commitments")} (
        rule_id, version_id, name, period, unit, committed_quantity,
        capacity_quantity, current_utilization, shortfall_rate, overage_rate
    )
        SELECT contract_id || '_COMMIT_1', contract_id || '_V1',
               'Monthly reserved stop capacity', 'month', 'stops',
               capacity_stops * 3, capacity_stops * 5, capacity_stops * 2, 12, 18
        FROM {table("carrier_contracts")}
        ON CONFLICT (rule_id) DO NOTHING
    """
    yield f"""INSERT INTO {table("operating_parameters")} (
        parameter_set_id, parameter_set_name, private_vehicle_limit,
        max_route_minutes, max_stops_per_route, allow_overtime
    ) VALUES ('default', 'Standard delivery operations', 4, 600, 8, TRUE)
        ON CONFLICT (parameter_set_id) DO NOTHING
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
            total_revenue DOUBLE PRECISION NOT NULL DEFAULT 0,
            profit DOUBLE PRECISION NOT NULL DEFAULT 0,
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
    yield f"ALTER TABLE {table('scenario_kpis')} ADD COLUMN IF NOT EXISTS total_revenue DOUBLE PRECISION NOT NULL DEFAULT 0"
    yield f"ALTER TABLE {table('scenario_kpis')} ADD COLUMN IF NOT EXISTS profit DOUBLE PRECISION NOT NULL DEFAULT 0"
    yield f"ALTER TABLE {table('solve_runs')} ADD COLUMN IF NOT EXISTS create_duration_ms INTEGER"
    yield f"ALTER TABLE {table('solve_runs')} ADD COLUMN IF NOT EXISTS worker_id TEXT"
    yield f"ALTER TABLE {table('solve_runs')} ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ"
    for table_name in ("depots", "customers", "fleet", "orders", "cost_parameters", "carriers", "carrier_contracts", "operating_parameters", "revenue_parameters"):
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
