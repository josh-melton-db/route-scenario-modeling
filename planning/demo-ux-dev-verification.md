# Demo UX: DEFAULT live acceptance

## Status

The later separate-supply implementation and final live acceptance supersede the positive AIR limitation below. See [Supply and handling capacity implementation and verification](supply-and-handling-capacity-implementation-plan.md) for deployment `01f1c1b095321270b96d5916f1f52244` and the final clean state.

**PASS — final DEFAULT API acceptance completed on 2026-10-06 against deployment `01f1c19ec3bf1f14b2f26eba50260b4a`. Independent final readiness, cleanup, and solver warm-up reads passed. Browser acceptance and positive stock-shortage AIR relief remain explicitly unverified. Earlier failures and repairs are retained below.**

Preparation made no live mutations. The parent gave GO and the combined harness was started, but a new deployment made the app unavailable during the run.

## Authenticated harness

Run from the repository root only after deployment is ready and the parent gives GO:

```bash
DATABRICKS_AUTH_STORAGE=plaintext .venv/bin/python scripts/test-dev-demo \
  --profile DEFAULT \
  --app route-scenario-modeling-dev
```

The harness resolves the app URL with `WorkspaceClient(Config(profile="DEFAULT"))` and obtains request headers through the SDK authentication provider. It does not read, embed, log, or persist tokens. `--app` may be an app name or authenticated URL.

This is destructive demo acceptance. It resets the demo before testing and again during final cleanup. A best-effort cleanup handler is armed after the first reset. Do not run it without explicit GO.

## Acceptance contract

The existing checks remain in place:

1. Readiness reports regional Model Serving, a configured endpoint, Dallas inside validated routing coverage, and Little Rock outside it.
2. Repeated reset clears disposable network scenarios and depot plans and completes solver warm-up.
3. One-day baseline, mild-tariff, and severe-tariff runs prove monotonic tariff response and elimination of cross-border assignment at the severe rate.
4. Dallas records Model Serving adapter invocation with a requested Valhalla truck matrix and validated coverage/artifact identity.
5. Little Rock records Model Serving adapter invocation with the explicit outside-coverage approximation and no Valhalla request.

The added UX checks verify:

1. A seeded baseline validates without `planning_rate_fallback`; its persisted scenario rate coverage has governed charges and zero fallback charge count/assigned units.
2. A three-day depot plan automatically solves only its first day. The next day remains `not_requested` until explicitly requested.
3. Two solve requests while that future day is pending, followed by another request after completion, retain one selected result and do not add result-history rows.
4. A named daily override combines one added delivery and a facility move. The selected result contains the added customer and one extra assigned case, route geometry starts or ends at the moved coordinates, and a fresh API read returns the same result ID.
5. `facility_capacity_retained_pct={"DC_TOLA_DALLAS": 1}` reduces assigned volume relative to the matching three-day control.
6. An AIR request uses the deployed contract:

```json
{
  "transfer_id": "ACCEPTANCE_HOUSTON_DALLAS",
  "origin_dc_id": "DC_TOLA_HOUSTON",
  "destination_dc_id": "DC_TOLA_DALLAS",
  "departure_date": "<default horizon start>",
  "capacity_units": 5000
}
```

The persisted movement must have `mode=AIR` and a future `arrival_date`. In the pure handling-capacity bottleneck test, the movement must remain unused, assigned-volume gain must be zero, and dated unmet demand must match the retained-capacity control. This proves an AIR request cannot bypass handling capacity or admit unrelated national sources. Positive stock-shortage transfer acceptance remains pending the separate generated supply dataset decision.

Canonical seeded lanes and the scenario-created AIR lane have different pricing contracts. The canonical-lane assertion requires governed rates and no fallback warning. AIR cost and transit are calculated by the scenario transfer adapter; AIR acceptance therefore records its persisted cost, transit, provenance, and conservation without claiming a governed canonical rate-book match.

## Route feasibility and adapter invocation

These are separate acceptance claims:

