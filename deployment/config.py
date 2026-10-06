from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


MODES = {"approximate_development", "local_road", "strict_serving_road", "serving_regional"}
REQUIRED_SYNC_PATHS = [
    "app.yaml",
    "requirements.txt",
    "dist/**",
    "backend/**",
    "route_opt/**",
    "notebooks/**",
    "pipelines/**",
    "routing_coverage/**",
]
RENDER_MARKER = ".route-scenario-deployment-render.json"
SENSITIVE_NAMES = {
    ".agents",
    ".aws",
    ".codex",
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
}


@dataclass(frozen=True)
class DeploymentConfig:
    name: str
    preset: str
    variables: dict[str, str]
    routing: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "DeploymentConfig":
        raw = json.loads(path.read_text())
        required = {"name", "preset", "variables", "routing"}
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(f"missing configuration keys: {', '.join(missing)}")
        if raw["preset"] not in {"minimal", "enhanced"}:
            raise ValueError("preset must be minimal or enhanced")
        routing = dict(raw["routing"])
        valhalla = routing.get("valhalla")
        if valhalla is not None:
            if not isinstance(valhalla, dict):
                raise ValueError("routing.valhalla must be an object")
            strategy = valhalla.get("strategy", "reuse")
            if strategy not in {"reuse", "deploy"}:
                raise ValueError("routing.valhalla.strategy must be reuse or deploy")
            routing["valhalla_strategy"] = strategy
            routing["valhalla_app"] = valhalla.get("app")
            routing["coverage_manifest"] = valhalla.get("coverage_manifest")
            routing["valhalla_region"] = valhalla.get("region")
            routing["valhalla_volume"] = valhalla.get("volume")
            routing["coverage_id"] = valhalla.get("coverage_id")
            routing["smoke_points"] = valhalla.get("smoke_points", [])
            routing["validate_valhalla"] = bool(valhalla.get("validate_on_deploy", False))
            if strategy == "deploy":
                for key in ("app", "region", "volume", "coverage_manifest", "coverage_id"):
                    if not valhalla.get(key):
                        raise ValueError(f"routing.valhalla.{key} is required for strategy=deploy")
                if len(routing["smoke_points"]) != 2:
                    raise ValueError("routing.valhalla.smoke_points must contain exactly two LAT,LON points")
        mode = routing.get("mode")
        if mode not in MODES:
            raise ValueError(f"routing.mode must be one of {sorted(MODES)}")
        for key in ("catalog", "lakebase_database_owner_role_id"):
            if not str(raw["variables"].get(key, "")).strip():
                raise ValueError(f"variables.{key} is required")
        if mode in {"strict_serving_road", "serving_regional"}:
            if not routing.get("solver_endpoint"):
                raise ValueError(f"routing.solver_endpoint is required for {mode}")
        if mode in {"local_road", "strict_serving_road", "serving_regional"}:
            if not routing.get("coverage_manifest"):
                raise ValueError(f"routing.coverage_manifest is required for {mode}")
            if not routing.get("valhalla_app"):
                raise ValueError(f"routing.valhalla_app is required for {mode}")
        return cls(raw["name"], raw["preset"], raw["variables"], routing)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _prepare_output(repo: Path, output: Path, managed_root: Path) -> None:
    repo = repo.resolve()
    output = output.resolve()
    managed_root = managed_root.resolve()
    if output == repo or _is_relative_to(repo, output):
        raise ValueError("output must not be the repository or one of its ancestors")
    if _is_relative_to(output, repo) and not _is_relative_to(output, managed_root):
        raise ValueError("custom output inside the repository is forbidden; use the managed render directory")
    if output.is_symlink():
        raise ValueError("output must not be a symbolic link")
    if not output.exists():
        return
    if not output.is_dir():
        raise ValueError("output exists and is not a directory")
    marker = output / RENDER_MARKER
    if marker.is_file():
        metadata = json.loads(marker.read_text())
        if metadata.get("tool") != "route-scenario-modeling/deploy-demo" or metadata.get("repo") != str(repo):
            raise ValueError("output marker is not owned by this repository")
        shutil.rmtree(output)
        return
    if any(output.iterdir()):
        raise ValueError("existing output is non-empty and is not owned by deploy-demo")
    output.rmdir()


