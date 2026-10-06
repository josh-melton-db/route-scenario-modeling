"""Plan or execute a repeatable regional Databricks App deployment."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from valhalla_service.smoke_coverage import _databricks_auth_headers, _request_json

@dataclass(frozen=True)
class DeploymentPlan:
    app_name: str
    profile: str
    region: str
    volume: str
    workspace_path: str
    compute_size: str
    app_request: dict
    update_request: dict
    app_yaml: dict
    commands: tuple[tuple[str, ...], ...]


def _identifier(value: str, *, label: str) -> str:
    value = value.strip()
    if not value or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in value):
        raise ValueError(f"{label} must contain only lowercase letters, digits, hyphens, or underscores")
    return value


def build_plan(*, app_name: str, profile: str, region: str, volume: str, workspace_path: str,
               compute_size: str = "MEDIUM") -> DeploymentPlan:
    app_name = _identifier(app_name, label="app_name")
    if len(app_name) > 30:
        raise ValueError("app_name must be at most 30 characters")
    profile = profile.strip()
    if not profile:
        raise ValueError("profile must be explicitly supplied")
    region = _identifier(region, label="region")
    volume_parts = volume.strip().split(".")
    if len(volume_parts) != 3 or any(not part for part in volume_parts):
        raise ValueError("volume must be a catalog.schema.volume full name")
    workspace_path = workspace_path.rstrip("/")
    if not workspace_path.startswith("/Workspace/"):
        raise ValueError("workspace_path must be an absolute /Workspace path")
    compute_size = compute_size.upper()
    if compute_size not in {"MEDIUM", "LARGE"}:
        raise ValueError("compute_size must be MEDIUM or LARGE")

    app_request = {
        "name": app_name,
        "description": f"Regional Valhalla matrix service ({region})",
        "compute_size": compute_size,
        "resources": [{
            "name": "valhalla-assets",
            "uc_securable": {
                "permission": "READ_VOLUME",
                "securable_full_name": volume,
                "securable_type": "VOLUME",
            },
        }],
    }
    app_yaml = {
        "command": ["bash", "start.sh"],
        "env": [
            {"name": "VALHALLA_VOLUME_PATH", "valueFrom": "valhalla-assets"},
            {"name": "VALHALLA_REGION", "value": region},
        ],
    }
    update_request = {
        "update_mask": "compute_size,description,resources",
        "app": app_request,
    }
    commands = (
        ("databricks", "apps", "get", app_name, "--profile", profile, "-o", "json"),
        ("databricks", "apps", "create", "--profile", profile, "--json", "<app-request.json>"),
        ("databricks", "apps", "create-update", app_name, "--profile", profile,
         "--json", "<app-update-request.json>"),
        ("databricks", "apps", "start", app_name, "--profile", profile),
        ("databricks", "sync", "<staged-service>", workspace_path, "--full", "--profile", profile),
        ("databricks", "apps", "deploy", app_name, "--source-code-path", workspace_path,
         "--mode", "SNAPSHOT", "--profile", profile),
    )
    return DeploymentPlan(
        app_name, profile, region, volume, workspace_path, compute_size,
        app_request, update_request, app_yaml, commands,
    )


def _sanitize_cli_output(value: str | None) -> str:
    """Retain useful CLI diagnostics while masking common credential forms."""
    output = value or ""
    output = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1<redacted>", output)
    output = re.sub(
        r"(?i)((?:access[_-]?token|client[_-]?secret|databricks_token)\s*[:=]\s*)[^\s,}\]]+",
        r"\1<redacted>",
        output,
    )
    return output.strip()


def _failure(command: Sequence[str], result: subprocess.CompletedProcess) -> RuntimeError:
    rendered = " ".join(command[:4])
    stderr = _sanitize_cli_output(result.stderr)
    stdout = _sanitize_cli_output(result.stdout)
    details = stderr or stdout or "Databricks CLI returned no diagnostic output"
    return RuntimeError(f"{rendered} failed with exit code {result.returncode}: {details}")


def _run(command: Sequence[str], *, runner: Callable[..., subprocess.CompletedProcess]) -> subprocess.CompletedProcess:
    result = runner(list(command), check=False, text=True, capture_output=True)
    if result.returncode != 0:
        raise _failure(command, result)
    return result


def _app_is_absent(result: subprocess.CompletedProcess) -> bool:
    diagnostic = f"{result.stderr or ''}\n{result.stdout or ''}".lower()
    return any(marker in diagnostic for marker in (
        "resource_does_not_exist", "does not exist", "not found", "cannot find app",
    ))


def wait_for_health(endpoint_url: str, *, profile: str, expected_region: str, timeout: float = 300,
                    interval: float = 5, requester: Callable[..., dict] = _request_json,
                    sleeper: Callable[[float], None] = time.sleep,
                    monotonic: Callable[[], float] = time.monotonic) -> dict:
    """Wait for bootstrap and verify active region without exposing OAuth headers."""
    if timeout <= 0 or interval <= 0:
        raise ValueError("health timeout and interval must be positive")
    headers = _databricks_auth_headers(profile)
    health_url = f"{endpoint_url.rstrip('/')}/health"
    deadline = monotonic() + timeout
    last_error = "health endpoint did not respond"
    while True:
        try:
            health = requester(health_url, None, headers=headers)
            active = health.get("region", {})
            observed_region = active.get("region") if isinstance(active, dict) else None
            if health.get("status") == "ok" and observed_region == expected_region:
                return health
            last_error = (
                f"health returned status={health.get('status')!r}, region={observed_region!r}; "
                f"expected region={expected_region!r}"
            )
        except Exception as exc:
            last_error = _sanitize_cli_output(str(exc)) or type(exc).__name__
        if monotonic() >= deadline:
            raise TimeoutError(
                f"Valhalla health did not become ready within {timeout:g}s: {last_error}"
            )
        sleeper(min(interval, max(0, deadline - monotonic())))


def execute(plan: DeploymentPlan, *, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
            health_timeout: float = 300,
            health_waiter: Callable[..., dict] = wait_for_health) -> dict:
    service_root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="valhalla-service-") as temporary:
        staging = Path(temporary) / "service"
        shutil.copytree(
            service_root,
            staging,
            ignore=shutil.ignore_patterns(
                ".git", ".databricks", ".DS_Store", "deploy", "__pycache__", ".pytest_cache"
            ),
        )
        (staging / "app.yaml").write_text(_yaml(plan.app_yaml), encoding="utf-8")
        request_path = Path(temporary) / "app-request.json"
        request_path.write_text(json.dumps(plan.app_request), encoding="utf-8")
        update_request_path = Path(temporary) / "app-update-request.json"
        update_request_path.write_text(json.dumps(plan.update_request), encoding="utf-8")

        get = runner(
            ["databricks", "apps", "get", plan.app_name, "--profile", plan.profile, "-o", "json"],
            check=False, text=True, capture_output=True,
        )
        if get.returncode != 0 and not _app_is_absent(get):
            raise _failure(["databricks", "apps", "get", plan.app_name], get)
        request_arg = f"@{request_path}"
        if get.returncode == 0:
            _run([
                "databricks", "apps", "create-update", plan.app_name, "--profile", plan.profile,
                "--json", f"@{update_request_path}",
            ], runner=runner)
        else:
            _run([
                "databricks", "apps", "create", "--profile", plan.profile,
                "--json", request_arg,
            ], runner=runner)
        _run(["databricks", "apps", "start", plan.app_name, "--profile", plan.profile], runner=runner)
        _run(["databricks", "sync", str(staging), plan.workspace_path, "--full", "--profile", plan.profile], runner=runner)
        _run([
            "databricks", "apps", "deploy", plan.app_name, "--source-code-path", plan.workspace_path,
            "--mode", "SNAPSHOT", "--profile", plan.profile,
        ], runner=runner)
        deployed = _run(
            ["databricks", "apps", "get", plan.app_name, "--profile", plan.profile, "-o", "json"],
            runner=runner,
        )
        try:
            endpoint_url = json.loads(deployed.stdout)["url"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError("Databricks app status did not return a deployment URL") from exc
        return health_waiter(
            endpoint_url, profile=plan.profile, expected_region=plan.region, timeout=health_timeout,
        )


def _yaml(document: dict) -> str:
    lines = ["command:"]
    lines.extend(f"  - {item}" for item in document["command"])
    lines.append("env:")
    for item in document["env"]:
        lines.append(f"  - name: {item['name']}")
        key = "valueFrom" if "valueFrom" in item else "value"
        lines.append(f"    {key}: {item[key]}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-name", default="valhalla-service")
    parser.add_argument("--profile", required=True, help="explicit Databricks CLI profile; DEFAULT is allowed")
    parser.add_argument(
        "--region", required=True,
        help="safe region ID already present in the Volume manifest (for example texas)",
    )
    parser.add_argument("--volume", required=True, help="catalog.schema.volume containing existing artifacts")
    parser.add_argument("--workspace-path", default="/Workspace/Shared/valhalla-service")
    parser.add_argument("--compute-size", choices=("MEDIUM", "LARGE"), default="MEDIUM")
    parser.add_argument(
        "--health-timeout", type=float, default=300,
        help="seconds to wait for authenticated /health after deployment (default: 300)",
    )
    parser.add_argument("--execute", action="store_true", help="create/update, sync, and deploy (default is dry-run)")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(app_name=args.app_name, profile=args.profile, region=args.region,
                          volume=args.volume, workspace_path=args.workspace_path, compute_size=args.compute_size)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({
        "app": plan.app_request,
        "app_update": plan.update_request,
        "runtime": plan.app_yaml,
        "commands": [list(command) for command in plan.commands],
    }, indent=2, sort_keys=True))
    if not args.execute:
        print("Dry run only. No remote resources were changed; add --execute after reviewing this plan.")
        return 0
    try:
        health = execute(plan, health_timeout=args.health_timeout)
    except (RuntimeError, TimeoutError, ValueError) as exc:
        parser.exit(1, f"deployment failed: {exc}\n")
    print(json.dumps({"deployment_health": health}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
