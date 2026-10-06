# Network shortage reallocation frontend inventory

## Scope

This inventory covers network frontend work only. It excludes `Layout`, reset flows, depot route components, backend behavior, and deployment.

The intended workflow is:

1. Start from a real shortage for one depot and service date.
2. Open **Reallocate supply** with that source context locked.
3. Load backend-qualified donor options and show their feasible availability.
4. Create or update a named network scenario.
5. Re-solve the scenario before showing a comparison.
6. Open the solved comparison; this workflow has no separate accept operation.

No frontend surface should infer donor availability, invent supply, or convert a horizon shortage into a service-date shortage.

## Current shortage surfaces

| Surface | Current shortage signal | Context available now | Reallocation integration |
| --- | --- | --- | --- |
| `NetworkPage` KPI strip | Network-level `kpis.unmet_units` | Horizon and region, no source depot/date | Summary only; cannot launch a scoped action |
| `NetworkPage` planning insight rail | `unmet_demand` insight with optional entity ID | Facility may be known; date is absent | Add action only when backend supplies depot/date context |
| `NetworkFlowMap` facility tooltip | Computes `demand_units - assigned_units` | Facility and horizon aggregate | Add action only through an explicit shortage context prop; do not derive a date |
| `NetworkDetailDrawer` facility details | Demand and assigned flow shown separately | Facility and horizon aggregate | Add a shortage callout/action when an exact dated shortage is supplied |
| `DcPage` DC KPI | Computes DC unmet demand | DC and one URL-selected service date | DC total is not an immutable source depot; no direct action |
| `DcPage` depot table | Computes each depot's unmet demand | Depot and URL-selected service date | Eligible once the backend confirms the row is date-granular |
| Scenario Flow KPI/compare | Scenario and baseline `unmet_units` | Scenario/run and horizon | Summary only; no unique source depot/date |
| Scenario Flow map/drawer | Run exceptions aggregated by facility | Scenario/run and facility; dates are discarded by aggregation | Preserve dated exceptions and expose actions per exact shortage |
| Scenario Exceptions table | Unmet exceptions grouped by depot across the horizon | Individual records contain nullable `service_date`, but grouping removes it | Replace/augment with dated rows; this is the primary action surface |

`CustomerImpactTable` and `ConstraintViolationsTable` belong to the depot route workflow and are out of scope.

## Proposed frontend structure

- `NetworkShortageContext`: scenario/run identity when applicable, immutable `source_facility_id`, `source_facility_name`, `service_date`, `unmet_units`, and provenance ID.
- `ReallocateSupplyAction`: shared contextual trigger. It renders only for a complete, backend-sourced context.
- `ReallocateSupplyModal`: owns donor loading, selection, transfer amount, scenario name/selection, create-or-update, solve progress, comparison, and acceptance state.
- Query hooks and API types for shortage detail, feasible donors/preview, reallocation mutation, and acceptance. Keep server response states explicit: loading, empty, partial, failed, infeasible, solving, solved, and accepted.

The source depot and date stay read-only throughout the modal. Closing and reopening the modal resets transient donor/preview state but preserves no fabricated defaults.

## Backend contract needed

The frontend needs a backend-qualified shortage identifier or the following immutable tuple: run/baseline revision, source depot ID, service date, and shortage quantity. Horizon aggregates are insufficient.

The donor preview response should include:

- donor facility ID/name;
- feasible transferable units for this source/date;
- donor capacity before and after the proposed transfer;
- transfer mode, direction, distance or transit time, and governed cost;
- qualification/rejection reasons;
- partial-data and freshness metadata.

The write contract should support creating a named scenario or updating an eligible draft with optimistic revision control. It must return the saved scenario revision. Solving must use that revision and return a run/result identifier before comparison is enabled.

The workflow persists through the existing scenario POST/PATCH, validate, and run operations. A solved comparison is the terminal frontend state; there is no separate accept endpoint.

## Map lane design

Ordinary linehaul should render as a straight directional path. Express air transfers should render as long elevated arcs, visually distinct from linehaul, with persistent mode/cost labels and clear origin-to-destination direction. Local distribution remains a straight local path.

Solved synthetic lanes are identified by `mode='AIR'` and `eligibility_source='scenario_express_air_transfer_v1'`. Preview-only requests do not appear on the map. Map data is split into ordinary linehaul, local distribution, and solved express AIR layers; labels show direction, mode, and solved total cost.

## Facility capacity UI

The scenario editor persists `facility_capacity_retained_pct` for the full scenario horizon. Values are bounded to 0–100, 100% entries are omitted, and 0% means closed. The backend computes effective daily handling throughput with `floor(base * pct / 100)`. Local outbound cases, imported cases, and onward transfers share that single facility-and-day handling limit.

Canonical `facility_capacity_daily.capacity_units` is handling throughput; it is not inventory or available supply. The current generated dataset has no independent DC inventory/supply measure. An AIR transfer therefore cannot relieve a shortage caused only by destination handling throughput. A positive out-of-stock AIR reallocation demonstration requires a separately governed inventory or supply input and must not infer donor stock from spare handling capacity.

## Honest states and sequencing

- Loading: skeleton/spinner with the source context still visible.
- Empty: “No feasible donors returned” with backend reasons when present.
- Partial: show available donor facts and a visible partial-data notice; disable commit if required fields are absent.
- Error: retain user input and provide retry; do not show stale preview as current.
- Solve: disable compare/accept until the returned revision finishes solving.
- Infeasible: show solver diagnostics and allow revising the donor/quantity.
- Compare: identify baseline and candidate run IDs and show shortage, cost, service, and capacity deltas.

## Implementation order after decisions

1. Add API types/client/query hooks from the agreed backend schema.
2. Preserve dated shortage records in scenario results and add the shared action to every eligible shortage surface.
3. Build the modal through preview, create/update, solve, and compare states.
4. Split map layers and add express transfer labels/direction using the canonical transfer discriminator.
5. Replace binary facility controls with percentage capacity only if the scenario assumption contract is confirmed.
6. Add focused component/e2e coverage for immutable source context, partial/error states, revision-safe solve sequencing, and map classification.