- **Adapter invocation** comes from `execution`: `solver`, `solver_invoked`, endpoint/model identity, `matrix_requested`, matrix source, coverage/artifact identity, costing, and approximation flags.
- **Route feasibility** comes from the depot result: terminal status, assigned/routed/unserved cases, diagnostics, and persisted routes. A successful remote invocation does not prove that every synthetic customer is road reachable.

The live evidence must report both. Dallas may invoke Model Serving and Valhalla while returning an infeasible result with explicitly unserved road-unreachable demand; that is truthful adapter success plus partial route feasibility.

## Evidence

### Local, non-destructive preparation — 2026-10-06

- `python3 -m py_compile scripts/test-dev-demo`: passed.
- `.venv/bin/pytest -q tests/test_network_transfers.py backend/tests/test_depot_plan_api.py backend/tests/test_depot_plan_service.py`: **24 passed** in 1.91 seconds; one dependency deprecation warning.
- No DEFAULT API calls or browser mutations were made.

### DEFAULT live API evidence

**INCOMPLETE — interrupted 2026-10-06; rerun required.**

Harness session `46561` targeted `route-scenario-modeling-dev` with profile `DEFAULT`. It completed reset #1 and warm-up, created the disposable scenario and Dallas depot plan, advanced through reset #2 deletion verification, and completed the baseline/mild/severe tariff scenario phase. It then failed at the first added UX check:

```text
POST /api/network/runs/network-run-7d5bdc9c-7bf6-4513-aee0-871cc68f4a08/depots/DPT_TOLA_DALLAS/plans
HTTP 500 request_id=24c13794-b2df-40e0-96bb-08c3dadd3185
```

Runtime logs establish the exact lazy-plan defect:

```text
psycopg.errors.CheckViolation: new row for relation "depot_plan_jobs"
violates check constraint "depot_plan_jobs_status_check"
status=not_requested
```

`DepotPlanService.get_or_create_plan` correctly constructed unsolved future-day jobs with `status=not_requested`, but the existing Lakebase constraint still allowed only `queued`, `running`, `completed`, `infeasible`, and `failed`. `CREATE TABLE IF NOT EXISTS` did not update that existing constraint. The prepared repair advances the migration ledger, includes `not_requested` for clean schemas, and explicitly drops/recreates `depot_plan_jobs_status_check` for existing schemas.

The registered cleanup reset began, but polling `/api/network/baseline/reset/status` returned HTTP 502. A read-only app status check immediately afterward showed deployment `01f1c196268c1b848bd67aa5238293fe` in `IN_PROGRESS`, the app `UNAVAILABLE`, and source download/build activity at 14:57–14:58. The network backend worker later confirmed that deployment was started mistakenly at 14:56 and has finished. The concurrent deployment explains the cleanup 502, while the database traceback independently proves the lazy-plan 500 root cause.

Final cleanup and solver warm-up are **unproven for this interrupted run**. A separate reset/warm-up completion at 14:55:31 predates the harness mutations and is not final-state proof. After the active deployment and bootstrap report readiness 200, rerun the complete harness from its initial reset through final cleanup. Do not resume midway.

Valhalla's updated bounded-source two-point smoke passed at 15:01:50. That is infrastructure/matrix evidence only; it does not claim that all generated customer coordinates are road feasible. Scope-aware road-generator repair and rate-anchor regression work remain inputs to the integrator's final deployment.

Required evidence fields include seeded rate coverage, tariff assigned units, lazy/idempotent depot result IDs and result count, persisted override result/customer/moved coordinates, retained-capacity assigned reduction, AIR departure/arrival/assigned capacity and assigned gain, Dallas execution metadata, Little Rock execution metadata, reset deletion counts, warm-up state, and final cleanup state.

### Authenticated browser evidence

**Blocked by browser authentication on 2026-10-06.** The embedded browser was navigated to the deployed app without making any mutation. It redirected to the Databricks workspace login page and had no authenticated accessibility tree. No reset confirmation, scenario creation, or solve was attempted. API authentication through the DEFAULT SDK profile does not substitute for visual acceptance.

