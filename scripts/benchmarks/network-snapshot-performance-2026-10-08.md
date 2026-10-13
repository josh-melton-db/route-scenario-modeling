# Network snapshot performance changes — October 8, 2026

Code review found reference manifests and compressed solver output already exist
for Lakebase runs. The earlier 153 MB diagnostic measured the fully expanded
inputs plus outputs, rather than bytes actually persisted per referenced run.
Shared immutable baseline revisions remain the source of historical inputs.

This change removes repeated full copies from the solve's source, normal-capacity,
and comparison views. Capacity/supply normalization copies just the tables it
mutates. Solver output replaces tables rather than editing shared records.
Database saves serialize owned bytes without first copying the full snapshot;
the in-memory repository still makes defensive copies at its ownership boundary.
Historical map requests read `result_payload` directly, while depot planning and
baseline promotion retain full snapshot reconstruction, including legacy runs.

Compression uses zlib level 3 rather than 9, with the same checked envelope format.
Small transfer/provenance metadata tables are now preserved in reference manifests.
Unchanged shared mutable tables bypass delta scanning by object identity.

Local component benchmark using the same frozen 28-day inputs as the serving
experiment, including solver flow rows and source baseline cost rows:

| Work | Before | After |
| --- | ---: | ---: |
| Three full input copies vs. shared views and capacity isolation | 3.7602 s | 0.0065 s |
| Compress 30,626,661-byte output envelope | 0.2228 s | 0.0490 s |
| Compressed envelope bytes | 701,628 | 903,666 |

Both compression levels decompress to identical bytes. These are laptop component
measurements, not deployed end-to-end solve times. The changes were subsequently
deployed to `route-scenario-modeling-dev` using profile `DEFAULT`; deployment
succeeded, app state was `RUNNING`, and authenticated health returned HTTP 200.
The existing historical run `network-run-1f23f801-180b-4f9d-ab6d-2249bb132f74`
reopened in 0.790 seconds with populated map facilities and lanes. A new cloud
solve has not yet been timed. Database normalized flow/audit writes remain synchronous and may still
account for substantial persistence time; no historical inputs or audit rows are
discarded to make these changes faster.

New `snapshot_storage_bytes` diagnostics report envelope plus manifest size,
excluding shared baseline and result/audit tables. For `reference-zlib-json-v1`
runs, `snapshot_json_bytes` measures that envelope's uncompressed JSON plus the
manifest, not a freshly serialized expansion of the whole network. Older runs
retain their original diagnostics unchanged.
