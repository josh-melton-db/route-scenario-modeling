# Valhalla regional matrix service

This FastAPI service runs a precompiled `valhalla_service` subprocess on localhost and
exposes `POST /matrix` and `POST /augment-matrix`. A Databricks job places a shared
Valhalla engine and independently selectable regional tile archives in a Unity Catalog
Volume. At startup the App service principal reads the manifest and downloads the
configured region through the Files API, then
extracts it under ephemeral `/tmp`; Databricks Apps do not FUSE-mount UC Volumes.

Example body:

```json
{"new_point":{"lat":42.3314,"lon":-83.0458},"existing_points":[{"lat":42.9634,"lon":-85.6681}],"costing":"auto"}
```

The response contains both the new row (`from_new`) and new column (`to_new`) because
road travel times need not be symmetric.

For a complete solver matrix, send points in node-index order:

```json
{"points":[{"lat":42.3314,"lon":-83.0458},{"lat":42.9634,"lon":-85.6681}],"costing":"auto"}
```

`POST /matrix` returns Valhalla's directed `sources_to_targets` cells in the same row
and column order. Each cell includes `time` in seconds and `distance` in kilometers;
unreachable cells include Valhalla's error status. The endpoint accepts 2–500 points.
The regional build raises Valhalla's automobile, taxi, and truck limits to 250,000
matrix pairs and 1,000 km per pair; production workloads should still be benchmarked
well below that request ceiling.

`build_valhalla.py` compiles Valhalla 3.5.1 and builds a named region on DBR 15.4 LTS.
The default parameters build Michigan from Geofabrik. The Volume layout is:

```text
manifest.json
engine/valhalla-3.5.1/runtime.tar.gz
regions/michigan/region.tar.gz
```

Additional regions can be published by rerunning the job with another safe `REGION_ID`
and HTTPS `PBF_URL`. Existing region entries remain in the manifest, and a validated
engine archive is preserved during regional refreshes.
`publish_compatible_engine.py` can republish the engine-only archive from a previously
validated DBR 15.4 `runtime/bin` and `runtime/lib` tree without rebuilding map tiles.

## Deploy an existing regional artifact

The parent repository provides a dry-run-first deployment entry point. It requires an
explicit Databricks profile and never discovers credentials or a workspace implicitly:

```bash
scripts/deploy-valhalla-service \
  --profile DEFAULT \
  --region texas \
  --volume demos.route_scenario_modeling.valhalla_assets
```

Review the emitted app resource, generated runtime configuration, and commands. Add
`--execute` to create or reconcile `valhalla-service`, grant its service principal
`READ_VOLUME`, stage only this service, and deploy a snapshot. Override `--app-name` or
`--workspace-path` when operating another isolated environment. Compute defaults to
`MEDIUM`; pass `--compute-size LARGE` if observed Texas startup or matrix memory requires
12 GB. After the CLI reports deployment success, the command performs an authenticated
`/health` poll for up to five minutes and verifies the active region, avoiding startup
races while the regional archive downloads and extracts. Override this with
`--health-timeout SECONDS`. OAuth headers are never printed. This command does not
delete an older app; replacement cleanup is a separate, explicit operator action after
the new service passes smoke checks.

The selected region is any safe lowercase ID and must already be present in the Volume
manifest; deployment is not restricted to the built-in named-extract shortcuts. For the current dev
artifact the complete command is:

```bash
scripts/deploy-valhalla-service \
  --profile DEFAULT \
  --region texas \
  --volume demos.route_scenario_modeling.valhalla_assets \
  --execute
```

After deployment, verify `/health` reports the expected region, coverage ID, and artifact
version, then use `scripts/check-valhalla-coverage` with two representative points to
verify directed truck reachability before recording the region as validated.

## Manual setup

1. Create a managed Unity Catalog Volume.
2. Run `build_valhalla.py` as a notebook task on DBR 15.4 LTS dedicated compute. Set
   `VOLUME_PATH`, `REGION_ID`, and `PBF_URL`.
3. Create a Databricks App with a Volume resource named `valhalla-assets` and grant it
   `READ_VOLUME`.
4. Set `VALHALLA_REGION` in `app.yaml` and deploy this directory as the App source.

No workspace URL, user identity, credential, or resource identifier is stored in this
repository. The App uses its managed service-principal identity at runtime.

## Repeatable named-extract workflow

From the parent repository root, plan a build without making a network call (dry-run is
the default). Git history shows this wrapper previously lived in the parent repository;
it is restored as the supported entry point over `named_extract_setup.py`:

```bash
scripts/setup-valhalla-extract texas \
  --coverage-id texas-delivery \
  --artifact-version texas-YYYYMMDD-N \
  --volume-path /Volumes/CATALOG/SCHEMA/VOLUME \
  --cluster-id USER_SUPPLIED_CLUSTER_ID \
  --notebook-path /Workspace/USER_SUPPLIED_BUILD_NOTEBOOK
```

The emitted Jobs request is credential-free and can be reviewed or retained. Add
`--execute --profile EXPLICIT_PROFILE` only for an authorized build. The tool never
discovers or selects a profile; an explicitly supplied `DEFAULT` is accepted. Add `--rebuild-engine`
only when intentionally replacing the shared engine artifact; normal region refreshes
preserve it. Michigan remains the notebook and bootstrap default. Texas is a named
candidate for Dallas and San Antonio, not provisioned coverage.

After deployment, copy the candidate manifest, replace its endpoint and artifact
fields with observed values, then run:

```bash
scripts/check-valhalla-coverage path/to/coverage.json COVERAGE_ID \
  --point LAT_A,LON_A --point LAT_B,LON_B \
  --profile EXPLICIT_PROFILE
```

The check verifies process health, active region and artifact identity, truck costing,
and reachable matrix cells in both directions before recording timestamped success or
failure. Managed Databricks App endpoints normally require OAuth, so their checks require
an explicitly supplied `--profile`; the SDK obtains bearer headers without printing
tokens. No profile is inferred. Use `--unauthenticated` only intentionally for a local or
explicitly public endpoint. Bounds are deliberately only a preflight; every solve must still validate its
actual directed matrix. The sample in `routing_coverage_samples/` remains
`candidate`/`not_run` and therefore fails strict registry resolution.