def _copy_checkout(repo: Path, output: Path) -> None:
    ignored = shutil.ignore_patterns(
        ".git",
        ".databricks",
        ".venv",
        "node_modules",
        ".pytest_cache",
        "test-results",
        *sorted(SENSITIVE_NAMES),
        ".env.*",
    )
    shutil.copytree(repo, output, ignore=ignored)
    (output / RENDER_MARKER).write_text(
        json.dumps({"tool": "route-scenario-modeling/deploy-demo", "repo": str(repo.resolve())}) + "\n"
    )
    # Preserve declared sync-exclude anchors so strict bundle validation does
    # not turn their intentional absence in the staging tree into warnings.
    for excluded in ("node_modules", ".pytest_cache"):
        directory = output / excluded
        directory.mkdir()
        (directory / ".deployment-placeholder").touch()


def render(config_path: Path, repo: Path, output: Path) -> Path:
    config = DeploymentConfig.load(config_path)
    managed_root = repo / ".databricks" / "deployment-render"
    _prepare_output(repo, output, managed_root)
    _copy_checkout(repo, output)
    bundle_path = output / "databricks.yml"
    bundle = yaml.safe_load(bundle_path.read_text())
    # The managed staging directory is intentionally ignored by the parent Git
    # checkout. Explicit includes prevent bundle sync from treating the staged
    # runtime as ignored and deleting the deployed App source.
    bundle.setdefault("sync", {})["include"] = list(REQUIRED_SYNC_PATHS)
    # Canonical network tables are required by the App, so their idempotent
    # bootstrap job belongs to both presets.
    bundle["include"] = ["resources/lakebase.yml", "resources/network-bootstrap.yml", "resources/depot_routes.job.yml"]
    if config.preset == "enhanced":
        bundle["include"] += [
            "resources/jobs.yml",
            "resources/pipelines.yml",
        ]

    app = bundle["resources"]["apps"]["route_scenario_modeling_app"]
    env = app["config"]["env"]
    env_by_name = {item["name"]: item for item in env}
    env_by_name["ROUTE_EXECUTION_MODE"]["value"] = config.routing["mode"]
    env_by_name["VALHALLA_ALLOW_HAVERSINE_FALLBACK"]["value"] = str(
        bool(config.routing.get("allow_haversine_fallback", False))
    ).lower()

    resources = app["resources"]
    resources.append({
        "name": "network_bootstrap_job",
        "job": {"id": "${resources.jobs.network_bootstrap.id}", "permission": "CAN_MANAGE_RUN"},
    })
    env.append({"name": "DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID", "value_from": "network_bootstrap_job"})
    endpoint = config.routing.get("solver_endpoint")
    if endpoint:
        resources.append({
            "name": "route_solver",
            "serving_endpoint": {"name": endpoint, "permission": "CAN_QUERY"},
        })
        env.append({"name": "DATABRICKS_ROUTE_SOLVER_ENDPOINT", "value_from": "route_solver"})
    valhalla = config.routing.get("valhalla_app")
    if valhalla:
        resources.append({
            "name": "valhalla",
            "app": {"name": valhalla, "permission": "CAN_USE"},
        })
        env.append({"name": "VALHALLA_APP_URL", "value_from": "valhalla"})
        env.append({"name": "VALHALLA_COSTING", "value": config.routing.get("costing", "truck")})
        env.append({
            "name": "VALHALLA_MAX_SNAP_DISTANCE_MILES",
            "value": str(config.routing.get("max_snap_distance_miles", 0.25)),
        })
    manifest = config.routing.get("coverage_manifest")
    if manifest:
        env.append({"name": "ROUTING_COVERAGE_MANIFEST", "value": manifest})

    # Values remain CLI variables, making the rendered bundle safe to inspect.
    bundle_path.write_text(yaml.safe_dump(bundle, sort_keys=False))
    app_config = json.loads(json.dumps(app["config"]))
    for item in app_config["env"]:
        if "value_from" in item:
            item["valueFrom"] = item.pop("value_from")
    (output / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False))
    (output / ".deployment-vars.json").write_text(json.dumps(config.variables, indent=2, sort_keys=True) + "\n")
    return output


