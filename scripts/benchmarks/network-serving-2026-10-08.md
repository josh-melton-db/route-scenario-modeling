# Network solver serving experiment — October 8, 2026

## Scope and setup

Profile: `DEFAULT`. Production App and `route-solver-dev` configuration remain unchanged.
The existing network solver runs OR-Tools directly inside the App; it does not invoke
the depot route-serving endpoint, so warming that endpoint cannot remove network-solve latency.

An isolated CPU Small endpoint, `network-solver-benchmark-20261008`, was created with
`scale_to_zero_enabled=false`, using `demos.route_scenario_modeling.network_solver_benchmark`,
version 2. The benchmark packages the existing deterministic solver; it trains no model.

The exact frozen input comes from run `network-run-1f23f801-180b-4f9d-ab6d-2249bb132f74`,
scenario `NSC_8AF1894A81`, revision 3, all regions, October 8–November 4.
It includes 117,600 customer-demand rows, 56 facilities, 4,342 lanes, and pinned dated
contract/tariff objective coefficients. Isolated AIR and LINEHAUL transfer variants
use the same inputs and a 5,000-case New Jersey-to-Atlanta transfer; LINEHAUL targets
Atlanta's Nashville depot. These requests create no live scenario or plan.

Solver-consumed tables still require approximately 89 MB of JSON, so the adapter
uses gzip/base64 input and output. Measurements include full solver-output transfer;
hashes verify exact equality against an in-process solve of the identical input.
Client measurements originate from the developer workstation, not from inside the App.

## Always-warm endpoint results

Three sequential requests per case were sent only after both endpoint readiness
fields confirmed `READY` and `NOT_UPDATING`; scale-to-zero was verified disabled.
All nine endpoint outputs matched their identical-input in-process output hashes.
Medians:

| Case | Local solver only | Endpoint solver only | Warm endpoint request |
| --- | ---: | ---: | ---: |
| Current tariff scenario | 0.699 s | 1.360 s | 3.967 s |
| AIR transfer | 0.542 s | 0.796 s | 4.473 s |
| LINEHAUL transfer | 0.533 s | 0.919 s | 4.750 s |

Endpoint request times include request transport, server-side decode, solve,
serialization/compression, and full result transport. Request compression on the
client costs another 1.04–1.06 s, excluded from that request column. Request sizes
are about 3.52 MB after compression; responses are 0.98 MB for the current scenario
and 2.12 MB for transfers. Uncompressed outputs are 31.14 MB and 53.65 MB.
Endpoint-side input decode alone costs 0.66–0.95 s.

Initial endpoint provisioning and dependency/container creation were completed
before measurement; these are setup times, not warm request latency. We did not
force an idle cold-start test because the experiment intentionally disables
scale-to-zero, and the production network solver already runs in the App.

The workstation-to-endpoint transport differs from App-to-endpoint networking.
Nevertheless the endpoint's solver-only time is already slower than the local
same-input replay and comparable to or slower than recent deployed App solves.
No evidence supports moving the network solver to this Small always-warm endpoint
for single-user demo latency. A larger endpoint or a redesigned compact interface
could change compute/concurrency behavior, but neither addresses the measured
10–11 s snapshot persistence or 7–13 s loading/copying bottlenecks.

The endpoint was deleted after testing; an immediate SDK `get` returned `NotFound`.
The benchmark UC model and experiment remain for reproducibility and have no
running serving compute. Detailed credential-free samples and cleanup verification
are in `network-serving-2026-10-08-results.json`.

## Existing deployed App measurements

Finalized snapshot diagnostics, including persistence, show:

| Run suffix | Total measured stages | Input load/copy | Solver | Persistence |
| --- | ---: | ---: | ---: | ---: |
| `1f23f801…` | 31.98 s | 13.23 s | 0.89 s | 11.35 s |
| `6bb20daa…` | 25.57 s | 7.35 s | 0.69 s | 10.88 s |
| `573f973b…` | 24.84 s | 7.66 s | 0.65 s | 10.36 s |

The solver accounts for less than 3% of the measured stages. Snapshot payloads are
about 153 MB. These totals exclude any frontend polling/queueing time.
Use snapshot diagnostics from `/api/network/runs/{run_id}`: the scenario result
stores the earlier diagnostics before the persistence timer is finalized.

The deployed initial-load endpoints also measured:

- Overview: 4.23 / 4.13 s, about 3.52 MB response.
- Baseline plan-run: 7.26 / 8.10 s, about 5.03 MB response.

## Local initial-load improvements (not deployed measurements)

The accompanying local changes reduce the network-home context response to 323 bytes
and avoid loading network facts, rating, and copying the full baseline snapshot just
to obtain two IDs. Local service comparison: 0.0027 s for context versus 3.62 s for
the full approximately 4.98 MB result.

Network-map projection returns only visible freight lanes, retaining identical KPIs
and facility summaries: 128,931 bytes versus 3,517,938 bytes, 96.3% less.
Revision/filter-keyed caching produced about 0.10 s warm local map service time.
These local numbers are not cloud before/after results.

## Reproduction

Package an isolated endpoint with `deploy_network_serving.py`, passing an explicit
profile, existing UC model namespace, unique endpoint name, and experiment path.
Dependencies for registration include MLflow and boto3. Poll both readiness fields
until `READY` and `NOT_UPDATING` before measuring.

Run `measure_network_serving.py --payload <private-input-file> --profile DEFAULT
--endpoint <isolated-endpoint> --output <private-measurements-file> --repeats 3`.
The input shape is `{ "rows": {...}, "options": {...} }`; date/lane keyed cost
maps are represented as `[date, lane_id, amount]` triples. The measurement script
rejects scale-to-zero endpoints and any allocation hash mismatch.

Raw frozen data stays in private temporary files; no credentials are logged or
committed. Remove the isolated always-warm endpoint after testing to stop its cost.
