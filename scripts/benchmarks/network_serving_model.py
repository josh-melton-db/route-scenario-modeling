"""Isolated benchmark adapter; production continues to solve inside the App."""
import hashlib
import json
import gzip
import base64
from time import perf_counter

import mlflow
import pandas as pd


class NetworkServingBenchmark(mlflow.pyfunc.PythonModel):
    def predict(self, context, model_input, params=None):
        from network_flow import solve_fixed_capacity_network

        outputs = []
        for payload in model_input["payload"]:
            started = perf_counter()
            request = json.loads(gzip.decompress(base64.b64decode(payload[5:])) if payload.startswith("gzip:") else payload)
            decoded = perf_counter()
            options = request["options"]
            for key in ("disabled_facility_ids", "disabled_lane_ids"):
                if key in options:
                    options[key] = set(options[key])
            for key in ("lane_unit_costs_by_date_lane", "tariff_per_case_by_date_lane"):
                if key in options:
                    options[key] = {(day, lane): amount for day, lane, amount in options[key]}
            result = solve_fixed_capacity_network(request["rows"], **options)
            solved = perf_counter()
            serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
            outputs.append({
                "decode_seconds": decoded - started,
                "solve_seconds": solved - decoded,
                "serialize_seconds": perf_counter() - solved,
                "result_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                "result_bytes": len(serialized.encode()),
                "result_json": base64.b64encode(gzip.compress(serialized.encode())).decode(),
            })
        return pd.DataFrame(outputs)


mlflow.models.set_model(NetworkServingBenchmark())
