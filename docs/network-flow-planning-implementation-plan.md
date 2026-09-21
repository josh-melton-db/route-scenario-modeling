# Network Flow Planning Implementation Plan

## Purpose

This plan extends the route scenario modeling application from depot-level route planning into a coordinated US network planning experience. The finished application will let a planner compare nationwide flows, create a network scenario across multiple distribution centers and depots, generate detailed depot plans, and reconcile those plans back into one governed network result.

Demand forecasting and capacity planning are explicitly outside the application boundary. The application consumes immutable, versioned demand and capacity plans produced elsewhere. For the demo, deterministic synthetic data will represent those upstream outputs.

The recommended product flow is:

```text
Published demand plan ──┐
Published capacity plan ├─> Network flow scenario ─> Depot plans ─> Reconciliation
Rates and topology ─────┘              │                  │               │
                                      └──── compare and publish ──────────┘
```

## Agreed product decisions

- The application is a planning product, not a live logistics control tower.
- Demand and capacity can be displayed and used as constraints, but this application does not forecast demand or determine required capacity.
- A network scenario coordinates flow across multiple distribution centers and depots.
- A network scenario governs detailed child scenarios for the affected depots and service dates.
- Network and depot plans synchronize through explicit versioned operations. They do not silently overwrite one another.
- The physical hierarchy is `Region -> Distribution center -> Depot -> Customer`.
- The domain supports distribution-center linehaul, depot-to-market flow, and depot-to-customer delivery detail.
- All demo data is synthetic, internally consistent, reproducible, and trusted for the purposes of the demo.
- Permissions and approval policy are outside the initial implementation scope.

## Scope

### In scope

- Consume published demand and capacity snapshots.
- Display network demand, capacity, assigned flow, utilization, service, and cost.
- Compare a baseline network with a network scenario.
- Optimize flow allocation through a fixed topology and fixed supplied capacities.
- Model facility or lane availability, allocation rules, service requirements, transportation costs, and contract choices.
- Detect infeasibility and report unmet demand or constraint violations.
- Generate detailed depot scenarios from a solved network scenario.
- Run affected depot scenarios in parallel with the existing route solver.
- Rate private-fleet and carrier activity with reproducible charge details.
- Reconcile depot results into facility, regional, lane, and network totals.
- Track parent-child versions and synchronization status.
- Publish a coordinated network plan with immutable input and rate-book references.

### Out of scope

- Demand forecasting, seasonality modeling, and forecast selection algorithms.
- Capacity acquisition, capacity sizing, fleet purchasing, or recommendations to add capacity.
- Inventory placement and replenishment optimization beyond transportation flow balance.
- Live shipment monitoring, real-time dispatch, tendering, or execution-system updates.
- Automated incident response and operational rerouting.
- Automated two-way changes to upstream demand or capacity plans.
- Permissions, approval routing, and persona-specific access control.
- Generative AI features from the Logistics Control Center example.

## Planning hierarchy and lane semantics

### Facility hierarchy

| Level | Meaning | Planning role |
| --- | --- | --- |
| Region | Logical geographic grouping | Filters, aggregation, and comparison |
| Distribution center | Primary network flow node | Receives, transfers, and allocates demand |
| Depot | Local delivery origin | Owns detailed daily route plans |
| Customer | Delivery destination | Owns demand, service windows, and delivery requirements |

A facility can have more than one operational role, but it has one stable `facility_id`. A distribution center that also dispatches local delivery routes remains one facility with both roles rather than two records joined by name.

### Lane types

| Lane type | Grain | Purpose |
| --- | --- | --- |
| `LINEHAUL` | Facility to facility | DC-to-DC and DC-to-depot transportation |
| `MARKET` | Depot to market or service territory | Aggregated demand allocation and coverage |
| `DELIVERY` | Depot to customer route leg | Detailed route sequence and costing |

Region is not a physical lane endpoint. Regional flows are calculated by aggregating facility-level lanes.

Contract lane rules must reference canonical endpoint IDs and endpoint types. Display names can change and must not be used as joins or rate-matching keys.

## Demo scope and narrative

The initial demo should contain:

- 4 US regions.
- 8 distribution centers, two per region.
- 24 depots, three per distribution center.
- Approximately 2,400 customers, around 100 per depot.
- A four-week network planning horizon in daily buckets.
- A detailed seven-day depot-planning window.
- Multiple transportation modes and governed carrier rate books.
- Millions of synthetic upstream demand or order records, reduced to readable facility and lane aggregates for the application.

