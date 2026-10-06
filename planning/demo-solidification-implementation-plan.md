# Repeatable demo and optional routing services

## Objective

Provide a configurable minimal deployment (application and required data resources) and an enhanced deployment (regional Valhalla and Model Serving solver). Deploy and verify the enhanced configuration in the explicitly selected DEFAULT workspace, using supplychain as the application catalog. Preserve existing uncommitted changes.

## Implementation workstreams

1. **Valhalla service:** rename `valhalla_poc` to `valhalla_service`, preserving its nested repository; inspect history for the missing extract setup script; restore a supported entry point. Add repeatable, explicitly profiled region deployment using existing artifacts or a named-extract build. Replace the authorized legacy `valhalla-api-poc` app with `valhalla-service`, loading the existing Texas artifact. Validate health, artifact identity, and directed truck matrix before recording coverage.
2. **Execution configuration:** separate solver selection from matrix coverage policy. Enhanced mode uses the serving endpoint for depot solves, validated Texas road matrices for covered points, and explicitly marked approximate matrices outside coverage. Covered-region failures must surface as errors rather than silently degrade. Keep existing strict modes compatible. Ensure actual depot planning, including partitioned days, invokes Model Serving.
3. **Demo reset:** make the existing reset action clear previous network scenarios/runs and depot plans, restore deterministic generated baseline data, and asynchronously warm configured serving resources with visible readiness. Verify tariff severity reduces cross-border flow while network optimization remains a network min-cost-flow problem distinct from depot vehicle routing.
4. **Deployment and documentation:** introduce one operator configuration and repeatable entry point for minimal/enhanced setups, catalog/schema/resources, Valhalla region/artifacts, solver endpoint, and coverage policy. Optional resources must actually be optional. Declare application service-principal permissions. Document region addition, solver replacement, reset behavior, and the exact demonstration sequence.
5. **Integration and dev acceptance:** run focused backend/configuration tests and frontend build; validate the bundle strictly; deploy to DEFAULT; exercise reset twice, tariff/network solves, a Texas depot solve showing Model Serving plus Valhalla, and an uncovered-region solve showing Model Serving plus approximate matrix. Record evidence and limitations in this plan or an adjacent report.

## Delegation and ownership

- Service worker: `valhalla_service/**`, rename of `valhalla_poc`, extract/deploy tooling specific to the service, service tests. No legacy app deletion until the replacement is tested.
- Execution worker: `backend/config.py`, depot execution/planning and coverage services, associated tests. Coordinate new execution mode/env contract with integrator.
- Reset worker: baseline reset/repositories, warm-up service/API and relevant frontend reset/readiness behavior, associated tests.
- Integrator (main agent): deployment configuration/scripts, bundle resources and manifests, top-level documentation, integration review and deployment coordination.
- Dev test worker: authenticated deployed workflow acceptance and evidence report after integration is ready; no conflicting deployment mutations.

## Acceptance criteria

- A documented command chooses minimal or enhanced without source edits or guessed credentials.
- DEFAULT enhanced app can repeatedly reset into the tariff demo; prior scenarios/plans do not survive reset.
- Texas service reports the observed Texas artifact and passes a directed truck matrix check.
- Texas depot results identify Valhalla and Model Serving; outside-coverage results identify approximation and Model Serving.
- Reset starts endpoint warm-up without exceeding the app HTTP proxy timeout and exposes failure/readiness accurately.
- Latest source is deployed and tested; legacy app removal is limited to the explicitly authorized `valhalla-api-poc`.

## Current observations

- Existing Texas artifact: `demos.route_scenario_modeling.valhalla_assets`, region `texas`, coverage `texas-delivery`, artifact `texas-20261002-v1` (must reverify before use).
- Existing solver `route-solver-dev` can be reused after checking its contract against depot execution.
- Existing app mode couples matrix and solver; this needs an explicit enhanced coverage-aware mode.
- Texas coverage must be based on real tiles and solve points; do not claim all six TOLA depots are covered by a Texas extract.

## Completion evidence

- Service renamed and made available as parent-repository source. Separate local history is preserved in `.databricks/valhalla-service-git-history`.
- Missing extract wrapper recovered from parent git history (`959d58d^`) and restored as `scripts/setup-valhalla-extract`.
- `valhalla-service` deployed on DEFAULT with Texas artifact `texas-20261002-v1`; coverage smoke succeeded at `2026-10-05T15:47:06Z`. Legacy `valhalla-api-poc` deletion confirmed.
- Added operator JSON configurations and `scripts/deploy-demo`; minimal excludes optional solver/Valhalla/planning pipeline while retaining required canonical-data bootstrap.
- Added `serving_regional`, explicit outside-coverage approximation policy, remote partition solves, reset orchestration, data seeding/bootstrap, and asynchronous real solver warm-up.
- Dev deployment revealed and fixed two existing deployment assumptions: staged files under gitignored `.databricks/` require explicit runtime sync includes; development-mode schema consumers must reference the resolved schema resource name. Actual dev schema is `supplychain.dev_josh_melton_route_scenario_modeling`.
- Live reset exposed successful-but-truncated inline SQL results. Read-only snapshots now retry through external chunks while retaining strict completeness checks. Reset loads the selected canonical versions/horizon asynchronously to stay within the Apps proxy timeout. The resolved schema name is materialized before upload because Apps environment variables do not interpolate bundle resource references at runtime.
- Broad suite: 244 passing tests; changed reset response and configuration edit timing required focused reruns. Latest focused configuration, reset, readiness, and route-execution checks: 40 passing tests. Final deployed acceptance evidence is recorded separately in `demo-solidification-dev-verification.md`.

DEFAULT live workflow acceptance passed on 2026-10-05: cross-border assigned cases were 3,761 at baseline, 1,791 with $0.10/case tariffs, and zero with $5/case tariffs. Dallas used Model Serving plus Valhalla; Little Rock used Model Serving plus the explicit outside-coverage approximation. Repeated reset deleted disposable scenarios/plans; final cleanup reset restored the original baseline and completed solver warm-up.

Legacy local setup had created two tables under the operator identity: `network_demand_changes` and `network_baseline_option_revisions`. Scoped DML grants repaired app access without deleting rows or transferring ownership. `scripts/repair-lakebase-demo-access` documents this explicit recovery; new deployments avoid it by letting the app create its schema first. Access-time demand-change checks no longer issue an unnecessary owner-only ALTER on an already migrated table.

Latest local gates include 29 ownership/reset/SQL tests and 16 network snapshot/readiness/deployment tests, strict bundle validation, frontend production build, and clean diff whitespace checks. Minimal rendering/configuration is tested locally; live acceptance exercised the enhanced DEFAULT configuration. Browser-driven visual acceptance and a clean-clone deployment were not run; the changes remain uncommitted in the shared worktree.
