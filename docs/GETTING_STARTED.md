# Getting started

This guide takes a clean checkout from local synthetic mode to a deployed Databricks App backed by Lakebase. Model Serving and Valhalla are optional and covered in [Advanced routing](ADVANCED_ROUTING.md).

## Saved routes and morning preparation

Depot route defaults and named scenario results are saved by network run, depot,
date, and route scenario. Reopening a saved result does not solve it again.
Lakebase retains these results across App restarts; the local stub backend is
in memory. A new network run or baseline horizon has its own plan and results.

The Lakebase seed command now prepares each depot's first date before exiting.
Use `--skip-route-preparation` when you only want to load data. Preparation uses
the configured routing mode and requires its normal solver and data access.

With the same connection environment as the App, prepare today's defaults with:

```bash
DATA_BACKEND=lakebase .venv/bin/python -m backend.services.depot_route_preparation --service-date today
```

Use `--service-date first` (the default) to prepare the first date instead. The
command preserves the full baseline horizon, so the UI finds the same saved
plans. Other dates remain lazy. An infeasible solve is saved too, including its
unserved deliveries. Failed preparation exits nonzero; successful saved results
remain available for the next attempt.

The bundle includes `depot_routes_morning`, a serverless Databricks Job scheduled
for 5:00 AM America/Indiana/Indianapolis. Its notebook calls the running App's
route-preparation API and polls for completion, so compute uses the App's
Lakebase identity and routing configuration. Grant the Job's run-as identity
`CAN_USE` on the App. The App must be running and accessible from job compute.

The schedule defaults to paused. After deploying and validating a manual run:

```bash
databricks bundle run depot_routes_morning -t <target> --profile <profile>
```

Unpause it in Jobs, or set the bundle variable
`depot_routes_schedule_pause_status=UNPAUSED` for subsequent deployments.
Development-mode bundles also pause schedules by default; use a production
target for an active recurring schedule. Always choose your own CLI profile.

This job prepares routes for the active baseline; it does not generate new
demand or advance the finite demo horizon. Today's date must fall inside that
horizon. Changed inputs require a new baseline/run rather than overwriting a
previously saved plan. No live schedule is created by editing these files.

## 1. Prerequisites

- Python 3.12
- Node.js 20+ and npm
- Databricks CLI 1.0.0 or newer (DEFAULT dev verified with 1.19.0)
- A workspace with Unity Catalog, serverless compute, Databricks Apps, and Lakebase Autoscaling
- Permission to create resources in a writable catalog

Check the CLI and list configured profiles:

```bash
databricks version
databricks auth profiles
```

Choose a profile yourself. Every Databricks command below uses `--profile <profile>`; the repository never assumes `DEFAULT` or another profile.

If needed, create and test a profile:

```bash
databricks auth login --host <workspace-url> --profile <profile>
databricks current-user me --profile <profile>
```

## 2. Run locally with synthetic data

```bash
git clone <repository-url>
cd route-scenario-modeling
npm install
npm run setup:python
npm run dev:all
```

Open <http://localhost:5180>. This path uses deterministic synthetic data, the in-memory store, local OR-Tools, and a labeled approximate travel matrix. It needs no Databricks credentials or cloud resources.

The default local backend does not restart automatically when Python files
change, so demo scenarios stay available while editing the frontend. Restart it
manually to apply backend changes. Use `npm run dev:backend:reload` when automatic
backend reload is useful; restarting the in-memory backend clears saved plans
and scenarios. Lakebase is required for results that survive backend restarts.
The browser keeps a session copy of network scenario parameters for recovery;
restoring these parameters creates an editable draft, not a solved result.

## 3. Configure deployment

Deployment is driven by one operator JSON file. Start with
`configs/deployment/minimal.example.json`; copy it outside the example file and
set the catalog and existing Lakebase owner role. The `minimal` preset creates
only the App, SQL warehouse, schema, raw volume, required Lakebase resources,
and the required idempotent network-bootstrap job. It does not include the full
planning job, pipeline, Valhalla, or Model Serving.

```bash
cp .env.example .env
```

Fill in each required value. Resource names and ownership values must describe your workspace. Keep `.env` local; Git ignores it.

At minimum, choose:

- a Unity Catalog catalog and schema;
- an App name and SQL warehouse name;
- a Lakebase project, application branch, database, endpoint, and owner role;
- `ROUTE_EXECUTION_MODE=approximate_development` for the first deployment.

Check the workstation and configuration before creating resources:

```bash
set -a; . ./.env; set +a
npm run doctor
DATABRICKS_CONFIG_PROFILE=<profile> npm run doctor:deploy
```

Resolve every reported error. The command checks local dependencies, explicit authentication, required variables, and configuration consistency.

## 4. Render, validate, and deploy

```bash
npm run build
scripts/deploy-demo --config <operator-config.json> \
  --profile <profile> --target dev --dry-run
scripts/deploy-demo --config <operator-config.json> \
  --profile <profile> --target dev
```