The interactive solver should generate child plans only for materially affected depots by default. A `Generate all depot plans` action can demonstrate parallel execution across the full network.

### Primary demo scenario

Southeast demand grows while the Atlanta distribution center has reduced supplied capacity. The planner selects the published demand and capacity plans, creates a network scenario, and changes permitted flow paths or allocation policies. The network flow solve shifts volume through Nashville and Charlotte. The application then generates affected depot plans, solves their detailed routes, applies carrier contracts, and reconciles the resulting cost and service performance back into the network scenario.

The application reports insufficient supplied capacity as unmet demand or an infeasible constraint. It does not recommend purchasing capacity or change the upstream capacity plan.

## Synthetic data design

Synthetic data must be generated from a common set of constraints instead of independently randomizing dashboard KPIs.

```text
Customer demand
  -> depot and market demand
  -> DC-to-depot supply requirement
  -> DC-to-DC balancing flow
  -> facility and lane utilization
  -> route and carrier costs
  -> regional and network KPI rollups
```

### Required properties

- Use a fixed random seed and configurable scale factors.
- Publish demand and capacity as immutable plan versions with source metadata.
- Ensure customer demand sums to depot, distribution-center, regional, and network demand.
- Ensure assigned flow never exceeds supplied facility or lane capacity.
- Preserve unmet demand explicitly when the network is infeasible.
- Derive utilization, service, and cost from generated facts rather than generating them independently.
- Generate coordinates and hierarchy assignments before lanes so all endpoints are valid.
- Generate realistic alternate paths so network scenarios have meaningful choices.
- Generate effective-dated contract coverage for every intended carrier lane and deliberate gaps for validation demonstrations.
- Generate multiple published input snapshots, including a normal plan and a regional-growth or constrained-capacity plan.

### Input plan metadata

Every demand and capacity snapshot must include:

- Stable plan ID and revision.
- Display name.
- Source system.
- Published timestamp.
- As-of timestamp.
- Horizon start and end.
- Time grain.
- Unit of measure.
- Record count and validation status.

The UI will display this lineage wherever a planner selects or inspects an input plan.

## Data architecture

Unity Catalog remains the governed store for synthetic upstream inputs, network dimensions, time-series aggregates, and published results. Lakebase remains the low-latency transactional store for scenario drafts, run state, version links, and authoring workflows.

### Governed network dimensions

- `dim_regions`
  - `region_id`, `region_name`, display order, geometry or map bounds.
- `dim_facilities`
  - `facility_id`, name, facility type, region, parent facility, latitude, longitude, timezone, operating roles, active dates.
- `dim_markets`
  - `market_id`, name, region, centroid, service attributes.
- `dim_network_lanes`
  - `lane_id`, lane type, origin endpoint, destination endpoint, mode, distance, transit time, active dates.
- `facility_hierarchy`
  - Ancestor and descendant IDs, relationship type, and effective dates when a simple parent relationship is insufficient.

### External planning inputs

- `demand_plan_versions`
- `demand_plan_daily`
  - Plan version, service date, market, depot or customer, demand units, priority, and service requirement.
- `capacity_plan_versions`
- `facility_capacity_daily`
  - Plan version, facility, service date, throughput capacity, and unit.
- `lane_capacity_daily`
  - Plan version, lane, service date, supplied capacity, and unit.

These records are read-only to this application. Scenario records reference their version IDs.

### Network scenario state

- `network_scenarios`
  - Scenario identity, baseline, demand plan version, capacity plan version, horizon, status, revision, and timestamps.
- `network_scenario_changes`
  - Facility availability, lane availability, topology choices, allocation policies, service settings, and other in-scope overrides.
- `network_flow_results`
  - Scenario, service date, lane, assigned volume, utilization, transit time, service result, cost, and rate snapshot.
- `network_facility_results`
  - Scenario, service date, facility, inbound flow, outbound flow, throughput, utilization, cost, and service metrics.
- `network_scenario_kpis`
  - Network and regional KPI aggregates.
- `network_scenario_exceptions`
  - Unmet demand, capacity violations, missing rates, disconnected nodes, and other validation or solve exceptions.

### Parent-child plan links

