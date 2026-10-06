import json
import subprocess
from pathlib import Path

import pytest

from valhalla_service.deploy_service import _run, build_plan, execute, main as deploy_main, wait_for_health
from valhalla_service.named_extract_setup import build_request, dispatch, main
from valhalla_service.smoke_coverage import _databricks_auth_headers, _requester_with_headers, main as smoke_main, smoke
from valhalla_service.volume_paths import volume_files_path


def test_named_extract_is_dry_run_by_default(capsys):
    assert main(["texas", "--coverage-id", "texas-delivery", "--artifact-version", "tx-1",
                 "--volume-path", "/Volumes/c/s/v", "--cluster-id", "cluster-1",
                 "--notebook-path", "/Workspace/build_valhalla"]) == 0
    output = capsys.readouterr().out
    assert '"REGION_ID": "texas"' in output
    assert '"REBUILD_ENGINE": "false"' in output
    assert '"COVERAGE_ID": "texas-delivery"' in output


def test_dispatch_requires_explicit_profile_and_accepts_explicit_default():
    request = build_request(extract="michigan", coverage_id="michigan", artifact_version="mi-1",
                            volume_path="/Volumes/c/s/v", cluster_id="c1",
                            notebook_path="/Workspace/build")
    with pytest.raises(ValueError, match="explicitly supplied"):
        dispatch(request, profile="  ")
    calls = []
    dispatch(request, profile="DEFAULT", runner=lambda *args, **kwargs: calls.append((args, kwargs)) or subprocess.CompletedProcess([], 0, "ok", ""))
    assert calls[0][0][0][0:5] == ["databricks", "jobs", "submit", "--profile", "DEFAULT"]


def test_smoke_requires_identity_and_bidirectional_reachability():
    def requester(url, payload):
        if url.endswith("/health"):
            return {"status": "ok", "region": {"coverage_id": "texas-delivery", "region": "texas", "artifact_version": "tx-1"}}
        return {"costing": "truck", "sources": payload["points"], "sources_to_targets": [
            [{"time": 0, "distance": 0}, {"time": 4, "distance": 0.2}],
            [{"time": 6, "distance": 0.3}, {"time": 0, "distance": 0}],
        ]}
    result = smoke("https://routing.test", coverage_id="texas-delivery", region_id="texas", artifact_version="tx-1",
                 points=[{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}], requester=requester)["result"] == "success"
    assert result

    with pytest.raises(RuntimeError, match="artifact mismatch"):
        smoke("https://routing.test", coverage_id="texas-delivery", region_id="texas", artifact_version="stale",
              points=[{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}], requester=requester)


def test_smoke_rejects_unreachable_reverse_cell():
    def requester(url, payload):
        if url.endswith("/health"):
            return {"status": "ok", "region": {"coverage_id": "texas-delivery", "region": "texas", "artifact_version": "tx-1"}}
        return {"costing": "truck", "sources": payload["points"], "sources_to_targets": [
            [{"time": 0, "distance": 0}, {"time": 4, "distance": 1}],
            [{"time": None, "distance": None}, {"time": 0, "distance": 0}],
        ]}
    with pytest.raises(RuntimeError, match="unreachable"):
        smoke("https://routing.test", coverage_id="texas-delivery", region_id="texas", artifact_version="tx-1",
              points=[{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}], requester=requester)


def test_smoke_rejects_error_cell_even_when_costs_are_present():
    def requester(url, payload):
        if url.endswith("/health"):
            return {"status": "ok", "region": {"coverage_id": "texas-delivery", "region": "texas", "artifact_version": "tx-1"}}
        return {"costing": "truck", "sources": payload["points"], "sources_to_targets": [
            [{"time": 0, "distance": 0}, {"time": 4, "distance": 1, "error_code": 442}],
            [{"time": 5, "distance": 1}, {"time": 0, "distance": 0}],
        ]}
    with pytest.raises(RuntimeError, match="unreachable"):
        smoke("https://routing.test", coverage_id="texas-delivery", region_id="texas", artifact_version="tx-1",
              points=[{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}], requester=requester)


