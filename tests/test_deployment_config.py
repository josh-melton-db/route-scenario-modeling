import ast
import hashlib
import json
import runpy
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call

import pytest
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


def depot_auth_helper():
    notebook = ast.parse((ROOT / "notebooks/11_prepare_depot_routes.py").read_text())
    helper = next(node for node in notebook.body if isinstance(node, ast.FunctionDef)
                  and node.name == "get_app_credentials")
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(ROOT / "notebooks/11_prepare_depot_routes.py"), "exec"), namespace)
    return namespace["get_app_credentials"]


def test_depot_uc_credentials_take_precedence() -> None:
    secrets = Mock()
    secrets.get.side_effect = ["oauth-client", "oauth-secret"]
    credentials = depot_auth_helper()(secrets, " manufacturing.route_scenario_modeling ", "old-scope")
    assert credentials == {"client_id": "oauth-client", "client_secret": "oauth-secret"}
    assert secrets.get.call_args_list == [
        call(catalog="manufacturing", schema="route_scenario_modeling", key="depot_job_client_id"),
        call(catalog="manufacturing", schema="route_scenario_modeling", key="depot_job_client_secret"),
    ]


def test_depot_workspace_scope_credentials_are_unchanged() -> None:
    secrets = Mock()
    secrets.get.side_effect = ["oauth-client", "oauth-secret"]
    assert depot_auth_helper()(secrets, "", " old-scope ") == {
        "client_id": "oauth-client", "client_secret": "oauth-secret",
    }
    assert secrets.get.call_args_list == [
        call(scope="old-scope", key="client-id"),
        call(scope="old-scope", key="client-secret"),
    ]


def test_depot_no_credentials_selects_notebook_token() -> None:
    secrets = Mock()
    assert depot_auth_helper()(secrets, " ", " ") is None
    secrets.get.assert_not_called()


@pytest.mark.parametrize("uc_schema,scope", [
    ("manufacturing.route_scenario_modeling", "old-scope"),
    ("", "old-scope"),
    ("", ""),
])
def test_depot_notebook_uses_selected_authentication(monkeypatch, capsys, uc_schema: str, scope: str) -> None:
    import databricks.sdk
    import requests
    import route_opt.app_notebook_auth

    widgets = {
        "app_auth_uc_secret_schema": uc_schema,
        "app_auth_secret_scope": scope,
        "publish_daily_plans": "false",
        "service_date": "2026-10-06",
    }
    dbutils = MagicMock()
    dbutils.widgets.text.side_effect = lambda name, default: widgets.setdefault(name, default)
    dbutils.widgets.get.side_effect = widgets.__getitem__
    context = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    context.notebookPath().get.return_value = "/Workspace/example/notebooks/11_prepare_depot_routes"
    context.apiToken().get.return_value = "ephemeral-token"
    dbutils.secrets.get.side_effect = ["oauth-client", "oauth-secret"]
    workspace = Mock()
    workspace.config.host = "https://workspace.example"
    workspace.apps.get.return_value = SimpleNamespace(url="https://app.example", oauth2_app_client_id="app-client")
    oauth_client = Mock()
    client_factory = Mock(side_effect=[workspace, oauth_client])
    notebook_auth_factory = Mock()
    response = Mock(status_code=200, headers={"content-type": "application/json"})
    response.json.return_value = {"preparation_id": "test-preparation", "state": "completed"}
    request = Mock(return_value=response)
    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", client_factory)
    monkeypatch.setattr(route_opt.app_notebook_auth, "NotebookAppAuth", notebook_auth_factory)
    monkeypatch.setattr(requests, "request", request)
    monkeypatch.syspath_prepend(str(ROOT))
    runpy.run_path(str(ROOT / "notebooks/11_prepare_depot_routes.py"), init_globals={"dbutils": dbutils})
    captured = capsys.readouterr()
    assert "oauth-secret" not in captured.out + captured.err
    assert "oauth-client" not in captured.out + captured.err
    dbutils.widgets.text.assert_any_call("app_auth_uc_secret_schema", "")
    if uc_schema or scope:
        assert client_factory.call_args_list == [call(), call(
            host="https://workspace.example", auth_type="oauth-m2m",
            client_id="oauth-client", client_secret="oauth-secret",
        )]
        notebook_auth_factory.assert_not_called()
        oauth_client.config.authenticate.assert_called_once_with()
    else:
        client_factory.assert_called_once_with()
        dbutils.secrets.get.assert_not_called()
        assert notebook_auth_factory.call_args.args == (workspace, "app-client")
        assert notebook_auth_factory.call_args.kwargs["notebook_token"]() == "ephemeral-token"
        notebook_auth_factory.return_value.headers.assert_called_once_with()