Add `network_depot_plan_links` with:

- `network_scenario_id`
- `network_revision`
- `depot_id`
- `service_date`
- `depot_scenario_id`
- `input_revision`
- `result_revision`
- `sync_status`
- `generated_at`
- `completed_at`

Existing depot scenario definitions and result tables should remain the source of detailed routes. The link records connect them to their governing network scenario without duplicating route payloads.

### Rate and cost integration

- Network linehaul and market flows use the existing governed contract-resolution and charge-calculation services.
- Depot delivery scenarios continue to rate outsourced routes through the same service.
- Every result stores the contract version and rate-book snapshot used during calculation.
- Network rollups separate linehaul cost from local delivery cost to prevent double counting.
- Published plans retain immutable rate references even after newer contract versions are published.

## Network flow solve

The network solver assigns externally supplied demand through the permitted network while respecting externally supplied capacity. It is a flow-allocation solver, not a demand forecast or capacity-sizing solver.

### Inputs

- Demand plan version.
- Capacity plan version.
- Network topology and active lane set.
- Facility and lane availability overrides.
- Service and allocation policies.
- Effective carrier contracts and costs.
- Existing published plan when branching a scenario.

### Constraints

- Flow conservation at network nodes.
- Supplied facility throughput limits.
- Supplied lane capacity limits.
- Demand satisfaction or an explicit unmet-demand variable.
- Valid origin, destination, mode, and effective-date combinations.
- Required facility or market assignments where configured.
- Service-time or transit-time bounds where configured.

### Objective

Minimize transparent transportation cost plus configured penalties for unmet demand and service misses. Capacity expansion must never appear as a solver decision variable.

### Outputs

- Assigned flow by lane and date.
- Facility inbound and outbound volume.
- Demand assigned to each depot or left unmet.
- Utilization derived from assigned flow and supplied capacity.
- Transparent cost and applied contract detail.
- Constraint violations and explanations.
- Depot planning targets for affected facilities and dates.

## Scenario lifecycle and synchronization

### Network scenario lifecycle

```text
Draft -> Validated -> Solving -> Solved -> Depot plans running
      -> Reconciliation required -> Reconciled -> Published
```

A failed or infeasible run retains its validation and solver diagnostics. Publication requires a solved network flow, completed required child plans, successful reconciliation, and no blocking exceptions.

### Child synchronization states

- `not_generated`: No child exists for the network revision.
- `current`: Child inputs match the parent revision.
- `running`: A child solve is active.
- `completed`: A child result exists and matches its inputs.
- `out_of_sync`: The parent changed after the child was generated.
- `conflict`: Both parent inputs and child-owned changes changed since the last synchronization.
- `failed`: Child validation or solve failed.

### Ownership rules

The network scenario owns:

- Demand and capacity plan references.
- Assigned depot demand.
- Facility and lane availability.
- Network flow and linehaul decisions.
- Targets passed to depot planning.

The depot scenario owns:

- Route construction and stop sequence.
- Fleet and driver usage.
- Private-fleet versus carrier fulfillment.
- Local delivery cost and service results.
- Permitted user edits within the supplied depot target.

### Synchronization operations

- `Generate`: Create a child plan from the current network revision.
- `Rebase`: Regenerate network-owned child inputs while preserving compatible child-owned edits.
- `Resolve conflict`: Show incompatible changes and require an explicit selection.
- `Reconcile`: Aggregate completed child outputs into the parent and calculate variances.
- `Publish`: Freeze the coordinated network and child plan revisions.

There is no automatic bidirectional overwrite. A parent edit marks affected children out of sync; a child edit marks the parent reconciliation stale.

## User experience and routes

### Navigation

Recommended primary navigation:

```text
Network | Depot | Scenarios | Rates | Inputs
```

- `/` redirects to `/network`.
- The existing `/analyze` route becomes the depot-level analysis workspace.
- Global planning context is reflected in URL parameters so links are durable and browser navigation behaves predictably.

### Network overview page

Route: `/network`

Components:

- `NetworkContextBar`
  - Baseline or scenario, comparison scenario, demand plan, capacity plan, horizon, region, lane type, and displayed metric.
- `NetworkKpiStrip`
  - Demand, assigned flow, unmet demand, total cost, cost per unit, on-time service, and utilization.
