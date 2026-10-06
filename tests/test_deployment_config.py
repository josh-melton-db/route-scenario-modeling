import json
import subprocess
from pathlib import Path

import yaml

from deployment.config import (
    DeploymentConfig,
    RENDER_MARKER,
    REQUIRED_SYNC_PATHS,
    render,
    variable_args,
    _bootstrap_required_data,
    _materialize_app_schema,
)


ROOT = Path(__file__).parents[1]


def test_minimal_render_excludes_optional_resources(tmp_path: Path) -> None:
    output = render(ROOT / "configs/deployment/minimal.example.json", ROOT, tmp_path / "rendered")
    bundle = yaml.safe_load((output / "databricks.yml").read_text())
    assert bundle["sync"]["include"] == REQUIRED_SYNC_PATHS
    assert (output / "backend/main.py").is_file()
    assert (output / "route_opt/__init__.py").is_file()
    assert (output / "requirements.txt").is_file()
    assert (output / "app.yaml").is_file()
    assert bundle["include"] == ["resources/lakebase.yml", "resources/network-bootstrap.yml", "resources/depot_routes.job.yml"]
    morning_job = yaml.safe_load((output / "resources/depot_routes.job.yml").read_text())["resources"]["jobs"]["depot_routes_morning"]
    assert morning_job["schedule"]["timezone_id"] == "America/Indiana/Indianapolis"
    assert morning_job["schedule"]["pause_status"] == "${var.depot_routes_schedule_pause_status}"
    assert bundle["variables"]["depot_routes_schedule_pause_status"]["default"] == "PAUSED"
    assert (output / "notebooks/11_prepare_depot_routes.py").is_file()
    app = bundle["resources"]["apps"]["route_scenario_modeling_app"]
    assert {resource["name"] for resource in app["resources"]} == {
        "lakebase", "sql_warehouse", "network_bootstrap_job"
    }
    assert app["resources"][-1]["job"]["permission"] == "CAN_MANAGE_RUN"
    env = {item["name"]: item for item in app["config"]["env"]}
    assert env["ROUTE_EXECUTION_MODE"]["value"] == "approximate_development"
    assert env["DATABRICKS_SCHEMA"]["value"] == "${resources.schemas.route_scenario_modeling_schema.name}"
    assert env["DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID"]["value_from"] == "network_bootstrap_job"


def test_enhanced_render_reuses_services_and_retains_jobs(tmp_path: Path) -> None:
    output = render(ROOT / "configs/deployment/dev-enhanced.json", ROOT, tmp_path / "rendered")
    bundle = yaml.safe_load((output / "databricks.yml").read_text())
    assert "resources/jobs.yml" in bundle["include"]
    assert "resources/pipelines.yml" in bundle["include"]
    app = bundle["resources"]["apps"]["route_scenario_modeling_app"]
    attached = {resource["name"]: resource for resource in app["resources"]}
    assert attached["route_solver"]["serving_endpoint"]["permission"] == "CAN_QUERY"
    assert attached["valhalla"]["app"]["permission"] == "CAN_USE"
    env = {item["name"]: item for item in app["config"]["env"]}
    assert env["ROUTE_EXECUTION_MODE"]["value"] == "serving_regional"
    assert env["DATABRICKS_ROUTE_SOLVER_ENDPOINT"]["value_from"] == "route_solver"
    config = DeploymentConfig.load(ROOT / "configs/deployment/dev-enhanced.json")
    assert config.routing["valhalla_strategy"] == "reuse"
    assert config.routing["valhalla_region"] == "texas"


def test_cli_variables_are_explicit() -> None:
    config = DeploymentConfig.load(ROOT / "configs/deployment/dev-enhanced.json")
    args = variable_args(config)
    assert "catalog=supplychain" in args
    assert "lakebase_database_owner_role_id=dbrx-apps-7bf07fff-a994-41fb-91b0-1c33ab04ac25" in args


def test_render_refuses_non_owned_nonempty_output(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "important.txt").write_text("keep")
    try:
        render(ROOT / "configs/deployment/minimal.example.json", ROOT, output)
    except ValueError as exc:
        assert "not owned" in str(exc)
    else:
        raise AssertionError("unsafe output was accepted")
    assert (output / "important.txt").read_text() == "keep"


def test_render_refuses_repo_and_unmanaged_repo_descendant(tmp_path: Path) -> None:
    for output in (ROOT, ROOT / "unsafe-render"):
        try:
            render(ROOT / "configs/deployment/minimal.example.json", ROOT, output)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe output was accepted: {output}")


def test_owned_output_can_be_re_rendered_and_excludes_secrets(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("databricks.yml", "app.yaml"):
        (repo / name).write_text((ROOT / name).read_text())
    shutil_resources = repo / "resources"
    shutil_resources.mkdir()
    (shutil_resources / "lakebase.yml").write_text((ROOT / "resources/lakebase.yml").read_text())
    (repo / ".env").write_text("TOKEN=secret")
    (repo / ".aws").mkdir()
    (repo / ".aws" / "credentials").write_text("secret")
    output = tmp_path / "rendered"
    render(ROOT / "configs/deployment/minimal.example.json", repo, output)
    assert (output / RENDER_MARKER).exists()
    assert not (output / ".env").exists()
    assert not (output / ".aws").exists()
    render(ROOT / "configs/deployment/minimal.example.json", repo, output)


def test_bootstrap_runs_job_then_grants_app_principal(tmp_path: Path, monkeypatch) -> None:
    output = render(ROOT / "configs/deployment/dev-enhanced.json", ROOT, tmp_path / "rendered")
    config = DeploymentConfig.load(ROOT / "configs/deployment/dev-enhanced.json")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        if command[1:3] == ["bundle", "summary"]:
            stdout = json.dumps({
                "resources": {"schemas": {"route_scenario_modeling_schema": {
                    "id": "supplychain.dev_josh_melton_route_scenario_modeling"
                }}}
            })
        elif command[1:3] == ["apps", "get"]:
            stdout = json.dumps({"service_principal_client_id": "app-principal"})
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    _bootstrap_required_data(
        config=config,
        output=output,
        profile="DEFAULT",
        target="dev",
        common=["--profile", "DEFAULT", "--target", "dev"],
    )
    assert commands[0][1:4] == ["bundle", "run", "network_bootstrap"]
    assert commands[1][1:3] == ["bundle", "summary"]
    assert commands[2][1:3] == ["apps", "get"]
    assert "app-principal" in commands[3]
    assert "supplychain.dev_josh_melton_route_scenario_modeling" in commands[3]


def test_materializes_resolved_schema_for_app_only(tmp_path: Path) -> None:
    output = render(ROOT / "configs/deployment/dev-enhanced.json", ROOT, tmp_path / "rendered")
    resolved = "dev_josh_melton_route_scenario_modeling"
    assert _materialize_app_schema(output, {
        "resources": {"schemas": {"route_scenario_modeling_schema": {"name": resolved}}}
    }) == resolved
    bundle = yaml.safe_load((output / "databricks.yml").read_text())
    env = {
        item["name"]: item for item in
        bundle["resources"]["apps"]["route_scenario_modeling_app"]["config"]["env"]
    }
    assert env["DATABRICKS_SCHEMA"]["value"] == resolved
    assert bundle["resources"]["schemas"]["route_scenario_modeling_schema"]["name"] == "${var.schema}"
    app_env = {item["name"]: item for item in yaml.safe_load((output / "app.yaml").read_text())["env"]}
    assert app_env["DATABRICKS_SCHEMA"]["value"] == resolved
