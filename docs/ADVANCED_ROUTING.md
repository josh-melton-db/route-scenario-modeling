# Advanced routing

The golden path uses `approximate_development`: local OR-Tools with an approximate travel matrix. It has no routing service or serving endpoint dependency.

Add road routing and managed solving when the use case needs them.

## Execution modes

| Mode | Matrix | Solver | Intended use |
|---|---|---|---|
| `approximate_development` | Approximate distance/time | Local OR-Tools | Local development, workshops, functional demos |
| `local_road` | Valhalla directed road matrix | Local OR-Tools | Road-aware testing with local solve compute |
| `strict_serving_road` | Valhalla directed road matrix | Model Serving | Managed interactive road solves |
| `serving_regional` | Valhalla inside validated regions; approximate fallback elsewhere | Model Serving | Regional road service with an explicit matrix fallback |

Strict mode is strict: missing coverage, unreachable matrix cells, unsupported inputs, or an unavailable serving endpoint return an explicit error. It never falls back to Haversine or a local solver. Approximate routing must be selected as its own labeled mode.

`serving_regional` always uses Model Serving for the solve. It uses Valhalla where
the validated coverage manifest applies and may use the labeled approximate
matrix outside that coverage when `allow_haversine_fallback` is true.

Configure these dependencies through a deployment JSON file, not by editing
`app.yaml`. The enhanced example is `configs/deployment/dev-enhanced.json`:

```json
{
  "preset": "enhanced",
  "routing": {
    "mode": "serving_regional",
    "solver_endpoint": "route-solver-dev",
    "valhalla": {
      "strategy": "reuse",
      "app": "valhalla-service",
      "region": "texas",
      "volume": "demos.route_scenario_modeling.valhalla_assets",
      "coverage_manifest": "routing_coverage/texas-service.v1.json",
      "coverage_id": "texas-delivery",
      "smoke_points": ["32.7767,-96.7970", "29.7604,-95.3698"]
    },
    "allow_haversine_fallback": true
  }
}
```

The renderer attaches the existing endpoint with `CAN_QUERY` and the managed
Valhalla App with `CAN_USE`; Databricks grants those permissions to the route
App service principal during deployment. The referenced coverage manifest must
exist in the source tree and must already have passed its smoke validation.

## Valhalla

Valhalla remains independently deployable, but its service source is vendored in
this repository under `valhalla_service/`. The parent repository provides stable
wrappers for its operator tooling:

- `scripts/setup-valhalla-extract` plans or submits a repeatable named-region build;
- `scripts/deploy-valhalla-service` plans or executes deployment of an existing
  regional artifact.

Clean clones include the deployable service source and require no second clone.
The former nested Git metadata is preserved only as local migration evidence
under ignored `.databricks/valhalla-service-git-history`; it is not required at
runtime or distributed. Road tiles and engine binaries are not committed; they
remain versioned artifacts in the configured Unity Catalog Volume.

The expected service contract is:

- `GET /health` reports coverage region, artifact identity, and readiness;
- `POST /matrix` accepts ordered coordinates with truck costing and returns a directed `sources_to_targets` matrix containing seconds and kilometers.

Provision Valhalla through the vendored `valhalla_service/` source and its independent deployment lifecycle. Build an extract large enough for the full delivery territory and likely detours. Multiple depots may share a regional service when the coverage artifact includes all of them.

Plan first, then explicitly execute:

```bash
scripts/setup-valhalla-extract texas --coverage-id texas-delivery \
  --artifact-version texas-YYYYMMDD-N --volume-path /Volumes/CATALOG/SCHEMA/VOLUME \
  --cluster-id <cluster-id> --notebook-path <workspace-notebook>

scripts/deploy-valhalla-service --profile <profile> --region texas \
  --volume <catalog.schema.volume>
scripts/deploy-valhalla-service --profile <profile> --region texas \
  --volume <catalog.schema.volume> --execute
```

Add `--execute --profile <profile>` to the extract setup command only after
reviewing its generated Jobs request. Consult `valhalla_service/README.md` for
region-refresh and engine-rebuild options.

The route deployment JSON can orchestrate this sequence. Use
`routing.valhalla.strategy: reuse` to attach an already healthy service without
redeploying it. Use `strategy: deploy` to make `scripts/deploy-demo` emit the
service plan, deploy the selected `region` from `volume`, run the two configured
smoke points, stamp the staged coverage manifest, and only then deploy the route
App. `validate_on_deploy: true` applies the smoke/stamp step to `reuse` as well.

Before enabling a road mode:

1. Copy `routing_coverage_samples/texas-candidates.v1.json` to an operator-owned deployment file.
2. Replace candidate metadata with the deployed endpoint, region, artifact, and build identity.
3. Grant the Databricks App service principal `CAN_USE` on each managed Valhalla App.
4. Inspect the smoke command's required arguments, then run it with an explicit profile:

   ```bash
   scripts/check-valhalla-coverage --help
   scripts/check-valhalla-coverage --profile <profile> <required-arguments>
   ```