- `NetworkFlowMap`
  - Facilities sized by throughput and lanes weighted by flow.
  - Metric layers for demand, capacity, assigned flow, utilization, service risk, cost per unit, and contract coverage.
- `NetworkInsightRail`
  - Bottlenecks, unmet demand, high-cost lanes, underutilized supplied capacity, service risks, and contract gaps.
- `FacilityDetailDrawer`
  - Demand, supplied capacity, assigned flow, utilization, cost, service, connected facilities, depots, and scenario changes.
- `LaneDetailDrawer`
  - Flow, supplied capacity, utilization, mode, service, cost, rate coverage, and origin/destination navigation.

Facility actions:

- `Open depot analysis`
- `Create or open depot plan`
- `View child plans`

Lane actions:

- `Inspect rate book`
- `Open origin facility`
- `Open destination facility`
- `Add lane change to scenario`

### Network scenario page

Route: `/scenarios/:scenarioId/network`

Tabs:

- `Overview`
  - KPI deltas, baseline-versus-scenario map, summary, and validation status.
- `Flows`
  - Lane map and table with flow, capacity, utilization, service, cost, and contract details.
- `Facilities`
  - Regional, DC, and depot performance with expandable hierarchy.
- `Depot plans`
  - Child status, synchronization state, result metrics, actions, and batch progress.
- `Assumptions`
  - Input plan versions, topology changes, availability changes, policies, and rate context.

Primary actions change with lifecycle:

- `Validate`
- `Run network plan`
- `Generate depot plans`
- `Run affected depot plans`
- `Reconcile`
- `Publish`

### Depot analysis integration

Example route:

```text
/analyze?depot=DPT_SE_ATL_01&date=2026-09-22&networkScenario=NSC_1042
```

Required changes:

- Initialize depot, date, primary scenario, and comparison scenario from URL state.
- Preserve network scenario context when navigating between pages.
- Add a breadcrumb back to the governing network scenario.
- Display the supplied network target and child synchronization status.
- Show actual versus target demand, cost, and service after the depot solve.
- Provide `Return results to network plan` after a successful child run.

### Scenario list

The Scenarios page should list both scopes with a scope badge:

- `Network`
- `Depot`

Child depot scenarios show their governing network scenario and synchronization status. Standalone depot scenarios remain supported.

## API additions

### Read APIs

- `GET /api/network/options`
  - Regions, facilities, lanes, available demand plans, capacity plans, dates, and metrics.
- `GET /api/network/overview`
  - Network KPIs, facility aggregates, lane aggregates, and insights for a selected context.
- `GET /api/network/scenarios/{scenario_id}`
- `GET /api/network/scenarios/{scenario_id}/results`
- `GET /api/network/scenarios/{scenario_id}/depot-plans`
- `GET /api/network/scenarios/{scenario_id}/reconciliation`

### Mutation APIs

- `POST /api/network/scenarios`
- `PATCH /api/network/scenarios/{scenario_id}`
- `POST /api/network/scenarios/{scenario_id}/validate`
- `POST /api/network/scenarios/{scenario_id}/runs`
- `POST /api/network/scenarios/{scenario_id}/depot-plans/generate`
- `POST /api/network/scenarios/{scenario_id}/depot-plans/run`
- `POST /api/network/scenarios/{scenario_id}/depot-plans/{depot_scenario_id}/rebase`
- `POST /api/network/scenarios/{scenario_id}/reconcile`
- `POST /api/network/scenarios/{scenario_id}/publish`

Network and batch child solves should use the existing durable run pattern: immediately return a run ID, persist stage state, and let the client poll until a terminal state.

## Reuse from Logistics Control Center

The repository at `examples/logistics-control-center` is a reference implementation, not a second application to deploy alongside this one.

| Reference asset | Action |
| --- | --- |
| Deck.gl facility and arc layers | Refactor into the current map component conventions |
| Lane selection, auto-fit, tooltips, and legend | Reuse with canonical network types |
| KPI and right-side detail layout | Adapt to planning metrics and shared styling |
| Lane and incident detail components | Retain only planning-relevant lane patterns |
| Reroute panel | Replace with network-scenario actions |
| Mock API and artificial delays | Do not copy |
| Standalone header, router, and app shell | Do not copy |
| Hard-coded airport-code lane parsing | Replace with canonical endpoint relationships |
| Package-scaled reroute costing | Replace with governed rate calculation |
| Streaming incident pipeline | Defer unless a future operational scope requires it |
| Genie and Knowledge Assistant | Exclude from the initial planning implementation |

