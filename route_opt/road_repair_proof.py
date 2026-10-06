"""Nonsecret proof format for offline-validated UC road-coordinate repairs."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

PROOF_SCHEMA_VERSION = 1


def rows_hash(rows: Sequence[Mapping[str, object]]) -> str:
    ordered = sorted((dict(row) for row in rows), key=lambda row: str(row.get("customer_id", "")))
    payload = json.dumps(ordered, default=str, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def scoped_generated_customers(
    customers: Sequence[Mapping[str, object]], depot_ids: set[str]
) -> list[dict[str, object]]:
    return [
        dict(row) for row in customers
        if str(row.get("customer_id", "")).startswith("NET-CUST-")
        and str(row.get("depot_id", "")) in depot_ids
    ]


def build_repair_proof(
    *, source_customers: Sequence[Mapping[str, object]],
    repaired_customers: Sequence[Mapping[str, object]], depot_ids: set[str],
    coverage_id: str, artifact_version: str, costing: str = "truck",
) -> dict[str, object]:
    source = scoped_generated_customers(source_customers, depot_ids)
    repaired = scoped_generated_customers(repaired_customers, depot_ids)
    if {str(row["customer_id"]) for row in source} != {
        str(row["customer_id"]) for row in repaired
    }:
        raise ValueError("Repair proof source and repaired customer IDs differ.")
    invalid = [
        str(row["customer_id"]) for row in repaired
        if row.get("road_reachability_status") != "validated"
        or row.get("road_access_lat") in (None, "")
        or row.get("road_access_lng") in (None, "")
        or row.get("road_snap_distance_miles") in (None, "")
        or abs(float(row.get("lat", 999)) - float(row.get("road_access_lat", -999))) > 1e-6
        or abs(float(row.get("lng", 999)) - float(row.get("road_access_lng", -999))) > 1e-6
    ]
    if invalid:
        raise ValueError("Repair proof contains unvalidated customers: " + ", ".join(invalid[:10]))
    return {
        "schema_version": PROOF_SCHEMA_VERSION,
        "coverage_id": coverage_id,
        "artifact_version": artifact_version,
        "costing": costing,
        "depot_ids": sorted(depot_ids),
        "source_customer_hash": rows_hash(source),
        "repaired_customer_hash": rows_hash(repaired),
        "repaired_customers": repaired,
    }


def verify_repair_proof(
    proof: Mapping[str, object], *, current_customers: Sequence[Mapping[str, object]],
    coverage_id: str, artifact_version: str, depot_ids: set[str],
) -> list[dict[str, object]]:
    if proof.get("schema_version") != PROOF_SCHEMA_VERSION:
        raise ValueError("Unsupported road repair proof schema version.")
    if (
        proof.get("coverage_id") != coverage_id
        or proof.get("artifact_version") != artifact_version
        or proof.get("costing") != "truck"
        or set(map(str, proof.get("depot_ids", []))) != depot_ids
    ):
        raise ValueError("Road repair proof artifact identity or depot scope does not match.")
    current = scoped_generated_customers(current_customers, depot_ids)
    if proof.get("source_customer_hash") != rows_hash(current):
        raise ValueError("Road repair proof source customer hash does not match current UC data.")
    repaired_raw = proof.get("repaired_customers")
    if not isinstance(repaired_raw, list) or not all(isinstance(row, Mapping) for row in repaired_raw):
        raise ValueError("Road repair proof repaired_customers is malformed.")
    repaired = [dict(row) for row in repaired_raw]
    rebuilt = build_repair_proof(
        source_customers=current, repaired_customers=repaired, depot_ids=depot_ids,
        coverage_id=coverage_id, artifact_version=artifact_version,
    )
    if proof.get("repaired_customer_hash") != rebuilt["repaired_customer_hash"]:
        raise ValueError("Road repair proof repaired customer hash does not match payload.")
    return repaired