@pytest.mark.parametrize("schema", ["manufacturing", ".schema", "catalog.", "catalog.schema.extra"])
def test_depot_rejects_malformed_uc_schema(schema: str) -> None:
    secrets = Mock()
    with pytest.raises(ValueError, match=r"catalog\.schema"):
        depot_auth_helper()(secrets, schema, "old-scope")
    secrets.get.assert_not_called()


@pytest.mark.parametrize("failed_key", ["depot_job_client_id", "depot_job_client_secret"])
@pytest.mark.parametrize("failure", ["missing", "unreadable", "empty", "unsupported"])
def test_depot_uc_errors_are_actionable_and_do_not_leak(failed_key: str, failure: str) -> None:
    def get_secret(**kwargs):
        if kwargs["key"] != failed_key:
            return "private-value"
        if failure == "empty":
            return ""
        if failure == "unsupported":
            raise TypeError("private-value: unexpected keyword argument 'catalog'")
        raise RuntimeError(f"private-value: {failure}")

    secrets = SimpleNamespace(get=get_secret)
    with pytest.raises(RuntimeError) as caught:
        depot_auth_helper()(secrets, "manufacturing.route_scenario_modeling", "old-scope")
    assert "private-value" not in str(caught.value)
    assert caught.value.__suppress_context__
    if failure == "unsupported":
        assert "serverless environment version 4" in str(caught.value)
        assert "17.3" in str(caught.value)
    else:
        assert failed_key in str(caught.value)
        assert "READ SECRET" in str(caught.value)


def test_depot_notebook_pins_uc_capable_environment_without_changing_dependencies() -> None:
    source = (ROOT / "notebooks/11_prepare_depot_routes.py").read_text()
    metadata = source.split("# /// script\n", 1)[1].split("# ///", 1)[0]
    environment = tomllib.loads("\n".join(line.removeprefix("# ") for line in metadata.splitlines()))
    assert environment == {"tool": {"databricks": {"environment": {"environment_version": "4"}}}}
    assert "# MAGIC %pip install faker==40.38.0" in source


def test_depot_uc_bundle_wiring_and_dev_render_compatibility(tmp_path: Path) -> None:
    output = render(ROOT / "configs/deployment/minimal.example.json", ROOT, tmp_path / "rendered")
    bundle = yaml.safe_load((output / "databricks.yml").read_text())
    assert bundle["variables"]["depot_routes_app_auth_uc_secret_schema"]["default"] == ""
    assert bundle["variables"]["depot_routes_app_auth_secret_scope"]["default"] == "route-scenario-modeling-depot-job"
    job_path = "resources/depot_routes.job.yml"
    job = yaml.safe_load((output / job_path).read_text())
    parameters = job["resources"]["jobs"]["depot_routes_morning"]["tasks"][0]["notebook_task"]["base_parameters"]
    assert parameters.pop("app_auth_uc_secret_schema") == "${var.depot_routes_app_auth_uc_secret_schema}"
    v010_job_sha256 = "ce3ab47eddea11fa14de2d7710cb38a991556f5e32522c9f1eba417fa4669beb"
    assert hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest() == v010_job_sha256
    bundle["variables"].pop("depot_routes_app_auth_uc_secret_schema")
    defaults = {key: bundle[key] for key in ("variables", "targets")}
    v010_defaults_sha256 = "c2176a5a9abafc3a7e7f96a176fc41d879cdf95512f1d37cf32a88906ac2fbd3"
    assert hashlib.sha256(json.dumps(defaults, sort_keys=True).encode()).hexdigest() == v010_defaults_sha256