def test_smoke_auth_uses_only_explicit_profile_and_returns_sdk_headers():
    calls = []

    class Config:
        def authenticate(self):
            return {"Authorization": "Bearer test-secret"}

    def factory(**kwargs):
        calls.append(kwargs)
        return Config()

    assert _databricks_auth_headers("DEFAULT", config_factory=factory) == {
        "Authorization": "Bearer test-secret"
    }
    assert calls == [{"profile": "DEFAULT"}]
    with pytest.raises(ValueError, match="explicitly supplied"):
        _databricks_auth_headers(" ", config_factory=factory)


def test_authenticated_requester_forwards_headers_without_printing(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "valhalla_service.smoke_coverage._request_json",
        lambda url, payload, *, headers: calls.append((url, payload, headers)) or {"ok": True},
    )
    requester = _requester_with_headers({"Authorization": "Bearer test-secret"})
    assert requester("https://app.test/health", None) == {"ok": True}
    assert calls == [("https://app.test/health", None, {"Authorization": "Bearer test-secret"})]
    assert "test-secret" not in capsys.readouterr().out


def test_smoke_cli_never_infers_authentication(capsys):
    with pytest.raises(SystemExit) as error:
        smoke_main(["missing.json", "coverage", "--point", "1,2", "--point", "3,4"])
    assert error.value.code == 2
    assert "--profile PROFILE | --unauthenticated" in capsys.readouterr().err


def test_deploy_plan_is_explicit_and_selects_region():
    plan = build_plan(
        app_name="valhalla-service",
        profile="DEFAULT",
        region="texas",
        volume="demos.route_scenario_modeling.valhalla_assets",
        workspace_path="/Workspace/Users/operator/valhalla-service",
    )
    assert plan.app_request["resources"][0]["uc_securable"] == {
        "permission": "READ_VOLUME",
        "securable_full_name": "demos.route_scenario_modeling.valhalla_assets",
        "securable_type": "VOLUME",
    }
    assert plan.app_request["compute_size"] == "MEDIUM"
    assert plan.update_request == {
        "update_mask": "compute_size,description,resources",
        "app": plan.app_request,
    }
    assert plan.app_yaml["env"][1] == {"name": "VALHALLA_REGION", "value": "texas"}
    assert all("--profile" in command and "DEFAULT" in command for command in plan.commands)
    update_command = plan.commands[2]
    assert update_command[0:5] == ("databricks", "apps", "create-update", "valhalla-service", "--profile")


def test_deploy_accepts_custom_manifest_region_and_rejects_unsafe_id():
    plan = build_plan(
        app_name="valhalla-service", profile="DEFAULT", region="south-central-v2",
        volume="c.s.v", workspace_path="/Workspace/Shared/valhalla-service",
    )
    assert plan.region == "south-central-v2"
    with pytest.raises(ValueError, match="region must contain only"):
        build_plan(
            app_name="valhalla-service", profile="DEFAULT", region="../unsafe",
            volume="c.s.v", workspace_path="/Workspace/Shared/valhalla-service",
        )


def test_existing_app_update_uses_nested_json_and_clean_stage():
    plan = build_plan(
        app_name="valhalla-service", profile="DEFAULT", region="texas",
        volume="demos.route_scenario_modeling.valhalla_assets",
        workspace_path="/Workspace/Shared/valhalla-service",
    )
    observed = {}

    get_calls = 0

    def runner(command, **kwargs):
        nonlocal get_calls
        if command[0:3] == ["databricks", "apps", "get"]:
            get_calls += 1
            body = "{}" if get_calls == 1 else '{"url":"https://valhalla.test"}'
            return subprocess.CompletedProcess(command, 0, body, "")
        if command[0:3] == ["databricks", "apps", "create-update"]:
            assert command[3:5] == ["valhalla-service", "--profile"]
            request_path = Path(next(item[1:] for item in command if item.startswith("@")))
            observed["update"] = json.loads(request_path.read_text(encoding="utf-8"))
        if command[0:2] == ["databricks", "sync"]:
            staged = Path(command[2])
            observed["staged_names"] = {path.name for path in staged.rglob("*")}
        return subprocess.CompletedProcess(command, 0, "", "")

    health_calls = []
    health = execute(
        plan, runner=runner,
        health_waiter=lambda url, **kwargs: health_calls.append((url, kwargs)) or {"status": "ok"},
    )
    assert observed["update"] == plan.update_request
    assert ".databricks" not in observed["staged_names"]
    assert ".DS_Store" not in observed["staged_names"]
    assert health == {"status": "ok"}
    assert health_calls == [("https://valhalla.test", {
        "profile": "DEFAULT", "expected_region": "texas", "timeout": 300,
    })]


