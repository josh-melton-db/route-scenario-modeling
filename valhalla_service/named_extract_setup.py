"""Plan or explicitly dispatch a named regional Valhalla build."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Callable, Sequence


EXTRACTS = {
    "michigan": "https://download.geofabrik.de/north-america/us/michigan-latest.osm.pbf",
    "texas": "https://download.geofabrik.de/north-america/us/texas-latest.osm.pbf",
}


def build_request(*, extract: str, coverage_id: str, artifact_version: str, volume_path: str, cluster_id: str, notebook_path: str,
                  rebuild_engine: bool = False) -> dict:
    if extract not in EXTRACTS:
        raise ValueError(f"unknown named extract {extract!r}; choose one of {', '.join(sorted(EXTRACTS))}")
    if not volume_path.startswith("/Volumes/"):
        raise ValueError("volume_path must be /Volumes/<catalog>/<schema>/<volume>")
    if not cluster_id.strip() or not notebook_path.startswith("/Workspace/"):
        raise ValueError("execution resources require a cluster ID and absolute /Workspace notebook path")
    if not coverage_id.strip() or not artifact_version.strip():
        raise ValueError("coverage_id and artifact_version must be explicit and non-empty")
    return {
        "run_name": f"valhalla-build-{extract}",
        "tasks": [{
            "task_key": "build_region",
            "existing_cluster_id": cluster_id,
            "notebook_task": {
                "notebook_path": notebook_path,
                "base_parameters": {
                    "VOLUME_PATH": volume_path,
                    "REGION_ID": extract,
                    "PBF_URL": EXTRACTS[extract],
                    "ARTIFACT_VERSION": artifact_version,
                    "COVERAGE_ID": coverage_id,
                    "REBUILD_ENGINE": str(rebuild_engine).lower(),
                },
            },
        }],
    }


def dispatch(request: dict, *, profile: str, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run):
    if not profile.strip():
        raise ValueError("live execution requires an explicitly supplied Databricks profile")
    return runner(
        ["databricks", "jobs", "submit", "--profile", profile, "--json", json.dumps(request)],
        check=True, text=True, capture_output=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extract", choices=sorted(EXTRACTS))
    parser.add_argument("--coverage-id", required=True)
    parser.add_argument("--artifact-version", required=True)
    parser.add_argument("--volume-path", required=True)
    parser.add_argument("--cluster-id", required=True)
    parser.add_argument("--notebook-path", required=True)
    parser.add_argument("--rebuild-engine", action="store_true")
    parser.add_argument("--execute", action="store_true", help="submit the planned run (default is dry-run)")
    parser.add_argument("--profile", help="required with --execute; never inferred (explicit DEFAULT is allowed)")
    args = parser.parse_args(argv)
    request = build_request(extract=args.extract, coverage_id=args.coverage_id,
                            artifact_version=args.artifact_version,
                            volume_path=args.volume_path, cluster_id=args.cluster_id,
                            notebook_path=args.notebook_path, rebuild_engine=args.rebuild_engine)
    print(json.dumps(request, indent=2, sort_keys=True))
    if not args.execute:
        return 0
    if not args.profile:
        parser.error("--execute requires an explicitly supplied --profile")
    result = dispatch(request, profile=args.profile)
    print(result.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