def variable_args(config: DeploymentConfig) -> list[str]:
    return [arg for key, value in sorted(config.variables.items()) for arg in ("--var", f"{key}={value}")]


def _materialize_app_schema(output: Path, validated_bundle: dict[str, Any]) -> str:
    schema_name = str(
        validated_bundle.get("resources", {})
        .get("schemas", {})
        .get("route_scenario_modeling_schema", {})
        .get("name", "")
    ).strip()
    if not schema_name or schema_name.startswith("${"):
        raise RuntimeError("bundle validation did not resolve the deployed schema resource name")

    bundle_path = output / "databricks.yml"
    bundle = yaml.safe_load(bundle_path.read_text())
    app = bundle["resources"]["apps"]["route_scenario_modeling_app"]
    for item in app["config"]["env"]:
        if item["name"] == "DATABRICKS_SCHEMA":
            item["value"] = schema_name
            break
    else:
        raise RuntimeError("rendered App config is missing DATABRICKS_SCHEMA")
    bundle_path.write_text(yaml.safe_dump(bundle, sort_keys=False))

    app_path = output / "app.yaml"
    app_config = yaml.safe_load(app_path.read_text())
    for item in app_config["env"]:
        if item["name"] == "DATABRICKS_SCHEMA":
            item["value"] = schema_name
            break
    else:
        raise RuntimeError("rendered app.yaml is missing DATABRICKS_SCHEMA")
    app_path.write_text(yaml.safe_dump(app_config, sort_keys=False))
    return schema_name


def _resolved_variable(bundle: dict[str, Any], config: DeploymentConfig, target: str, name: str) -> str:
    if name in config.variables:
        return str(config.variables[name])
    target_value = bundle.get("targets", {}).get(target, {}).get("variables", {}).get(name)
    if target_value is not None:
        return str(target_value)
    default = bundle.get("variables", {}).get(name, {}).get("default")
    if default is None:
        raise ValueError(f"unable to resolve bundle variable {name!r} for target {target!r}")
    return str(default)


def _bootstrap_required_data(
    *, config: DeploymentConfig, output: Path, profile: str, target: str, common: list[str]
) -> None:
    subprocess.run(
        ["databricks", "bundle", "run", "network_bootstrap", *common],
        cwd=output,
        check=True,
    )
    bundle = yaml.safe_load((output / "databricks.yml").read_text())
    summary_result = subprocess.run(
        ["databricks", "bundle", "summary", *common, "-o", "json"],
        cwd=output,
        check=True,
        capture_output=True,
        text=True,
    )
    schema_resource = (
        json.loads(summary_result.stdout)
        .get("resources", {})
        .get("schemas", {})
        .get("route_scenario_modeling_schema", {})
    )
    deployed_schema = str(schema_resource.get("id", "")).strip()
    if not deployed_schema:
        raise RuntimeError("bundle summary did not report the deployed route_scenario_modeling schema id")
    app_name = _resolved_variable(bundle, config, target, "app_name")
    app_result = subprocess.run(
        ["databricks", "apps", "get", app_name, "--profile", profile, "-o", "json"],
        cwd=output,
        check=True,
        capture_output=True,
        text=True,
    )
    principal = str(json.loads(app_result.stdout).get("service_principal_client_id", "")).strip()
    if not principal:
        raise RuntimeError(f"Databricks App {app_name!r} did not report a service principal client ID")
    subprocess.run(
        [
            sys.executable,
            str(output / "scripts" / "grant-network-schema"),
            "--profile", profile,
            "--principal", principal,
            "--schema", deployed_schema,
        ],
        cwd=output,
        check=True,
    )


