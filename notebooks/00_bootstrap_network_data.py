# Databricks notebook source
import json
import sys
from pathlib import PurePosixPath

dbutils.widgets.text("catalog", "demos")
dbutils.widgets.text("schema", "route_scenario_modeling")
dbutils.widgets.dropdown("repair_reachability", "false", ["false", "true"])
dbutils.widgets.text("valhalla_url", "")
dbutils.widgets.text("coverage_id", "")
dbutils.widgets.text("artifact_version", "")
dbutils.widgets.text("coverage_manifest", "")
dbutils.widgets.text("coverage_depot_ids", "")
dbutils.widgets.text("repair_validation_path", "")
dbutils.widgets.text("max_adjustment_miles", "5.0")
dbutils.widgets.text("max_snap_distance_miles", "0.25")
notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
root = str(PurePosixPath(notebook_path).parent.parent)
if not root.startswith("/Workspace/"):
    root = "/Workspace" + root
sys.path.insert(0, root)

from route_opt.network_bootstrap import (
    bootstrap_network_tables, publish_network_customer_repair_proof,
    repair_existing_network_customer_table,
)
from route_opt.network_synthetic import national_dataset_cached

if dbutils.widgets.get("repair_reachability").lower() == "true":
    valhalla_url = dbutils.widgets.get("valhalla_url").strip()
    coverage_id = dbutils.widgets.get("coverage_id").strip()
    artifact_version = dbutils.widgets.get("artifact_version").strip()
    manifest_path = dbutils.widgets.get("coverage_manifest").strip()
    configured_depots = {
        value.strip()
        for value in dbutils.widgets.get("coverage_depot_ids").replace(";", ",").split(",")
        if value.strip()
    }
    if manifest_path:
        if not manifest_path.startswith("/Workspace/"):
            manifest_path = str(PurePosixPath(root) / manifest_path)
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        matches = [
            item for item in manifest.get("coverages", [])
            if item.get("coverage_id") == coverage_id
        ]
        if len(matches) != 1:
            raise ValueError(
                f"coverage_manifest must contain exactly one {coverage_id!r} entry"
            )
        manifest_depots = {str(value) for value in matches[0].get("depot_ids", [])}
        if configured_depots and configured_depots != manifest_depots:
            raise ValueError("coverage_depot_ids do not match the selected manifest entry")
        configured_depots = manifest_depots
    proof_path = dbutils.widgets.get("repair_validation_path").strip()
    if not all((coverage_id, artifact_version)) or (not proof_path and not valhalla_url):
        raise ValueError(
            "repair_reachability requires coverage_id, artifact_version, and either "
            "repair_validation_path or valhalla_url"
        )
    if proof_path:
        if not proof_path.startswith("/Workspace/"):
            raise ValueError("repair_validation_path must be an absolute /Workspace path")
        with open(proof_path, encoding="utf-8") as handle:
            proof = json.load(handle)
        result = publish_network_customer_repair_proof(
            spark, catalog=dbutils.widgets.get("catalog"), schema=dbutils.widgets.get("schema"),
            proof=proof, coverage_id=coverage_id, artifact_version=artifact_version,
            coverage_depot_ids=configured_depots,
        )
    else:
        from databricks.sdk.core import Config
        from route_opt.valhalla_reachability import BootstrapValhallaClient
        client = BootstrapValhallaClient(
            valhalla_url, auth_headers=Config().authenticate,
            max_snap_distance_miles=float(dbutils.widgets.get("max_snap_distance_miles")),
        )
        result = repair_existing_network_customer_table(
            spark, catalog=dbutils.widgets.get("catalog"), schema=dbutils.widgets.get("schema"),
            validator=client.inspect_bidirectional_reachability,
            provenance={"costing": "truck", "coverage_id": coverage_id, "artifact_version": artifact_version},
            max_adjustment_miles=float(dbutils.widgets.get("max_adjustment_miles")),
            coverage_depot_ids=configured_depots,
        )
    dbutils.notebook.exit(json.dumps(result))

result = bootstrap_network_tables(
    spark,
    national_dataset_cached(),
    catalog=dbutils.widgets.get("catalog"),
    schema=dbutils.widgets.get("schema"),
)
dbutils.notebook.exit(json.dumps(result))