5. Confirm the check validates artifact identity, snapping, and every directed matrix cell.
6. Set `ROUTING_COVERAGE_MANIFEST` and select `local_road` or `strict_serving_road`.

Bounds alone do not prove that points are routable. The application validates the returned directed matrix and rejects missing, unreachable, or misaligned cells.

### Repair generated customer road access

After deploying a Valhalla service that returns snapped `sources` and `targets`, repair an
existing UC network snapshot explicitly. Validation runs locally with the operator's
Databricks profile because a serverless bootstrap notebook cannot use an interactive App
login. It uploads a nonsecret proof to Workspace Files; it does not modify UC tables.

```bash
scripts/repair-demo-road-data \
  --config <deployment-config.json> \
  --profile <profile> \
  --workspace-path /Workspace/Users/<operator>/route-road-repair/<proof>.json \
  --output <local-proof.json>
```

The command reads complete typed SQL snapshots, validates only generated customers assigned
to the manifest's validated depot IDs, and requires bounded truck reachability in both
directions. Excessive customer snapping triggers bounded regeneration; excessive depot
snapping, malformed responses, service failures, or unresolved candidates abort. Each
accepted row stores its original coordinate, generated road candidate, snapped access
coordinate, snap distance, coverage ID, and artifact version. The final customer coordinate
is the revalidated access coordinate.

Publish the proof only through the staged bundle whose synced source includes
`route_opt/road_repair_proof.py`, `route_opt/network_bootstrap.py`,
`notebooks/00_bootstrap_network_data.py`, and `resources/network-bootstrap.yml`:

```bash
databricks bundle run network_bootstrap \
  --profile <profile> \
  --target <target> \
  <resolved staged --var arguments> \
  --notebook-params \
repair_reachability=true,\
coverage_id=<coverage-id>,\
artifact_version=<artifact-version>,\
coverage_manifest=<manifest-path>,\
repair_validation_path=/Workspace/Users/<operator>/route-road-repair/<proof>.json
```

Use the rendered staging directory and its resolved schema variables for this run. The
publisher checks proof schema and artifact identity, exact depot scope, the current scoped
UC source hash, repaired payload hash, validated access coordinates, and customer IDs before
writing. Changes outside the covered generated-customer scope do not invalidate the proof;
any covered-row change does. A successful publication replaces the customer dimension and
refreshes only affected delivery-lane distances and transit times. No App credential or
token is passed to the notebook.

## Model Serving

Model Serving is optional because the same OR-Tools solver can run locally. Use it when you need managed interactive compute, independent scaling, or a stable remote solve interface.

Deploy or select a route solver endpoint, grant the App service principal `CAN_QUERY`, set `DATABRICKS_ROUTE_SOLVER_ENDPOINT`, and select `strict_serving_road`.

To reuse an endpoint, set `routing.solver_endpoint` to its name. The renderer
attaches it; it never recreates or updates that endpoint.

To provision a new endpoint, copy
`configs/deployment/solver-provision.example.json`. This is an enhanced bundle
with approximate App routing, so the planning job exists without requiring the
not-yet-created endpoint. Set `variables.route_solver_endpoint_name`, deploy it,
and run the existing provisioning job:

```bash
scripts/deploy-demo --config <solver-provision.json> \
  --profile <profile> --target <target> --dry-run --provision-solver
scripts/deploy-demo --config <solver-provision.json> \
  --profile <profile> --target <target> --provision-solver
```

The job registers `${catalog}.${schema}.route_solver` through
`notebooks/06a_register_solver_model.py` and creates or updates the named
endpoint through `notebooks/06b_deploy_serving_endpoint.py`. Wait for `READY` and
`NOT_UPDATING`; the command verifies both states. Then put that same name in `routing.solver_endpoint`, select a
serving execution mode, and redeploy. This provision path also runs the complete
planning job, including data and pipeline tasks, so use it only when those
effects are intended.

Discover exact CLI syntax before endpoint operations:

```bash
databricks serving-endpoints -h
databricks serving-endpoints get <endpoint-name> --profile <profile>
```

An endpoint is fully ready when `state.ready` is `READY` and `state.config_update` is `NOT_UPDATING`. Inspect its OpenAPI schema before changing request or response adapters:

```bash
databricks serving-endpoints get-open-api <endpoint-name> --profile <profile>
```

## Provenance and failure behavior

Every persisted route result should identify:

- execution mode and solver;
- matrix provider and coverage artifact;
- fleet and cost source;
- supported constraints applied or rejected;
- immutable parent network run and service date.

Do not silently substitute a synthetic fleet, approximate matrix, or local solver when a strict dependency fails. Select `approximate_development` explicitly when approximation is acceptable.

## Production operations

Keep Valhalla and Model Serving health visible on the App readiness page. Alert on coverage mismatch, incomplete matrices, endpoint readiness, and permission errors. For long-running or high-volume solve workloads, submit work through Lakeflow Jobs and retain the external job/run identifier in Lakebase.