def _prepare_valhalla(config: DeploymentConfig, output: Path, profile: str) -> None:
    strategy = config.routing.get("valhalla_strategy", "reuse")
    validate = bool(config.routing.get("validate_valhalla")) or strategy == "deploy"
    if strategy == "deploy":
        service = output / "valhalla_service" / "deploy_service.py"
        if not service.is_file():
            raise RuntimeError(
                "routing.valhalla.strategy=deploy requires the independent valhalla_service checkout"
            )
        base = [
            sys.executable,
            str(output / "scripts" / "deploy-valhalla-service"),
            "--profile", profile,
            "--app-name", str(config.routing["valhalla_app"]),
            "--region", str(config.routing["valhalla_region"]),
            "--volume", str(config.routing["valhalla_volume"]),
        ]
        # Preserve the service tool's plan-first contract in the combined flow.
        subprocess.run(base, cwd=output, check=True)
        subprocess.run([*base, "--execute"], cwd=output, check=True)
    if validate:
        manifest = output / str(config.routing["coverage_manifest"])
        command = [
            sys.executable,
            str(output / "scripts" / "check-valhalla-coverage"),
            str(manifest),
            str(config.routing["coverage_id"]),
            "--profile", profile,
        ]
        for point in config.routing.get("smoke_points", []):
            command.extend(("--point", str(point)))
        subprocess.run(command, cwd=output, check=True)
def main() -> int:
    parser = argparse.ArgumentParser(description="Render, validate, and deploy a configured demo bundle")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--dry-run", action="store_true", help="render only; do not contact Databricks")
    parser.add_argument(
        "--provision-solver",
        action="store_true",
        help="after deploying an enhanced bootstrap config, run the planning job and verify its new endpoint",
    )
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="validate the rendered config, then run canonical bootstrap and repair the App schema grant",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    config = DeploymentConfig.load(args.config.resolve())
    output = (args.output or repo / ".databricks" / "deployment-render" / config.name).resolve()
    render(args.config.resolve(), repo, output)
    print(f"Rendered {config.preset} deployment to {output}")
    if args.dry_run:
        if args.provision_solver:
            print(f"Would provision solver endpoint {config.variables.get('route_solver_endpoint_name', '<missing>')}")
        return 0
    if args.bootstrap_only and args.provision_solver:
        raise ValueError("--bootstrap-only and --provision-solver cannot be combined")

    if args.provision_solver:
        if config.preset != "enhanced":
            raise ValueError("--provision-solver requires preset=enhanced so the planning job is present")
        if config.routing["mode"] != "approximate_development" or config.routing.get("solver_endpoint"):
            raise ValueError(
                "--provision-solver requires an approximate bootstrap config without routing.solver_endpoint"
            )
        if not config.variables.get("route_solver_endpoint_name"):
            raise ValueError("--provision-solver requires variables.route_solver_endpoint_name")

    common = ["--profile", args.profile, "--target", args.target, *variable_args(config)]
    validation = subprocess.run(
        ["databricks", "bundle", "validate", "--strict", "-o", "json", *common],
        cwd=output,
        check=True,
        capture_output=True,
        text=True,
    )
    schema_name = _materialize_app_schema(output, json.loads(validation.stdout))
    print(f"Resolved App Unity Catalog schema: {schema_name}")
    subprocess.run(["databricks", "bundle", "validate", "--strict", *common], cwd=output, check=True)
    if not args.bootstrap_only:
        _prepare_valhalla(config, output, args.profile)
        subprocess.run(["databricks", "apps", "deploy", "--auto-approve", *common], cwd=output, check=True)
    _bootstrap_required_data(
        config=config, output=output, profile=args.profile, target=args.target, common=common
    )
    if args.bootstrap_only:
        print("Canonical network bootstrap and App schema grant completed")
        return 0
    if args.provision_solver:
        endpoint = config.variables["route_solver_endpoint_name"]
        subprocess.run(
            ["databricks", "bundle", "run", "route_scenario_modeling_plan", *common],
            cwd=output,
            check=True,
        )
        result = subprocess.run(
            ["databricks", "serving-endpoints", "get", endpoint, "--profile", args.profile, "-o", "json"],
            cwd=output,
            check=True,
            capture_output=True,
            text=True,
        )
        state = json.loads(result.stdout).get("state", {})
        if state.get("ready") != "READY" or state.get("config_update") != "NOT_UPDATING":
            raise RuntimeError(f"solver endpoint {endpoint!r} is not fully ready: {state}")
        print(f"Solver endpoint {endpoint} is READY/NOT_UPDATING; deploy a serving config to attach it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
