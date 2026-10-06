"""Create the network demo snapshot without replacing existing route data."""
import math
from copy import deepcopy
from collections.abc import Mapping
from .network_synthetic import assert_valid_network_dataset
from .network_synthetic import repair_generated_customer_reachability
from .network_synthetic import _road_distance_miles, _transit_minutes
from .schemas import NETWORK_TABLES
from .spark_io import _normalize_rows
from .road_repair_proof import verify_repair_proof


def repair_existing_network_customer_table(
    spark,
    *,
    catalog: str,
    schema: str,
    validator,
    provenance: Mapping[str, object],
    max_adjustment_miles: float = 5.0,
    coverage_depot_ids: set[str],
) -> dict[str, object]:
    """Replace generated UC access coordinates and dependent delivery-lane metrics."""
    def quoted(value: str) -> str:
        if not value:
            raise ValueError("Catalog and schema must be nonempty")
        return "`" + value.replace("`", "``") + "`"

    prefix = ".".join(quoted(part) for part in (catalog, schema))
    customer_table = f"{prefix}.{quoted('dim_network_customers')}"
    facility_table = f"{prefix}.{quoted('dim_facilities')}"
    lane_table = f"{prefix}.{quoted('dim_network_lanes')}"
    for full_name in (customer_table, facility_table, lane_table):
        if not spark.catalog.tableExists(full_name):
            raise ValueError(f"Reachability repair requires existing table {full_name}.")
    customers = [row.asDict(recursive=True) for row in spark.table(customer_table).collect()]
    facilities = [row.asDict(recursive=True) for row in spark.table(facility_table).collect()]
    lanes = [row.asDict(recursive=True) for row in spark.table(lane_table).collect()]
    if not coverage_depot_ids:
        raise ValueError("Reachability repair requires at least one coverage depot ID.")
    known_depots = {str(row["facility_id"]) for row in facilities}
    unknown_depots = sorted(coverage_depot_ids - known_depots)
    if unknown_depots:
        raise ValueError(
            "Reachability repair coverage contains unknown depot IDs: "
            + ", ".join(unknown_depots)
        )
    repaired = repair_generated_customer_reachability(
        customers, facilities, validator=validator, provenance=provenance,
        max_adjustment_miles=max_adjustment_miles,
        depot_ids=coverage_depot_ids,
    )
    unresolved = sorted(
        str(row["customer_id"]) for row in repaired
        if str(row.get("customer_id", "")).startswith("NET-CUST-")
        and str(row.get("depot_id", "")) in coverage_depot_ids
        and row.get("road_reachability_status") != "validated"
    )
    if unresolved:
        sample = ", ".join(unresolved[:10])
        raise RuntimeError(
            f"Reachability repair aborted before publish: {len(unresolved)} generated "
            f"customers remain unresolved ({sample})."
        )
    customers_by_id = {str(row["customer_id"]): row for row in repaired}
    facilities_by_id = {str(row["facility_id"]): row for row in facilities}
    affected_lanes = 0
    for lane in lanes:
        if str(lane.get("lane_type")) != "DELIVERY":
            continue
        customer = customers_by_id.get(str(lane.get("destination_endpoint_id")))
        origin = facilities_by_id.get(str(lane.get("origin_endpoint_id")))
        if (
            customer is None or origin is None
            or not str(customer.get("customer_id", "")).startswith("NET-CUST-")
            or str(customer.get("depot_id", "")) not in coverage_depot_ids
        ):
            continue
        distance = _road_distance_miles(
            float(origin["lat"]), float(origin["lng"]),
            float(customer["lat"]), float(customer["lng"]),
        )
        lane["distance_miles"] = distance
        lane["transit_minutes"] = _transit_minutes(distance)
        affected_lanes += 1
    customer_view = "_network_reachable_customers_revision"
    lane_view = "_network_reachable_lanes_revision"
    spark.createDataFrame(_normalize_rows(repaired)).createOrReplaceTempView(customer_view)
    spark.createDataFrame(_normalize_rows(lanes)).createOrReplaceTempView(lane_view)
    # All network calls and validation finish before either accepted table is replaced.
    # Re-running is deterministic from road_original_* if a table replacement is interrupted.
    spark.sql(
        f"CREATE OR REPLACE TABLE {customer_table} USING DELTA AS "
        f"SELECT * FROM {quoted(customer_view)}"
    )
    spark.sql(
        f"CREATE OR REPLACE TABLE {lane_table} USING DELTA AS "
        f"SELECT * FROM {quoted(lane_view)}"
    )
    adjusted = sum(
        str(row.get("depot_id", "")) in coverage_depot_ids
        and float(row.get("road_adjustment_miles") or 0) > 0
        for row in repaired
    )
    return {
        "repaired_table": customer_table,
        "customer_count": len(repaired),
        "validated_generated_customers": sum(
            str(row.get("customer_id", "")).startswith("NET-CUST-")
            and str(row.get("depot_id", "")) in coverage_depot_ids
            for row in repaired
        ),
        "adjusted_generated_customers": adjusted,
        "refreshed_delivery_lanes": affected_lanes,
        "costing": provenance.get("costing"),
        "coverage_id": provenance.get("coverage_id"),
        "artifact_version": provenance.get("artifact_version"),
        "coverage_depot_ids": sorted(coverage_depot_ids),
    }


