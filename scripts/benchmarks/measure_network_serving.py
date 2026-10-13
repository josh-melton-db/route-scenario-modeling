"""Compare exact in-process allocations with an isolated warm endpoint.

Usage: .venv/bin/python scripts/benchmarks/measure_network_serving.py
       --payload /private/tmp/network-benchmark-payload.json --profile DEFAULT
       --endpoint network-solver-benchmark-20261008 --output /private/tmp/measurements.json
The payload must contain rows and options, with dated costs encoded as triples.
"""
import argparse
import base64
import gzip
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from route_opt.network_flow import solve_fixed_capacity_network


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    from databricks.sdk import WorkspaceClient
    import requests

    workspace = WorkspaceClient(profile=args.profile)
    endpoint = workspace.serving_endpoints.get(args.endpoint)
    if endpoint.state.ready.value != "READY" or endpoint.state.config_update.value != "NOT_UPDATING":
        raise RuntimeError("Benchmark endpoint is not fully ready")
    if any(entity.scale_to_zero_enabled for entity in endpoint.config.served_entities):
        raise RuntimeError("Benchmark requires an always-warm endpoint")
    request_bytes = Path(args.payload).read_bytes()
    payload = json.loads(request_bytes)
    options = dict(payload["options"])
    for key in ("disabled_facility_ids", "disabled_lane_ids"):
        if key in options:
            options[key] = set(options[key])
    for key in ("lane_unit_costs_by_date_lane", "tariff_per_case_by_date_lane"):
        if key in options:
            options[key] = {(day, lane): amount for day, lane, amount in options[key]}
    measured = {"endpoint": args.endpoint, "request_raw_bytes": len(request_bytes), "local": [], "serving": []}
    for _ in range(args.repeats):
        started = perf_counter()
        result = solve_fixed_capacity_network(payload["rows"], **options)
        solved = perf_counter()
        serialized = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        measured["local"].append({"solve_seconds": solved-started, "serialize_seconds": perf_counter()-solved})
    measured["result_sha256"] = hashlib.sha256(serialized).hexdigest()
    started = perf_counter()
    encoded = "gzip:" + base64.b64encode(gzip.compress(request_bytes)).decode()
    measured["request_compress_seconds"] = perf_counter()-started
    body = json.dumps({"dataframe_records": [{"payload": encoded}]})
    measured["request_wire_bytes"] = len(body.encode())
    session = requests.Session()
    for index in range(args.repeats):
        headers = workspace.config.authenticate()
        headers["Content-Type"] = "application/json"
        started = perf_counter()
        response = session.post(f"{workspace.config.host}/serving-endpoints/{args.endpoint}/invocations", headers=headers, data=body, timeout=300)
        response.raise_for_status()
        elapsed = perf_counter()-started
        prediction = response.json()["predictions"][0]
        if prediction["result_sha256"] != measured["result_sha256"]:
            raise AssertionError("Serving allocation differs from identical local input")
        prediction.pop("result_json")
        prediction.update(request_seconds=elapsed, response_wire_bytes=len(response.content), sample=index)
        measured["serving"].append(prediction)
        Path(args.output).write_text(json.dumps(measured, indent=2))
        print(json.dumps(prediction), flush=True)
    Path(args.output).write_text(json.dumps(measured, indent=2))


if __name__ == "__main__":
    main()