Dry-run renders an inspectable bundle under `.databricks/deployment-render/` and
does not contact Databricks. The deploy command renders the same bundle, runs
strict validation, then uses `databricks apps deploy` to deploy and start it. It
then runs `network_bootstrap`, grants the App service principal read access to
the canonical schema, and leaves Lakebase migration and reset writes to the
running App service principal. A successful one-command deployment therefore
creates canonical data without changing ownership of the App-owned Lakebase
schema.
Both `--profile` and `--target` are required; no workspace is inferred.

Changing an existing deployment from `enhanced` to `minimal` can remove optional
resources previously owned by that bundle. Use minimal for a new deployment, or
review the bundle plan deliberately before changing presets.

`--output` is intended for CI inspection outside the checkout. Existing custom
directories are accepted only when empty or marked as a render previously owned
by this repository. The tool refuses repository ancestors, unowned non-empty
directories, symlinks, and custom paths inside the checkout. Local `.env*`,
`.aws`, `.codex`, and `.agents` content is never copied into a staged bundle.

Use a dedicated Lakebase application branch or schema. On first startup, the App service principal must create the application schema so it owns the objects used by the app. Deploy before connecting a local process to an empty database.

Inspect the deployed resource:

```bash
databricks apps get <app-name> --profile <profile>
```

## 5. Initialize demo state

The App applies Lakebase migrations at startup under its service-principal
identity. Use the App's **Reset demo** action (or its reset API) to install the
canonical baseline and clear disposable scenario state. This keeps all writes
to the App-owned schema under the identity that owns it.

The reset is destructive to demo scenarios and plans. Do not run it against a
database containing decisions you need to retain. The local
`backend.services.lakebase_seed` command is an operator recovery tool, not part
of normal deployment; using it requires intentional ownership/role access.

For an existing demo where a local process created `network_demand_changes` or
`network_baseline_option_revisions` before the app, the owner can use the scoped
recovery below. It grants app read/write access only to these two legacy tables,
without dropping rows or transferring ownership. Omit `--execute` to inspect
first. Future schema migrations still require the table owner; fresh setups
should always deploy the app first.

```bash
.venv/bin/python scripts/repair-lakebase-demo-access \
  --profile <profile> --app <app-name> --endpoint <endpoint-resource-path> \
  --database <postgres-database-name> --schema <app-schema> --execute
```

## 6. Verify the deployment

Open the App URL returned by `databricks apps get`. For a minimal configuration,
confirm readiness reports Lakebase connected and migrated, the SQL warehouse
available, local OR-Tools selected, and approximate routing selected. For the
enhanced regional configuration, confirm `serving_regional`, the configured
Model Serving endpoint, validated Texas coverage, and the labeled approximate
fallback policy for depots outside coverage.

Then complete a small scenario:

1. Inspect a network baseline.
2. Create a named scenario.
3. Run the solve.
4. Open a depot and its daily plan.
5. Compare the result with baseline.
6. Reload the App and confirm the run and decision remain available.

Run the quick check before a demo and the complete gate before publishing changes:

```bash
npm run verify:fast
npm run verify:full
```

## 7. Load governed planning data

Normal deployment already runs the required canonical bootstrap. To rerun only
bootstrap and repair the App schema grant using the same JSON variables:

```bash
scripts/deploy-demo --config <operator-config.json> \
  --profile <profile> --target dev --bootstrap-only
```

The bootstrap creates canonical network tables only when the complete set is
absent and does not erase Lakebase scenario state or accepted decisions. An
enhanced deployment also retains the full planning job and pipeline. Run those
from the rendered bundle directory with the same explicit `--var` values shown
in `.deployment-vars.json`; running from the repository root does not load an
operator JSON automatically. See [Adapting the accelerator](ADAPTING.md) before
substituting real data.

The App also attaches the required network-bootstrap job with `CAN_MANAGE_RUN`,
exposed as `DATABRICKS_NETWORK_BOOTSTRAP_JOB_ID`. This lets reset orchestration
rerun bootstrap when canonical tables are absent. The deploy command applies
the schema read grant automatically. To repair or audit it manually:

```bash
python3 scripts/grant-network-schema --profile <profile> \
  --principal <app-service-principal-id> --schema <catalog>.<schema>
```

## 8. Test the clean-clone path

Before a release, run the deployment rehearsal from a clean copy of tracked files:

```bash
scripts/test-clean-clone --config configs/deployment/dev-enhanced.json \
  --profile <profile> --target dev
```

The script accepts only a tracked, repository-relative operator config. It
clones tracked files, installs dependencies, runs the verification gate, renders
the config, and deploys through `scripts/deploy-demo`. This is intentionally a
release rehearsal: uncommitted files are absent from the clone.

## Troubleshooting

### Authentication is ambiguous

Pass both `-t <target>` and `--profile <profile>`. Public bundle targets do not contain a profile.

### Lakebase reports `permission denied for schema`

The schema was probably created locally by a user before the App service principal started. Use a fresh app-owned schema or branch. Export required data before removing an existing schema.

### A route solve asks for Valhalla or Model Serving

Select `ROUTE_EXECUTION_MODE=approximate_development`. Road matrices and managed solving are opt-in modules described in [Advanced routing](ADVANCED_ROUTING.md).

### The SQL warehouse is unavailable

Synthetic local mode does not need it. A deployed App uses it for governed analytical reads; confirm the resource exists and the App has `CAN_USE`.