def publish_network_customer_repair_proof(
    spark, *, catalog: str, schema: str, proof: Mapping[str, object],
    coverage_id: str, artifact_version: str, coverage_depot_ids: set[str],
) -> dict[str, object]:
    """Verify an offline validation proof against current UC, then publish its rows."""
    def quoted(value: str) -> str:
        if not value:
            raise ValueError("Catalog and schema must be nonempty")
        return "`" + value.replace("`", "``") + "`"

    prefix = ".".join(quoted(part) for part in (catalog, schema))
    customer_table = f"{prefix}.{quoted('dim_network_customers')}"
    facility_table = f"{prefix}.{quoted('dim_facilities')}"
    lane_table = f"{prefix}.{quoted('dim_network_lanes')}"
    for full_name in (customer_table, facility_table, lane_table):
        if not spark.catalog.tableExists(full_name):
            raise ValueError(f"Reachability repair requires existing table {full_name}.")
    customers = [row.asDict(recursive=True) for row in spark.table(customer_table).collect()]
    facilities = [row.asDict(recursive=True) for row in spark.table(facility_table).collect()]
    lanes = [row.asDict(recursive=True) for row in spark.table(lane_table).collect()]
    repaired_scope = verify_repair_proof(
        proof, current_customers=customers, coverage_id=coverage_id,
        artifact_version=artifact_version, depot_ids=coverage_depot_ids,
    )
    repaired_by_id = {str(row["customer_id"]): row for row in repaired_scope}
    revised_customers = [
        dict(repaired_by_id.get(str(row.get("customer_id")), row)) for row in customers
    ]
    facilities_by_id = {str(row["facility_id"]): row for row in facilities}
    refreshed_lanes = 0
    for lane in lanes:
        customer = repaired_by_id.get(str(lane.get("destination_endpoint_id")))
        origin = facilities_by_id.get(str(lane.get("origin_endpoint_id")))
        if str(lane.get("lane_type")) != "DELIVERY" or customer is None or origin is None:
            continue
        distance = _road_distance_miles(
            float(origin["lat"]), float(origin["lng"]),
            float(customer["lat"]), float(customer["lng"]),
        )
        lane["distance_miles"] = distance
        lane["transit_minutes"] = _transit_minutes(distance)
        refreshed_lanes += 1
    customer_view = "_network_proven_customer_revision"
    lane_view = "_network_proven_lane_revision"
    spark.createDataFrame(_normalize_rows(revised_customers)).createOrReplaceTempView(customer_view)
    spark.createDataFrame(_normalize_rows(lanes)).createOrReplaceTempView(lane_view)
    spark.sql(f"CREATE OR REPLACE TABLE {customer_table} USING DELTA AS SELECT * FROM {quoted(customer_view)}")
    spark.sql(f"CREATE OR REPLACE TABLE {lane_table} USING DELTA AS SELECT * FROM {quoted(lane_view)}")
    return {
        "repaired_table": customer_table,
        "validated_generated_customers": len(repaired_scope),
        "refreshed_delivery_lanes": refreshed_lanes,
        "coverage_id": coverage_id,
        "artifact_version": artifact_version,
        "coverage_depot_ids": sorted(coverage_depot_ids),
        "source_customer_hash": proof["source_customer_hash"],
        "repaired_customer_hash": proof["repaired_customer_hash"],
    }