def test_missing_app_create_uses_json_name_without_positional_name():
    plan = build_plan(
        app_name="valhalla-service", profile="DEFAULT", region="texas",
        volume="demos.route_scenario_modeling.valhalla_assets",
        workspace_path="/Workspace/Shared/valhalla-service",
    )
    observed = {}

    get_calls = 0

    def runner(command, **kwargs):
        nonlocal get_calls
        if command[0:3] == ["databricks", "apps", "get"]:
            get_calls += 1
            if get_calls == 1:
                return subprocess.CompletedProcess(command, 1, "", "RESOURCE_DOES_NOT_EXIST: app not found")
            return subprocess.CompletedProcess(command, 0, '{"url":"https://valhalla.test"}', "")
        if command[0:3] == ["databricks", "apps", "create"]:
            assert command[3] == "--profile"
            request_path = Path(next(item[1:] for item in command if item.startswith("@")))
            observed["create"] = json.loads(request_path.read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(command, 0, "", "")

    execute(plan, runner=runner, health_waiter=lambda *args, **kwargs: {"status": "ok"})
    assert observed["create"] == plan.app_request


def test_cli_failure_surfaces_diagnostics_and_redacts_credentials():
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 1, "", "create failed; Authorization: Bearer secret-value; client_secret=also-secret"
        )

    with pytest.raises(RuntimeError) as error:
        _run(["databricks", "apps", "create", "valhalla-service"], runner=runner)
    message = str(error.value)
    assert "create failed" in message
    assert "secret-value" not in message
    assert "also-secret" not in message
    assert message.count("<redacted>") == 2


def test_volume_resource_value_normalizes_to_files_api_path():
    expected = "/Volumes/demos/route_scenario_modeling/valhalla_assets"
    assert volume_files_path(expected + "/") == expected
    assert volume_files_path("demos.route_scenario_modeling.valhalla_assets") == expected


def test_health_wait_retries_startup_and_checks_region(monkeypatch):
    monkeypatch.setattr(
        "valhalla_service.deploy_service._databricks_auth_headers",
        lambda profile: {"Authorization": "Bearer test-secret"},
    )
    responses = [OSError("502 Bad Gateway"), {"status": "ok", "region": {"region": "michigan"}},
                 {"status": "ok", "region": {"region": "texas", "artifact_version": "tx-1"}}]
    calls = []
    clock = iter((0, 0, 1, 1, 2))

    def requester(url, payload, *, headers):
        calls.append((url, payload, headers))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    health = wait_for_health(
        "https://valhalla.test/", profile="DEFAULT", expected_region="texas", timeout=10,
        interval=1, requester=requester, sleeper=lambda _: None, monotonic=lambda: next(clock),
    )
    assert health["region"]["artifact_version"] == "tx-1"
    assert len(calls) == 3
    assert all(call[2] == {"Authorization": "Bearer test-secret"} for call in calls)


def test_deploy_cli_is_dry_run_and_requires_profile(capsys):
    assert deploy_main([
        "--profile", "DEFAULT", "--region", "texas",
        "--volume", "demos.route_scenario_modeling.valhalla_assets",
        "--workspace-path", "/Workspace/Users/operator/valhalla-service",
    ]) == 0
    output = capsys.readouterr().out
    assert '"VALHALLA_REGION"' in output
    assert "No remote resources were changed" in output

    with pytest.raises(SystemExit) as error:
        deploy_main(["--region", "texas", "--volume", "c.s.v"])
    assert error.value.code == 2