def test_depot_uc_operator_variable_is_forwarded(tmp_path: Path) -> None:
    raw = json.loads((ROOT / "configs/deployment/minimal.example.json").read_text())
    raw["variables"]["depot_routes_app_auth_uc_secret_schema"] = "manufacturing.route_scenario_modeling"
    config_path = tmp_path / "uc.json"
    config_path.write_text(json.dumps(raw))
    config = DeploymentConfig.load(config_path)
    assert "depot_routes_app_auth_uc_secret_schema=manufacturing.route_scenario_modeling" in variable_args(config)
    output = render(config_path, ROOT, tmp_path / "rendered")
    assert json.loads((output / ".deployment-vars.json").read_text())["depot_routes_app_auth_uc_secret_schema"] == "manufacturing.route_scenario_modeling"


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
    assert bundle["variables"]["depot_routes_schedule_pause_status"]["default"] == "UNPAUSED"
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
    output = render(ROOT / "configs/deployment/enhanced.example.json", ROOT, tmp_path / "rendered")
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
    config = DeploymentConfig.load(ROOT / "configs/deployment/enhanced.example.json")
    assert config.routing["valhalla_strategy"] == "reuse"
    assert config.routing["valhalla_region"] == "texas"


def test_cli_variables_are_explicit() -> None:
    config = DeploymentConfig.load(ROOT / "configs/deployment/enhanced.example.json")
    args = variable_args(config)
    assert "catalog=my_catalog" in args
    assert "lakebase_database_owner_role_id=dbrx-apps-REPLACE_ME" in args


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
    output = render(ROOT / "configs/deployment/enhanced.example.json", ROOT, tmp_path / "rendered")
    config = DeploymentConfig.load(ROOT / "configs/deployment/enhanced.example.json")
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
    output = render(ROOT / "configs/deployment/enhanced.example.json", ROOT, tmp_path / "rendered")
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


def test_tags_apply_to_taggable_resources(tmp_path: Path) -> None:
    config_path = tmp_path / "tagged.json"
    raw = json.loads((ROOT / "configs/deployment/solver-provision.example.json").read_text())
    raw["tags"] = {"mfg_subindustry": "Logistics"}
    config_path.write_text(json.dumps(raw))
    output = render(config_path, ROOT, tmp_path / "rendered")
    bundle = yaml.safe_load((output / "databricks.yml").read_text())
    assert bundle["resources"]["sql_warehouses"]["sql_warehouse"]["tags"] == {
        "custom_tags": [{"key": "mfg_subindustry", "value": "Logistics"}]
    }
    lakebase = yaml.safe_load((output / "resources/lakebase.yml").read_text())["resources"]
    assert lakebase["postgres_projects"]["route_scenario_modeling_lakebase"]["custom_tags"] == [
        {"key": "mfg_subindustry", "value": "Logistics"}
    ]
    jobs = yaml.safe_load((output / "resources/jobs.yml").read_text())["resources"]["jobs"]
    assert jobs["route_scenario_modeling_plan"]["tags"] == {"mfg_subindustry": "Logistics"}
    pipelines = yaml.safe_load((output / "resources/pipelines.yml").read_text())["resources"]["pipelines"]
    assert pipelines["route_scenario_modeling_pipeline"]["tags"] == {"mfg_subindustry": "Logistics"}


def test_compute_tags_replace_ampersand(tmp_path: Path) -> None:
    config_path = tmp_path / "tagged.json"
    raw = json.loads((ROOT / "configs/deployment/minimal.example.json").read_text())
    raw["tags"] = {"mfg_outcome_usecase": "Distribution & Logistics Optimization"}
    config_path.write_text(json.dumps(raw))
    output = render(config_path, ROOT, tmp_path / "rendered")
    bundle = yaml.safe_load((output / "databricks.yml").read_text())
    assert bundle["resources"]["sql_warehouses"]["sql_warehouse"]["tags"]["custom_tags"][0]["value"] == (
        "Distribution and Logistics Optimization"
    )
    lakebase = yaml.safe_load((output / "resources/lakebase.yml").read_text())["resources"]
    assert lakebase["postgres_projects"]["route_scenario_modeling_lakebase"]["custom_tags"][0]["value"] == (
        "Distribution & Logistics Optimization"
    )