If workspace SSO cannot be completed in the available browser session, report that authentication limitation explicitly. API acceptance through the DEFAULT SDK profile remains valid but does not substitute for a visual/browser claim.

## Final-deployment rerun — 2026-10-06

The full harness was rerun against deployment `01f1c1972c0116e38111121c92a623a6` after readiness reported migration `2026_10_06_lazy_depot_status_v15` ready. Session `64206` completed initial reset and solver warm-up, then failed while creating the disposable one-day Dallas depot plan:

```text
service_date=2026-10-05
assigned_cases=7879
status=failed
error=Valhalla snapped source 18 0.298 miles; limit is 0.250 miles
```

The harness did not relax the 0.250-mile bound, use an approximation, or claim route feasibility. Because the disposable plan failed, this run did not reach reset #2, tariff scenarios, lazy future-day solving, persisted overrides, retained-capacity comparison, AIR transfer acceptance, or the uncovered-depot fallback check.

The harness's registered final cleanup ran. Independent authenticated reads proved:

- reset `reset_complete` at `2026-10-06T15:14:04.824332+00:00`;
- solver warm-up `ready` at `2026-10-06T15:14:10.014262+00:00`;
- `/api/ready` status `ready`, including Lakebase migration `2026_10_06_lazy_depot_status_v15` ready;
- routing coverage still identified Dallas, Houston, and San Antonio as validated Texas depots;
- `/api/network/scenarios` returned an empty list.

This is an actual generated-road feasibility failure, separate from adapter invocation. The plan failed before a selected result existed, so it provides no successful Model Serving or Valhalla invocation claim for the route solve. The failed Texas repair authorization and subsequent local validator work remain outside this acceptance result.

## Cleanup

On a passing run, the harness performs a final reset, waits for solver warm-up, verifies an empty network-scenario list, and proves the sampled depot plans return 404. On failure after the first reset, the registered cleanup handler attempts the same reset. Any cleanup warning must be treated as a live-state follow-up rather than ignored.

## Repaired-Texas partial run — 2026-10-06

Publication job `398992635550844` succeeded before this run, reporting 300 scoped Texas customers validated, 300 lanes refreshed, and matching source/proof hashes. The harness targeted deployment `01f1c199b387146480bdebd04975eef3` in session `92216`.

Passed before the run was intentionally stopped:

- initial reset and real solver warm-up;
- disposable one-day Dallas plan with the strict zero-`road_unreachable` assertion;
- reset #2 deletion proof;
- seeded canonical rate validation with no fallback warning;
- baseline, mild-tariff, and severe-tariff assertions;
- first-day-only lazy depot planning;
- idempotent future-day solve without duplicate persisted results;
- persisted named override combining an added delivery and facility move, with the delivery anchored to a successfully routed baseline customer and zero `road_unreachable` retained.

A model review found that imported DC flow bypasses retained throughput. The harness reached the retained-capacity/AIR phase, completed the retained-capacity control, and launched the AIR scenario. The operator intentionally terminated local harness process `92216` with Ctrl-C at that boundary; no deployment or external tool termination stopped it. Neither result is accepted as physical-capacity or conservation evidence. The dedicated final Dallas execution-provenance check and uncovered-depot fallback check occur later in the harness and were not reached.

The immediate automatic cleanup received HTTP 409 because the AIR network run was still active. Read-only polling showed that run subsequently reached `solved`. Final cleanup was then run explicitly and proved:

- reset `reset_complete` at `2026-10-06T15:31:26.333815+00:00`;
- solver warm-up `ready` at `2026-10-06T15:31:31.426245+00:00`;
- `/api/network/scenarios` returned `[]`;
- readiness status was `ready`;
- the final deployed migration reported `2026_10_06_lazy_depot_status_v16` ready.

