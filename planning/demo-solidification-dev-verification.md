# Demo solidification: DEFAULT dev verification

## Purpose

This report records the destructive, authenticated acceptance test for the enhanced demo deployment. The harness verifies the deployed application workflow through its public API; it does not deploy or reconfigure workspace resources.

## Harness

Run from the repository root after the main deployment is confirmed ready:

```bash
DATABRICKS_AUTH_STORAGE=plaintext .venv/bin/python scripts/test-dev-demo \
  --profile DEFAULT \
  --app route-scenario-modeling-dev
```

`--app` accepts either an app name or URL. `--texas-depot`, `--uncovered-depot`, and `--timeout` are configurable. Authentication comes from `databricks.sdk.core.Config(profile=...)`; authorization headers and tokens are never printed.

The test intentionally mutates demo state. It:

1. Requires `/api/ready` to report `serving_regional`, a configured serving endpoint, and validated routing coverage.
2. Resets the demo and polls through asynchronous `resetting`, `seeding_lakebase`, canonical UC `bootstrapping`, and solver warm-up phases.
3. Creates a disposable network scenario and Texas depot plan, resets again, then proves the scenario and depot plan were deleted.
4. Solves one-day TOLA baseline, $0.10/case, and $5/case MX-to-US tariff scenarios. Because min-cost flow is discrete, the mild tariff must be monotonic (no increase); the severe tariff must eliminate cross-border flow. The evidence reports actual values without claiming a partial shift when none occurred.
5. Solves Dallas through Model Serving with a Valhalla truck matrix and persisted coverage/artifact metadata.
6. Solves Little Rock through Model Serving with the explicit outside-coverage approximation fallback.
7. Captures evidence, performs a final reset, awaits solver warm-up, proves no scenarios or test depot plans remain, then prints a redacted JSON summary containing execution metadata but no credentials. Best-effort final cleanup is also registered for failures after the initial reset.

The single-day horizon keeps the destructive acceptance run bounded while exercising the same network and depot execution paths used by the repeatable demo.

## Expected persisted execution contract

Texas result metadata must include:

- `solver: model_serving`, `solver_invoked: true`, and a non-empty solver endpoint and served-model identity
- `matrix_source: valhalla`, `matrix_requested: true`, and `approximate: false`
- non-empty `coverage_id` and `artifact_version`, with `costing: truck`

Outside validated coverage, result metadata must include:

- `solver: model_serving`, `solver_invoked: true`, and served-model identity
- `approximate: true` and `approximation_reason: outside_validated_coverage`
- `matrix_requested: false`

## DEFAULT dev evidence

Status: **PASS — authenticated deployed API acceptance, 2026-10-05**.

The main integrator ran the delegated worker's harness against DEFAULT. It
exited zero and printed `[dev-demo] PASS`. The latest app deployment is
`01f1c0d9d02319128386830a230a2564`, confirmed SUCCEEDED/RUNNING after a transient
CLI polling network failure. The recovery bootstrap run
`223619208036167` succeeded. The live app uses
`supplychain.dev_josh_melton_route_scenario_modeling`.

| One-day TOLA scenario | Cross-border assigned cases |
|---|---:|
| Baseline, no tariff | 3,761 |
| $0.10/case MX-to-US tariff | 1,791 |
| $5/case MX-to-US tariff | 0 |

Verified execution:

- Dallas: `solver=model_serving`, `solver_invoked=true`, endpoint
  `route-solver-dev`, served model `demos.route_scenario_modeling.route_solver`
  version `18`, served entity `route-solver-dev-v18`, solver contract `2`,
  OR-Tools `9.8.3296`; `matrix_source=valhalla`, `matrix_requested=true`,
  `approximate=false`, truck costing, coverage `texas-delivery`, artifact
  `texas-20261002-v1`.
- Little Rock: the same remote solver, with `approximate=true`,
  `approximation_reason=outside_validated_coverage`, and no Valhalla request.
- Repeated reset: disposable network scenario and depot plan no longer existed
  (404); scenario listing was empty after reset.
- Final cleanup: reset completed at `2026-10-05T17:53:46.109578Z`; the real
  warm-up solve completed at `2026-10-05T17:53:51.236351Z`. Final independent
  GET checks confirmed `reset_complete`, warm-up `ready`, `/api/ready=ready`,
  and an empty network-scenario list. The demo was left on its original baseline.

## Fixes exercised during live acceptance

Staged bundle sync now explicitly includes runtime source. Apps environment
configuration now materializes the development-prefixed UC schema before
deployment. Successful-but-truncated inline SQL snapshots retry using external
chunks, retaining row-count/completeness checks. Canonical reset loading runs
asynchronously and scopes inputs to the selected versions/shared horizon.

Legacy local setup had created `network_demand_changes` and
`network_baseline_option_revisions` under the operator identity. App DML access
was repaired only for those two tables with
`scripts/repair-lakebase-demo-access`; no tables or rows were dropped for this
repair. Ownership remains unchanged. Access-time demand-change checks avoid
unnecessary owner-only ALTER statements. Fresh setups should deploy first so
the app creates and owns its objects.

## Validation boundaries

Latest local focused gates passed: 29 ownership/reset/SQL tests and 16
network-snapshot/readiness/deployment tests. Strict bundle validation and
frontend production builds passed. The earlier broad suite had 244 passing
tests; changed-contract/configuration failures required focused reruns.

This was API acceptance, not a browser-driven visual test. Enhanced DEFAULT was
deployed and exercised; minimal configuration rendering is tested locally but
was not separately deployed. A clean-clone deployment was not run because
these changes remain uncommitted in the shared worktree.

Real road routing can reveal infeasible synthetic coordinates. Dallas metadata
identified `NET-CUST-TOLA-0055` as road-unreachable; this test does not claim that
every generated customer was served. Covered-road failures do not silently
switch to approximate matrices. The serving endpoint can scale to zero again
after inactivity; Reset demo performs another real warm-up invocation.
