"""Package the existing deterministic solver into an isolated test endpoint.

No production endpoint or App configuration is changed. The caller must remove
the temporary endpoint after measuring; scale-to-zero is deliberately disabled.
"""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--experiment", required=True)
    args = parser.parse_args()
    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput
    import mlflow
    from mlflow.models import ModelSignature
    from mlflow.types import ColSpec, Schema

    workspace = WorkspaceClient(profile=args.profile)
    workspace.workspace.mkdirs(str(Path(args.experiment).parent))
    mlflow.set_tracking_uri(f"databricks://{args.profile}")
    mlflow.set_registry_uri(f"databricks-uc://{args.profile}")
    mlflow.set_experiment(args.experiment)
    signature = ModelSignature(
        inputs=Schema([ColSpec("string", "payload")]),
        outputs=Schema([ColSpec("double", "decode_seconds"), ColSpec("double", "solve_seconds"),
                        ColSpec("double", "serialize_seconds"), ColSpec("string", "result_sha256"),
                        ColSpec("long", "result_bytes"), ColSpec("string", "result_json")]),
    )
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as temporary:
        solver = Path(temporary) / "network_flow.py"
        shutil.copy(root / "route_opt/network_flow.py", solver)
        with mlflow.start_run(run_name="isolated-network-solver-serving-benchmark"):
            info = mlflow.pyfunc.log_model(
                name="network_solver_benchmark", python_model=str(Path(__file__).with_name("network_serving_model.py")),
                code_paths=[str(solver)], signature=signature,
                pip_requirements=["mlflow==3.16.0", "ortools==9.8.3296", "pandas==2.2.3", "numpy<2"],
                registered_model_name=args.model,
            )
    workspace.serving_endpoints.create(
        name=args.endpoint,
        config=EndpointCoreConfigInput(name=args.endpoint, served_entities=[ServedEntityInput(
            entity_name=args.model, entity_version=str(info.registered_model_version),
            workload_size="Small", scale_to_zero_enabled=False,
        )]),
    )
    print(json.dumps({"endpoint": args.endpoint, "version": info.registered_model_version}))


if __name__ == "__main__":
    main()