def prepare_reachable_network_revision(
    dataset,
    *,
    validator,
    provenance: Mapping[str, object],
    max_adjustment_miles: float = 5.0,
):
    """Build a detached publishable revision; accepted source tables remain immutable."""
    revised = deepcopy(dataset)
    revised["dim_network_customers"] = repair_generated_customer_reachability(
        revised["dim_network_customers"],
        revised["dim_facilities"],
        validator=validator,
        provenance=provenance,
        max_adjustment_miles=max_adjustment_miles,
    )
    assert_valid_network_dataset(revised)
    return revised


def bootstrap_network_tables(spark, dataset, *, catalog: str, schema: str) -> dict:
    if set(dataset) != set(NETWORK_TABLES):
        raise ValueError("Bootstrap accepts only the complete network table set")
    assert_valid_network_dataset(dataset)

    def quoted(value):
        if not value:
            raise ValueError("Catalog and schema must be nonempty")
        return "`" + value.replace("`", "``") + "`"

    names = {
        name: ".".join(quoted(part) for part in (catalog, schema, name))
        for name in NETWORK_TABLES
    }
    existing = [name for name, full_name in names.items() if spark.catalog.tableExists(full_name)]
    missing = [name for name in names if name not in existing]
    additive_supply_migration = missing == ["facility_supply_daily"]
    if existing and missing and not additive_supply_migration:
        raise ValueError(
            "Partial network snapshot already exists; no tables were written. "
            "Reconcile the existing snapshot before bootstrapping: " + ", ".join(existing)
        )
    if not missing:
        return {"created": [], "existing": existing}
    counts = {}
    create_names = missing if additive_supply_migration else list(names)
    for name in create_names:
        full_name = names[name]
        rows = dataset[name]
        if additive_supply_migration and name == "facility_supply_daily":
            facilities = {
                str(row["facility_id"]): row
                for row in (
                    record.asDict(recursive=True)
                    for record in spark.table(names["dim_facilities"]).collect()
                )
            }
            rows = [
                {
                    "capacity_plan_version_id": row["capacity_plan_version_id"],
                    "service_date": row["service_date"],
                    "facility_id": row["facility_id"],
                    "supply_units": int(math.ceil(int(row["capacity_units"]) * 1.20)),
                }
                for row in (
                    record.asDict(recursive=True)
                    for record in spark.table(names["facility_capacity_daily"]).collect()
                )
                if facilities.get(str(row["facility_id"]), {}).get("facility_type")
                == "distribution_center"
            ]
        print(f"Creating {full_name}: {len(rows)} rows", flush=True)
        view = "_network_bootstrap_" + name
        spark.createDataFrame(_normalize_rows(rows)).createOrReplaceTempView(view)
        # CTAS fails if the table exists and is supported by serverless Spark.
        spark.sql(f"CREATE TABLE {full_name} USING DELTA AS SELECT * FROM {quoted(view)}")
        counts[name] = spark.table(full_name).count()
        if counts[name] != len(rows):
            raise RuntimeError(f"Published row count mismatch for {full_name}")
    return {"created": create_names, "existing": existing, "row_counts": counts}