A later read-only check returned the same reset and warm-up timestamps, readiness `ready`, migration v16 `ready`, and zero scenarios. No harness session remains active. Successful reset admission and completion also prove there were no queued/running network or depot jobs at cleanup time; reset would otherwise return HTTP 409.

This is a partial acceptance, not an overall pass. Full acceptance must rerun after the shared handling-cap model correction and must still execute Dallas Valhalla provenance, uncovered-region fallback, retained-capacity conservation, AIR future-arrival/conserved-supply assertions, and final cleanup.

For the next model run, retained-capacity acceptance must use a capacity-only case and prove imported flow cannot bypass the shared handling cap. The AIR request is a pure shared-throughput bottleneck negative case against that unchanged control: it must assign zero transfer units, produce zero assigned-volume gain, and leave dated unmet demand unchanged. This result makes no mathematical claim about dataset inventory and does not constitute positive-transfer acceptance. Positive AIR gain remains pending a product decision to generate a synthetic donor-supply dataset; it does not require a user inventory upload. Dallas Valhalla provenance and uncovered-region fallback remain mandatory independent checks.

## Shared-capacity final rerun and regional-scope correction

After recovery of the orphaned daily job, the centrally controlled harness ran against `01f1c19c0d7411a29e18043bb15f6585`. Reset/deletion, solver warmup, all tariff cases, strict Dallas road reachability, lazy/idempotent future-day solving, persisted daily overrides, and zero AIR movement passed. The dated unmet-demand comparison failed. Final cleanup reset/warmup completed.

Review identified different regional scoping between the direct and time-expanded solver: the transfer path admitted unrelated national sources/demand. The correction aligns participating DCs and reserved existing demand with the standard regional path, and additionally reserves existing demand for requested transfer endpoints. A regression adds an unrelated cheap national source and proves an unused AIR request preserves regional unmet demand. All six transfer tests passed, and `git diff --check` passed.

The corrected app deployed successfully as `01f1c19ec3bf1f14b2f26eba50260b4a`; frontend validation/type checking/build passed. Bootstrap run `111562180895726` succeeded. Final centrally owned harness evidence is retained locally in `.databricks/dev-demo-final-acceptance.log`; no concurrent deploy is permitted during this run.

## Final passing DEFAULT acceptance — 2026-10-06

The complete harness exited 0 with `PASS`. An earlier attempt encountered an incomplete HTTP result read and cleaned up. The harness now retries incomplete GET responses at most twice; mutations are never retried. Two incomplete result reads were recovered in the passing run.

- Seeded canonical rates: zero fallback charges and zero fallback assigned cases; 45,786 governed assigned cases across eight charges.
- Cross-border assigned cases: baseline **3,761**, tariff $0.10/case **1,791**, tariff $5/case **0**.
- Lazy daily scheduling, repeated future-day requests (one persisted result), added delivery, moved facility, fresh-read persistence, and zero road-unreachable customers passed.
- Dallas retained at 1% normal throughput reduced assigned cases by **49,165** versus the matching three-day control.
- AIR negative case: departure October 5, arrival October 6, requested capacity 5,000, assigned movement **0**, assigned gain **0**. Departure-day unmet demand was **15,276** in both cases; dated unmet demand matched throughout. This is shared-throughput/scope correctness evidence, not positive stock-shortage relief.
- Dallas invoked `route-solver-dev`, model version18, with a real Valhalla truck matrix and `texas-20261002-v1`/`texas-delivery`; approximation false and no road-unreachable customers.
- Little Rock invoked the same Model Serving endpoint with `haversine_circuity`, approximation true, and no Valhalla matrix request.
- Final reset completed at **16:09:18 UTC**, endpoint warm-up ready at **16:09:23 UTC**; scenarios empty and sampled depot plans returned404.
- Independent post-harness reads returned readiness200/ready, migrationv16 ready, reset complete, solver warmup ready, and an empty scenario list.

Local full evidence: `.databricks/dev-demo-final-evidence.json` and `.databricks/dev-demo-final-acceptance.log`. The deployment has not been changed after the passing run.
