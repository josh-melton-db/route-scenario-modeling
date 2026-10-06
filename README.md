# Route Scenario Modeling

Route Scenario Modeling is an independently maintained demo for testing changes to a multi-depot delivery network before committing them. It demonstrates one complete planning loop:

> Personal project, not a Databricks product or supported offering. You may copy and adapt it under the MIT License; use it at your own risk. See [License](#license).

> inspect network → create scenario → solve → drill into depot → compare → persist decision

The default path uses deterministic synthetic data, local OR-Tools, and an approximate travel matrix. It runs without Model Serving or Valhalla.

## Architecture

```text
Unity Catalog / Lakehouse
  → governed analytical and planning inputs

Lakebase
  → low-latency scenarios, runs, edits, and application state

Databricks App
  → React + FastAPI interaction layer

Model Serving / Valhalla
  → optional computational services
```

Keeping analytical inputs, interactive state, the application, and compute services behind separate interfaces is the repository's central design lesson. Each layer can evolve independently.

## Five-minute local run

Prerequisites: Python 3.12, Node.js 20+, and npm.

```bash
git clone <repository-url>
cd route-scenario-modeling
npm install
npm run setup:python
npm run dev:all
```

Open <http://localhost:5180>. The API runs at <http://localhost:8002/api/health>.

This local mode sets no Databricks profile and needs no cloud resources. The FastAPI backend uses the bundled synthetic store; route solves use local OR-Tools with approximate travel assumptions.

For a repeatable presentation date, start with `DEMO_DATE_ANCHOR=2026-09-30 npm run dev:all`.

## Deploy to Databricks

The deployment path uses one operator JSON configuration and always requires an explicit bundle target and Databricks CLI profile. The minimal preset creates only the App and required SQL, Unity Catalog, and Lakebase resources:

```bash
cp .env.example .env
# Fill in the required values, then check the workstation and configuration.
set -a; . ./.env; set +a
npm run doctor
DATABRICKS_CONFIG_PROFILE=<profile> npm run doctor:deploy

npm run build
scripts/deploy-demo --config configs/deployment/minimal.example.json \
  --profile <profile> --target dev --dry-run
scripts/deploy-demo --config <operator-config.json> \
  --profile <profile> --target dev
```

Use `configs/deployment/dev-enhanced.json` as the concrete pattern for jobs,
pipeline, an existing solver endpoint, and regional Valhalla routing. See
[Advanced routing](docs/ADVANCED_ROUTING.md) before adapting that example.

No profile is selected by the repository. See [Getting started](docs/GETTING_STARTED.md) for authentication, variables, first deployment, synthetic seeding, and verification.

## Use only what you need

| Component | Can be reused independently? | Dependencies |
|---|---:|---|
| `route_opt` | Yes | Python, OR-Tools |
| Synthetic generator | Yes | Faker, Pandas |
| Lakebase state layer | Mostly | Lakebase, migrations |
| FastAPI backend | Yes | Store implementation |
| React UI | Yes | Backend API contract |
| Network planning | Yes | Canonical network tables |
| Depot routing | Yes | Matrix provider and solver |
| Valhalla service | Yes | Vendored service source; regional artifacts in a UC Volume |

Read [Adapting the accelerator](docs/ADAPTING.md) before replacing synthetic inputs or selecting only part of the stack.

## Repository map

```text
route_opt/     reusable optimization, synthetic data, and planning logic
backend/       FastAPI API and store/service implementations
src/           React application
notebooks/     data generation, planning, and publishing tasks
pipelines/     Lakeflow pipeline definitions
resources/     Databricks bundle resources
valhalla_service/ vendored regional matrix service and deployment tooling
docs/          public setup, architecture, and adoption guides
planning/      internal implementation history (not distributed)
```

## Documentation

- [Complete deployment](docs/GETTING_STARTED.md)
- [Adapting the accelerator](docs/ADAPTING.md)
- [Demo script](docs/DEMO_SCRIPT.md)
- [Advanced routing](docs/ADVANCED_ROUTING.md)
- [Architecture and data contracts](docs/ARCHITECTURE.md)
- [Supported feature boundaries](docs/FEATURE_BOUNDARIES.md)
- [Contributing](CONTRIBUTING.md)

The in-process workers are suitable for an accelerator, workshop, and controlled demo. Use Lakeflow Jobs for durable production execution, retries, scheduling, and operational isolation.

## Verification

```bash
npm run verify:fast   # sub-minute developer check
npm run verify:full   # complete local suite
```

The full suite covers Python tests, TypeScript checks, a production build, bundle size, and Git whitespace validation.

## License

This is Josh Melton's personal repository. It is not a Databricks product, an official Databricks solution, or a supported offering. Databricks customers are welcome to use, copy, modify, and adapt the code for their own projects under the [MIT License](LICENSE); the license permits the same use by others. Keep the license notice when redistributing substantial portions.

The code is provided **as is**, without warranties or a support commitment from the author or Databricks. You are responsible for reviewing its security, data handling, costs, and fitness for your environment before using it, especially in production. The MIT License contains the controlling warranty disclaimer and limitation of liability.