Both applications already use compatible React, Deck.gl, MapLibre, and router versions. Consolidating the map code into the current application is preferable to an iframe, microfrontend, or second backend.

## Implementation phases

Implementation status as of September 21, 2026:

- Phase 1 is implemented: canonical schemas, four-region deterministic data, alternate DC paths, normal and Southeast-constrained published inputs, canonical rate endpoints, reconciliation, and validation.
- Phase 2 is implemented: the read-only network overview, governed context API, URL-backed filters and deep links, planning map, KPI and insight surfaces, entity details, and depot round-trip navigation.
- Phase 3 is implemented as a thin end-to-end vertical slice: network scenario authoring (facility/lane assumptions, unmet penalty), validation against published plans, a fixed-capacity min-cost-flow solve that never invents capacity, governed-contract rating with explicit planning-fallback exceptions, Lakebase persistence with revisions, and the five-tab scenario workspace (Scenario, Plan flow, Lane changes, Rate audit, Exceptions). Depot-plan fan-out and reconciliation remain future work.

### Phase 1 Canonical data and synthetic generation

Deliverables:

- Add canonical region, facility, market, and lane definitions.
- Build deterministic synthetic demand and capacity plan generators.
- Generate internally reconciled baseline flows and depot demand.
- Add demand and capacity plan metadata and validation.
- Map current depot IDs into the canonical facility hierarchy.
- Extend contract lane endpoints with canonical IDs and lane type.
- Seed a normal plan and a constrained Southeast plan.

Acceptance criteria:

- Every lane endpoint resolves to a valid canonical node.
- Demand totals reconcile at every hierarchy level.
- Capacity units and time grains are explicit.
- Re-running with the same seed produces the same data.
- Published input snapshots cannot be edited through the application.

### Phase 2 Read-only network overview

Deliverables:

- Add `/network` and make it the default landing page.
- Create network option and overview APIs.
- Add shared URL-backed planning context.
- Implement `NetworkFlowMap`, KPI strip, insight rail, and detail drawers.
- Add durable facility and lane deep links.
- Connect `Open depot analysis` to the existing analysis page.

Acceptance criteria:

- Network totals match underlying synthetic facts.
- Filters update the map, KPIs, and insights consistently.
- Facility and lane selections are addressable in the URL.
- A planner can move from network to depot analysis and back without losing context.

### Phase 3 Network scenario authoring and solve

Deliverables:

- Add network scenario tables and APIs.
- Add the scenario detail page and its five tabs.
- Implement validation for plan versions, topology, capacity constraints, rates, and effective dates.
- Implement fixed-capacity network flow optimization.
- Rate assigned transportation flows through existing contract services.
- Persist results, charge details, exceptions, and run stages.
- Add baseline-versus-scenario comparison.

Acceptance criteria:

- The solver never creates or expands capacity.
- Assigned flow respects supplied capacity or is recorded as unmet.
- Costs are reproducible from stored charge lines and rate snapshots.
- An infeasible scenario returns actionable diagnostics.
- Baseline and scenario maps use identical metric definitions.

### Phase 4 Depot plan generation and parallel execution

Deliverables:

- Add parent-child link and synchronization state.
- Generate depot scenario inputs from solved network assignments.
- Add affected-depot detection.
- Add batch generation and run actions.
- Run child scenarios in parallel using durable run orchestration.
- Add parent breadcrumbs and target context to depot pages.
- Implement rebase and conflict detection.

Acceptance criteria:

- Every generated child references one network revision and one service date.
- Parent changes mark only affected children out of sync.
- Child-owned edits are never silently discarded.
- Batch status shows queued, running, completed, infeasible, and failed children.
- Standalone depot scenarios continue to work.

### Phase 5 Reconciliation and coordinated publication

Deliverables:

- Aggregate child routes, costs, service, carrier allocation, and exceptions.
- Compare targets with detailed results.
- Add network reconciliation status and variance views.
- Prevent publication when required children are stale or incomplete.
- Publish immutable parent and child revision references.
- Display the published network result on the overview page.

Acceptance criteria:

- Depot totals reconcile to facility, region, and network totals.
- Linehaul and local delivery costs are not double counted.
- A child change marks reconciliation stale.
- Published results retain exact input-plan and rate-book versions.
- The primary demo narrative completes without manual data correction.

### Phase 6 Demo hardening

Deliverables:

- Add fixture and Lakebase-backed development paths.
- Add end-to-end tests for the primary narrative.
- Add scale tests for network aggregation and parallel child runs.
- Add loading, empty, partial, stale, infeasible, and failure states.
- Add data lineage and freshness indicators.
- Validate responsive behavior and dense-map performance.
- Update deployment resources and documentation.

Acceptance criteria:

- The frontend production build passes.
- Backend and solver tests pass.
- The complete workflow is repeatable from a clean synthetic seed.
- Map interaction remains responsive at the target facility and lane count.
- Run failures can be diagnosed from persisted stages and logs.

## Testing strategy

### Data tests

- Referential integrity across regions, facilities, markets, lanes, depots, and customers.
- Demand reconciliation across all hierarchy levels.
- Capacity and assigned-flow unit compatibility.
- No assigned flow above supplied capacity.
- Effective-date and contract coverage validation.
- Deterministic synthetic generation.

### Solver tests

- Balanced feasible network.
- Insufficient lane capacity.
- Insufficient facility capacity.
- Disconnected market or depot.
- Disabled facility or lane.
- Alternate path selection.
- Unmet-demand penalty behavior.
- Transparent and repeatable rated costs.

### Synchronization tests

- Initial child generation.
- Parent change affecting one child.
- Parent change affecting many children.
- Compatible rebase with child edits.
- Conflicting parent and child edits.
- Stale reconciliation after a child rerun.
- Publication with current children.
- Publication blocked by stale or failed children.

### End-to-end tests

- Open baseline network and drill into a depot.
- Create and solve the Southeast network scenario.
- Generate and run affected depot plans.
- Inspect carrier costs and charge lines in a child result.
- Reconcile and publish the network scenario.
- Compare the published scenario against baseline on the network map.

## Principal risks and mitigations

### Grain and unit mismatch

Network plans operate at facility and market flow grain while depot plans operate at routes and stops. Use explicit units, daily buckets, and parent target records. Never infer conversions from labels.

### Cyclic parent-child updates

Automatic two-way synchronization can make results non-reproducible. Use immutable revisions, owned fields, explicit rebase, and explicit reconciliation.

### Cost double counting

Linehaul and local delivery costs can overlap. Classify every charge by network segment and roll up from canonical charge lines.

### Map density

The underlying dataset can be large, but the national map must remain readable. Aggregate by facility and lane, filter by hierarchy and metric, and reveal delivery detail only after drill-down.

### Split persistence

Unity Catalog and Lakebase serve different purposes. Keep governed inputs and published aggregates in Unity Catalog; keep mutable workflow state in Lakebase; store immutable IDs linking the two.

### Interactive solve duration

Network and multi-depot solves may exceed a request lifecycle. Use durable runs, parallel child tasks, stage-level progress, retry-safe writes, and resumable reconciliation.

### Misleading synthetic data

Randomly generated KPIs can contradict one another. Generate demand, capacity, flows, routes, and costs through a single reconciled pipeline and validate invariants before seeding the application.

## Default implementation choices

Unless requirements change, implementation should proceed with these defaults:

- Daily network flow buckets over four weeks.
- Detailed child scenarios for seven service days.
- Cases as the initial normalized demand unit, with unit metadata retained for future extension.
- Affected-depot child generation by default.
- Fixed external demand and capacity snapshots within a scenario revision.
- Explicit unmet demand instead of invented capacity.
- Network linehaul and depot delivery costs reported separately and together.
- One consolidated React and FastAPI application.
- Unity Catalog for governed data and Lakebase for interactive state.
- No live incident response or generative AI in the initial implementation.

## Definition of done

The network planning capability is complete when a planner can:

1. Open a nationwide baseline using published demand and capacity plans.
2. Understand flow, utilization, service, and cost from region to route detail.
3. Create and solve a multi-DC network flow scenario without modifying upstream plans.
4. Generate and execute the affected depot scenarios.
5. Inspect detailed private-fleet and carrier costs with applied rate rules.
6. Reconcile depot results into the network result with visible variances.
7. Resolve stale plans or conflicts explicitly.
8. Publish a reproducible coordinated plan and compare it with baseline.
