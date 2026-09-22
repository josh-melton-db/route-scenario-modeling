# Route Scenario Modeling CUJs

> **Document status:** Reverse-engineered current-state product definition, based on the repository as implemented on September 18, 2026. Examples called out as repository examples come from the included local stub data. This document does not represent unimplemented roadmap commitments.

This document describes the critical user journeys (CUJs) supported by the Route Scenario Modeling application. The product is a Databricks-native decision-support workbench for reconstructing a delivery-network baseline, testing operational changes, optimizing private-fleet routes, sourcing overflow to contract carriers, governing rate logic, and comparing service and financial outcomes before a planner changes the operating plan.

The application is designed for transportation and network-planning teams that otherwise assemble route assumptions, carrier costs, customer constraints, and scenario results across disconnected spreadsheets and routing tools. Its role is to make those assumptions explicit, run them through repeatable planning logic, and preserve the resulting evidence. It does not dispatch trucks or execute transportation transactions.

## Product Vision and Scope

### Problem Being Solved and Current Technological Limitations

Transportation planners regularly need to answer questions such as:

> * Can the current delivery plan be explained and reproduced from trusted orders, customers, depots, fleet, and operating parameters?
> * What happens to cost and customer service if a driver is removed, a delivery day changes, new demand is added, or a distribution center moves?
> * Which stops still fit the private fleet, and which should be assigned to an eligible contract carrier?
> * Which published contract rules produced a carrier charge, and will the answer remain reproducible after a new rate version is published?
> * Are scenario results caused by a real network trade-off or by invalid planning inputs?

In a spreadsheet-led process, the baseline is often implicit, route geometry is difficult to inspect, constraints are applied inconsistently, and carrier charges cannot be traced back to a specific version of a contract. Scenario files diverge quickly, comparisons use different assumptions, and manual edits can silently invalidate relationships among customers, orders, depots, fleet, and carriers.

Route Scenario Modeling closes that gap with five connected CUJs:

1. Network baseline reconstruction and analysis.
2. Constraint-aware route scenario modeling.
3. Private-fleet and carrier-sourcing optimization.
4. Governed carrier-rate contract management.
5. Planning-input stewardship.

### Primary Personas

| Persona | Primary decision supported |
| :---- | :---- |
| Transportation / route planner | Determine whether a depot-day delivery plan is feasible and how a proposed change affects routes, cost, and service. |
| Network planner | Test structural changes such as depot moves, demand additions, fleet changes, and delivery-day shifts. |
| Transportation manager | Compare private-fleet and carrier allocation, understand constraint exposure, and review financial trade-offs. |
| Rate / contract analyst | Build, validate, publish, and test governed carrier-rate versions. |
| Planning-data steward | Correct source assumptions safely and promote a validated, auditable planning-data version. |

### End-to-End Decision Flow

```text
Governed planning inputs + published rate contracts
                         |
                         v
             Reconstruct the current baseline
                         |
                         v
        Branch a scenario and stack proposed changes
                         |
                         v
       Precheck -> prepare -> solve private fleet
                         |
                         v
       Source and rate eligible carrier overflow
                         |
                         v
       Compare -> persist -> review decision evidence
```

The common planning grain is **scenario × depot × delivery day**, with route-, stop-, customer-, transportation-allocation-, and carrier-charge detail beneath it.

## Network Baseline Reconstruction and Analysis

### Problem Being Solved and Current Technological Limitations

A scenario has no decision value unless it is compared with a trusted representation of the current network. In many transportation organizations, the current plan exists as a mixture of order extracts, driver knowledge, static route files, and manually maintained cost assumptions. Planners can see that a change produces a different result, but they cannot always establish which baseline route, stop sequence, customer assignment, service window, or cost component changed.

The application creates an explainable baseline from planning inputs and gives users an Analyze workspace in which baseline and scenario results share the same visual and metric language.

**Key considerations:**

> * **Controlled planning slice:** Users analyze a selected depot and delivery day rather than mixing unrelated network partitions.
> * **Reconstructed as-run baseline:** Historical orders are grouped into routes with deterministic baseline logic. This establishes a stable operational reference even when a complete route plan is not available upstream.
> * **Comparable evidence:** Route maps, stop sequences, KPIs, cost categories, transportation allocation, customer impacts, rate charges, and constraint diagnostics use common contracts for baseline and scenario views.
> * **Synchronized maps:** Side-by-side maps allow the planner to compare route geometry without mentally reconciling different zoom levels and map states.
> * **Drill-down before aggregation:** A planner can move from network KPIs to a route and its ordered stops, then to customer or carrier evidence.

### Jobs-To-Be-Done (JTBD)

| Layer | Baseline-analysis JTBD | Implemented product capability |
| :---- | :---- | :---- |
| Data foundation | Assemble consistent depots, customers, orders, fleet, costs, constraints, and revenue inputs. | Lakeflow bronze, silver, and gold transformations normalize the generated or substituted source data in Unity Catalog; Lakebase holds the interactive operating copy. |
| Baseline reconstruction | Create a stable representation of the current route plan. | Deterministic baseline logic groups the selected demand into routes and persists route, stop, and daily-summary snapshots. |
| Planning-slice selection | Focus analysis on one operational area at a time. | Depot and delivery-day filters drive the baseline and comparison queries. |
| Network review | Understand route count, distance, volume, service, cost, revenue, and profit. | The Analyze workspace presents KPI cards and delta-aware measures for baseline or scenario comparisons. |
| Route review | See where each vehicle travels and in what order it serves customers. | Route-colored maps, route selectors, and sequenced stop detail expose route geometry and operating sequence. |
| Cost review | Explain the financial result rather than relying on one rolled-up number. | Cost breakdowns distinguish the modeled operating-cost components and support baseline-to-scenario deltas. |
| Service review | Identify customers whose route, day, sequence, arrival, or window risk changes. | Customer-impact tables report disruption scores and the underlying change dimensions. |
| Decision benchmark | Preserve a common reference for subsequent what-if analysis. | Baseline results are available as scenario parents and as the comparison side of the Analyze workspace. |

### Decision-Grade Output Views

#### Network View: “What does the current plan look like?”

| Output | Implemented interpretation |
| :---- | :---- |
| Planning slice | Selected depot and delivery day. |
| Route plan | Route count, route paths, assigned vehicles, and ordered stops. |
| Demand served | Stop and case totals represented by the plan. |
| Distance and time | Road miles, route duration, late minutes, and overtime minutes. |
| Service | Missed-window counts and customer-level window risk. |
| Economics | Revenue, modeled operating cost, profit, and cost-category detail. |
| Transportation allocation | Stops and cost assigned to the private fleet or contract carriers. |
| Constraints | Hard violations, soft penalties, dropped stops, and explanatory diagnostics when present. |

#### Route View: “Why does this route produce that result?”

| Decision field | Output |
| :---- | :---- |
| Route identity | Scenario, depot, delivery day, route, and vehicle. |
| Geometry | Directed road path when Valhalla is available; explicit fallback geometry otherwise. |
| Stop sequence | Ordered customer stops with demand, service time, and receiving-window context. |
| Utilization | Vehicle capacity and driver-time utilization. |
| Service performance | Arrival timing, window adherence, route duration, and overtime. |
| Cost evidence | Mileage, labor, vehicle, and any carrier-charge contribution represented by the result. |

#### Repository Baseline Example

The bundled stub result for **North Depot / Tuesday** provides the following demonstration baseline:

| KPI | Baseline output |
| :---- | :---- |
| Routes | 4 |
| Stops | 24 |
| Cases | 2,840 |
| Miles | 286 |
| Overtime | 35 minutes |
| Missed windows | 0 |
| Revenue | $17,750 |
| Cost | $4,920 |
| Profit | $12,830 |

These values are illustrative application data, not a production-network claim.

### Cadence

| Activity | Implemented trigger | Planning horizon / scope | Primary purpose |
| :---- | :---- | :---- | :---- |
| Source-data and medallion refresh | On-demand full job run | Configured source history and planning date | Rebuild trusted planning tables. |
| Baseline reconstruction | During the orchestrated job and after a planning-input commit | Depot × delivery day | Establish a current benchmark. |
| Baseline review | Event-driven in the app | Selected depot-day | Understand the current route, service, and cost position. |
| Scenario comparison | After a scenario solve or when a saved comparison is selected | Baseline vs. one saved scenario, or one scenario vs. another | Evaluate a proposed operating change. |
| Metric publication and validation | At the end of an on-demand job run | Cross-scenario analytical history | Refresh certified measures for downstream analysis. |

The repository does not configure a recurring job schedule; production refresh frequency is therefore a deployment decision.

## Constraint-Aware Route Scenario Modeling

### Problem Being Solved and Current Technological Limitations

Network changes are rarely isolated. A driver reduction can increase mileage and overtime. A depot move can improve proximity to some customers while making route-duration or receiving-window constraints impossible elsewhere. New accounts can exceed truck capacity, and a delivery-day change can move demand into a different fleet and contract-capacity context.

Static calculators and one-off spreadsheets struggle to propagate these interactions. Route Scenario Modeling lets a planner branch a scenario from the baseline or another saved scenario, stack multiple changes, validate the combined inputs, solve the resulting routing problem, and compare outcomes with the chosen reference.

**Scenario changes implemented in the application:**

> * Add deliveries by selecting map locations or uploading an Excel workbook.
> * Change available drivers or trucks.
> * Move demand to another delivery day.
> * Move an existing distribution center or add a distribution center.
> * Change private-fleet cost assumptions.
> * Change operating constraints.
> * Change carrier-sourcing mode, eligible carriers, or contract selection.

### Constraint Model

| Constraint / objective | Implemented behavior |
| :---- | :---- |
| Vehicle case capacity | Hard limit; a route cannot exceed the vehicle capacity represented in the solver input. |
| Maximum stops | Hard limit per route. |
| Maximum route duration | Hard limit. |
| Strategic / key-customer receiving windows | Hard time windows. |
| Other receiving windows | Soft windows with late-delivery penalties. |
| Dropped stops | Allowed only behind a deliberately very high penalty so an otherwise impossible solve can expose unassigned demand. |
| Objective | Minimize modeled road mileage, labor, fixed vehicle cost, soft-window penalties, and dropped-stop penalties. |
| Search | OR-Tools cheapest-arc first solution followed by guided local search; the default search limit is five seconds. |

The solver classifies unassigned demand with reasons such as no vehicle, capacity infeasibility, route-duration infeasibility, or solver penalty / no solution. This gives the user a planning diagnosis rather than only a failed status.

### Jobs-To-Be-Done (JTBD)

| Layer | Scenario-modeling JTBD | Implemented product capability |
| :---- | :---- | :---- |
| Define the decision | Name and describe the operating question being tested. | Create a scenario from the baseline or branch from an existing scenario. |
| Build the change set | Represent all relevant changes together. | A scenario draft stacks demand, fleet, day, facility, cost, constraint, and sourcing changes before it is saved. |
| Ingest incremental demand | Add customer stops without rebuilding the source dataset manually. | Map-based delivery creation and Excel upload produce validated scenario deliveries. |
| Validate feasibility inputs | Catch structural issues before invoking optimization. | Scenario precheck validates the scope, references, change payloads, and solver prerequisites. |
| Prepare travel evidence | Represent directed truck travel between depots and stops. | The app requests a Valhalla truck-road matrix and can use an explicitly disclosed Haversine/circuity fallback. |
| Optimize routes | Find a feasible, economically evaluated private-fleet plan under capacity, stop, duration, and time-window rules. | An OR-Tools CVRPTW model is packaged as an MLflow PyFunc and called interactively through Model Serving. |
| Track execution | Let the planner see where a longer solve is in its lifecycle and recover from app restarts. | Lakebase persists queued, precheck, prepare, solve, rate, compare, and persist stages; worker leases support recovery. |
| Explain infeasibility | Identify the binding rule and possible modeling response. | Constraint diagnostics report actual vs. allowed values and contextual recommendations. |
| Compare outcomes | Quantify the operational, service, and financial trade-off. | Analyze supports baseline-to-scenario and scenario-to-scenario KPI, map, route, cost, allocation, customer, rate, and constraint comparisons. |
| Preserve lineage | Keep the result tied to the scenario and inputs that produced it. | Scenario definitions, parentage, changes, runs, stages, and result snapshots are stored durably. |

### Decision-Grade Outputs

For a solved scenario, the application can return the following compact decision record:

| Output | Meaning |
| :---- | :---- |
| Scenario status | Draft, queued/running, succeeded, infeasible, or failed run state as applicable. |
| Parent / comparison | Baseline or prior scenario used as the starting and comparison point. |
| Applied changes | Ordered stack of demand, fleet, facility, day, cost, constraint, and sourcing changes. |
| Route plan | Assigned private-fleet routes, vehicles, stop sequences, timing, distance, and utilization. |
| Unassigned demand | Dropped stops with classified reasons and constraint evidence. |
| Transportation allocation | Private-fleet versus carrier-served stops and cost. |
| KPI deltas | Scenario minus comparison values for routes, miles, overtime, windows, cost, revenue, and profit. |
| Customer impact | Route, sequence, delivery-day, arrival, and service-risk changes with disruption score. |
| Carrier audit | Selected contract version, service date, rules, formulas, and charge lines for rated carrier routes. |
| Constraint diagnosis | Binding constraint, actual and allowed values, severity, and suggested planning responses. |

#### Repository Example: One Fewer Driver

The bundled **One Fewer Driver** scenario demonstrates a feasible trade-off rather than a universally “better” answer:

| KPI | Baseline | Scenario | Decision signal |
| :---- | :---- | :---- | :---- |
| Routes | 4 | 3 | One fewer fixed route / driver. |
| Miles | 286 | 301 | 15 additional miles. |
| Overtime | 35 min | 118 min | 83 additional overtime minutes. |
| Cost | $4,920 | $4,806 | $114 modeled cost reduction. |
| Profit | $12,830 | $12,944 | $114 modeled profit increase. |
| Customer impacts | — | 3 | Review the affected customers before acting. |

The result exposes the management decision: accept more mileage, overtime, and customer disruption in exchange for lower modeled fixed cost, or retain the fourth route.

#### Repository Example: Facility Move South

The bundled **Facility Move South** scenario is infeasible and reports three hard diagnostics:

| Binding issue | Actual vs. policy | Planning interpretation |
| :---- | :---- | :---- |
| Route duration | 668 vs. 600 minutes | The relocated facility cannot serve the route within the configured duration. |
| Receiving window | Arrival 38 minutes after the window | A hard customer commitment is violated. |
| Network feasibility | Failed | No complete plan satisfies the combined constraints. |

The diagnostic suggestions include adding a driver, changing route limits or receiving-window assumptions when business policy permits, selecting another facility location, or using temporary overflow capacity. They are explanatory options; the application does not automatically execute them.

### Cadence

| Activity | Implemented frequency | Scope | Primary purpose |
| :---- | :---- | :---- | :---- |
| Scenario design | Event-driven | One scenario and parent | Formulate a planning question and its combined change set. |
| Precheck | Every scenario run | Scenario inputs | Stop invalid requests before solver cost is incurred. |
| Optimization | On demand | Primarily depot × delivery day | Produce a feasible route plan or explain why one cannot be produced. |
| Run tracking | Continuous while a run is active | One durable run | Show progress and recover leased work after interruption. |
| Planner review | After the result is persisted | Selected comparison pair | Decide whether the trade-off warrants an operating-plan change. |
| Scenario reuse | Event-driven | Saved scenario lineage | Branch a follow-on scenario without overwriting the prior decision record. |

## Private-Fleet and Carrier-Sourcing Optimization

### Problem Being Solved and Current Technological Limitations

Private-fleet routing and for-hire carrier sourcing are often modeled in separate tools. That split can make overflow appear either free or unavailable, ignore effective contract dates and lane eligibility, and obscure whether an apparent savings is caused by a routing improvement or a carrier-rate assumption.

The application solves the private fleet first, identifies stops that remain unassigned, groups eligible overflow into carrier routes, and rates those routes from a governed Lakebase rate book. Private and carrier results are then included in the same scenario comparison.

**Key considerations:**

> * **Private fleet first:** Available internal vehicles are used in the CVRPTW solve before overflow is sourced.
> * **Explicit sourcing policy:** Automatic mode chooses among eligible published contracts; locked mode pins the scenario to one contract.
> * **Eligibility before price:** Carrier and contract status, service date, sourcing mode, carrier pool, lane, and available stop capacity are applied before quote comparison.
> * **Lowest eligible quote:** Automatic sourcing selects the lowest modeled quote among the contracts that pass those filters.
> * **Reproducible rating:** Every carrier route retains its service date, contract and version, matched rule IDs, formulas, charge lines, and deterministic rate-book snapshot.
> * **No silent repricing:** A later published rate version does not rewrite the charge evidence stored with a historical scenario.

### Jobs-To-Be-Done (JTBD)

| Layer | Transportation-allocation JTBD | Implemented product capability |
| :---- | :---- | :---- |
| Use private capacity | Assign feasible demand to the available internal fleet. | CVRPTW optimization respects vehicle capacity, maximum stops, duration, and customer-window policy. |
| Explain overflow | Identify demand that could not be served by the private plan. | Dropped-stop reasons distinguish vehicle, capacity, duration, and solver causes. |
| Apply sourcing policy | Decide whether overflow can use a carrier pool or must use a named contract. | Scenario sourcing settings support automatic eligible-carrier selection or a locked contract. |
| Filter contracts | Exclude contracts that are inactive, out of date, out of lane, or out of capacity. | The rating service evaluates carrier status, contract status, published version dates, lane rules, and stop capacity. |
| Build carrier routes | Consolidate unassigned stops into rateable transportation work. | Eligible overflow stops are grouped into carrier routes for the selected depot-day context. |
| Compare quotes | Choose the least-cost eligible governed option. | Automatic sourcing evaluates transparent quotes and selects the lowest eligible result. |
| Audit the bill | Explain how the selected quote was constructed. | The charge ledger identifies line-haul, mileage, stop, tier, minimum, fuel, accessorial, and commitment components where applicable. |
| Preserve the commercial basis | Keep historical scenario economics reproducible. | The run persists the exact rate-book snapshot and contract-version evidence used at solve time. |

### Rating Components

| Charge component | Implemented purpose |
| :---- | :---- |
| Lane base | Flat charge associated with the matched origin-destination lane rule. |
| Mileage | Rate applied to rated distance, using the rule's mileage-rounding policy. |
| Stops | Per-stop charge after included stops. |
| Volume-tier adjustment | Tiered adjustment based on the governed unit and breakpoints. |
| Minimum adjustment | Charge required to bring the route total up to a contractual minimum. |
| Fuel | Effective-dated surcharge applied to its configured basis. |
| Accessorials | Rule-coded additional charges included in the quote request. |
| Commitment shortfall / overage | Modeled adjustment relative to published capacity-commitment rules. |

### Decision-Grade Transportation Record

| Output | Example form |
| :---- | :---- |
| Transportation mode | Private fleet or contract carrier. |
| Assignment status | Routed, carrier-assigned, or unassigned. |
| Demand covered | Route and stop identifiers, cases, distance, and service date. |
| Sourcing decision | Automatic pool or locked contract. |
| Selected commercial basis | Carrier, contract, immutable version, and matched lane. |
| Capacity evidence | Available stop capacity and commitment context used in eligibility. |
| Total charge | Sum of persisted charge lines. |
| Charge explanation | Rule ID, input, formula, rate, and amount for each component. |
| Snapshot identity | Rate-book snapshot used to reproduce the quote. |

### Cadence

| Activity | Implemented frequency | Primary purpose |
| :---- | :---- | :---- |
| Private-fleet allocation | Every scenario solve | Use feasible internal capacity first. |
| Carrier eligibility and rating | Every solve with eligible overflow | Source remaining stops using published commercial rules. |
| Charge audit | On demand in Analyze | Explain the selected carrier cost. |
| Contract-capacity review | On demand in Rates | Review capacity and commitment assumptions before scenario use. |
| Historical result review | On demand | Reproduce the commercial assumptions used by a prior scenario. |

## Governed Carrier Rate Contract Management

### Problem Being Solved and Current Technological Limitations

Carrier rates are frequently distributed across workbooks, email attachments, and TMS configuration screens. Analysts may know a total quote but not which lane, fuel, stop, accessorial, tier, minimum, or commitment rule created it. Editing a live rate in place can also change the economics of an old scenario without warning.

The Rates workspace treats contracts as governed, effective-dated version sets. Analysts create a contract or clone a version into a draft, edit five rule families, validate the draft, test a quote, and publish an immutable version for scenario use.

### Governed Rule Families

| Rule family | Implemented coverage |
| :---- | :---- |
| Lane rates | Origin, destination, priority, flat rate, mileage rate, stop rate, included stops, minimum, and mileage rounding. |
| Fuel schedules | Effective-dated percentage and charge basis. |
| Accessorials | Unique code, charge type, rate, name, and description. |
| Volume tiers | Ordered lower and upper bounds with adjustment type and value. |
| Capacity commitments | Period, unit, committed quantity, available capacity, utilization, and shortfall / overage rates. |

### Jobs-To-Be-Done (JTBD)

| Layer | Rate-management JTBD | Implemented product capability |
| :---- | :---- | :---- |
| Inventory contracts | See available carriers, contracts, versions, coverage, and capacity. | Rates presents contract inventory plus coverage and capacity KPI summaries. |
| Start commercial terms | Create a contract or revise an existing one without mutating history. | Analysts can create a contract and clone an existing version into a new draft. |
| Author rules | Represent the commercial logic required by a transportation quote. | Structured editors cover lanes, fuel, accessorials, tiers, and capacity commitments. |
| Save work in progress | Preserve incomplete changes without making them available to scenarios. | Draft versions can be saved and revisited. |
| Validate publication | Detect structural, date, identifier, and economic conflicts. | Server-side publication validation returns blocking errors and warnings. |
| Test a quote | Confirm how rules combine before publication. | A transparent quote tester exposes eligibility, matched rules, formulas, and line-item amounts. |
| Publish safely | Make approved terms available while protecting historical evidence. | Published versions are immutable; a new publication can end-date the prior effective version with an explicit warning. |
| Abandon a draft | Remove an unwanted unpublished revision. | Draft versions can be discarded without affecting published history. |
| Review history | Understand what was available for a past service date. | Contract detail retains version status, effective dates, change summary, and rule content. |

### Publication Controls

| Validation area | Implemented check |
| :---- | :---- |
| Version identity | Required version name and change summary. |
| Effective period | Required dates, valid start/end order, and overlap checks. |
| Lane coverage | At least one lane and unique origin-destination-priority combinations. |
| Rule identity | Rule IDs must be globally unique within the version payload. |
| Economics | Monetary and percentage rates cannot be negative. |
| Fuel | Fuel schedules must fall within version dates and cannot overlap. |
| Accessorials | Accessorial codes must be unique. |
| Volume tiers | Tiers must begin at zero and remain contiguous and non-overlapping. |
| Capacity | Commitment cannot exceed capacity; period and unit combinations must be unique. |
| Prior publication | Warn when publishing the new version will end-date the prior version. |

### Decision-Grade Quote Output

| Output | Meaning |
| :---- | :---- |
| Eligibility result | Whether the contract can rate the requested service date, lane, and capacity context. |
| Contract evidence | Carrier, contract, version, status, and effective period. |
| Matched rules | Exact lane, fuel, accessorial, tier, and commitment rule identifiers. |
| Formula evidence | Human-readable formula and input values used for each charge. |
| Charge ledger | Ordered charge lines and total quote. |
| Validation feedback | Blocking errors and non-blocking publication warnings. |

### Cadence

| Activity | Implemented frequency | Primary purpose |
| :---- | :---- | :---- |
| Contract inventory review | On demand | Check coverage, versions, and available capacity. |
| Draft editing | Event-driven around commercial changes | Prepare new contract terms without changing live versions. |
| Quote testing | During draft review and troubleshooting | Verify eligibility and charge construction. |
| Validation | On demand before publication; enforced at publish | Prevent invalid governed rules from becoming active. |
| Publication | Event-driven | Make an immutable effective-dated version available to scenario rating. |
| Version-history review | On demand | Reproduce the terms available on a historical service date. |

## Planning Input Stewardship

### Problem Being Solved and Current Technological Limitations

Optimization quality is bounded by the quality of its planning inputs. A corrected customer coordinate, fleet capacity, depot assignment, receiving window, wage, fixed cost, or service-time assumption can materially change route feasibility and economics. Direct edits to shared tables, however, create a different risk: partial updates, broken foreign keys, concurrent overwrites, and no way to preview the new baseline before other users see it.

The Inputs workspace provides a private, authenticated Lakebase editing session. Each user edits an isolated snapshot, validates the complete cross-table result, previews a reconstructed baseline, then atomically promotes or discards the session.

### Governed Input Domains

| Domain | Planning role |
| :---- | :---- |
| Orders | Delivery date/day, customer, depot, cases, and service demand. |
| Customers | Account identity, depot assignment, coordinates, customer tier, service time, and receiving windows. |
| Fleet | Vehicle / driver availability, depot, capacity, and operating limits. |
| Depots | Facility identity and coordinates. |
| Carriers | Carrier reference data required by rate contracts. |
| Cost parameters | Mileage, labor, overtime, fixed-vehicle, and related modeled cost assumptions. |
| Carriers | Carrier identity and active status used by sourcing and contract relationships. |
| Carrier contracts | Contract identity, carrier reference, effective dates, capacity, and summary rate fields. Detailed versioned rules are governed in the Rates workspace. |
| Operating parameters | Speed, circuity, duration, stop, service, and penalty assumptions used by planning logic. |
| Revenue parameters | Revenue assumptions used in scenario economics. |

### Jobs-To-Be-Done (JTBD)

| Layer | Input-stewardship JTBD | Implemented product capability |
| :---- | :---- | :---- |
| Isolate work | Make a set of related edits without exposing partial changes. | Opening the editor snapshots the current master rows into a session private to the authenticated principal. |
| Edit consistently | Insert, update, or delete rows across the supported domains. | Paginated typed editors use row-level version tokens and session-scoped mutations. |
| Prevent tab conflicts | Avoid silently overwriting a newer edit in another browser tab. | Row-version mismatch returns a conflict and requires reload. |
| Validate types and ranges | Reject malformed identifiers, coordinates, quantities, times, and costs. | Strict row models validate required text, coordinate ranges, positive and nonnegative numeric policies, and time formats. |
| Validate relationships | Ensure the edited dataset remains referentially coherent. | Cross-table checks verify carrier-contract, customer-depot, fleet-depot, order-customer, and order-depot relationships. |
| Preview operational effect | See whether the edited inputs reconstruct a sensible baseline. | Preview runs the baseline reconstruction against the session snapshot without committing it. |
| Protect shared master data | Detect if the source changed after the session began. | Commit checks source-row and master-version conflicts before promotion. |
| Promote atomically | Make the complete validated data version current or make no change. | A Lakebase transaction promotes the session and rebuilds baseline snapshots as one controlled commit workflow. |
| Preserve accountability | Retain who changed or completed a session and what happened. | Editor audit events record session lifecycle and mutations. |
| Clean up abandoned work | Prevent private drafts from accumulating indefinitely. | Sessions expire after the configured TTL, eight hours by default; session rows are removed while audit metadata is retained. |

### Validation Controls

| Validation area | Implemented check examples |
| :---- | :---- |
| Required fields | Required identifiers and text cannot be blank. |
| Geospatial inputs | Latitude and longitude must fall in valid ranges. |
| Demand and capacity | Demand, service time, fleet capacity, speed, and circuity fields must be positive where required. |
| Costs and penalties | Cost and penalty fields must be nonnegative; overtime multiplier must be at least 1. |
| Receiving windows | Values must use valid `HH:MM` time and end after start. |
| Carrier relationships | A rate contract must reference a carrier in the same proposed dataset. |
| Depot relationships | Customers and fleet must reference an existing depot. |
| Order relationships | An order must reference an existing customer and depot, and its depot must match the customer's depot. |
| Concurrency | Row and master versions must still match at mutation and commit time. |

### Decision-Grade Stewardship Record

| Output | Meaning |
| :---- | :---- |
| Session identity | Authenticated principal, session ID, status, and expiration. |
| Change summary | Inserted, updated, deleted, and unchanged row counts by entity. |
| Validation result | Blocking issues with entity, row, field, code, and message. |
| Baseline preview | Reconstructed route and KPI effect of the uncommitted dataset. |
| Conflict result | Row or source-master version that changed since snapshot. |
| Commit result | New promoted master version and rebuilt baseline snapshot. |
| Audit evidence | Timestamped session and row mutation events. |

### Cadence

| Activity | Implemented frequency | Primary purpose |
| :---- | :---- | :---- |
| Open isolated session | On demand | Begin a coherent planning-data change set. |
| Edit and save rows | Interactive | Build the proposed data version. |
| Validate | On demand and before commit | Identify type, policy, and relationship issues. |
| Preview baseline | On demand | Understand operational consequences before promotion. |
| Commit or discard | Event-driven | Atomically promote a valid version or abandon the draft. |
| Session expiry | Eight hours by default | Remove stale private working data while retaining audit evidence. |

## Cross-CUJ Operating Cadence

The current repository supports an event-driven planning loop. It contains the orchestration needed to refresh data and analytical assets, but it does not prescribe or configure a production schedule.

| Planning layer | Current trigger | Primary user outcome |
| :---- | :---- | :---- |
| Data generation / ingest | On-demand Databricks job | Populate source data for the planning model. |
| Medallion transformation | Job task after data generation | Produce standardized bronze, silver, and gold planning tables. |
| Baseline reconstruction | Job task or input-editor commit | Refresh the current route benchmark. |
| Scenario modeling | Interactive, event-driven | Evaluate a proposed network or operating change. |
| Optimization and carrier rating | Interactive solve or batch job | Produce route, allocation, cost, service, and diagnostic evidence. |
| Comparison review | After solve, on demand | Compare a scenario with the baseline or another scenario. |
| Rate publication | Event-driven | Activate governed commercial terms for future rating. |
| Metric-view refresh | End of the on-demand batch workflow | Publish certified analytical measures. |

An implementation can map these triggers to daily, weekly, monthly, or event-based business processes, but those production cadences are outside the current codebase.

## Databricks Implementation Mapping

| Product responsibility | Databricks / application implementation |
| :---- | :---- |
| Deployment | Databricks Asset Bundles deploy the app, Lakebase resources, Lakeflow pipeline, serverless SQL warehouse, job, Unity Catalog schema, volume, and permissions. |
| User experience | A custom React / Vite interface is served with a FastAPI backend as a Databricks App. |
| Batch orchestration | One Lakeflow Job runs data generation, medallion refresh, baseline reconstruction, scenario materialization, travel-matrix build, model registration and deployment, solving, comparison, metric publication, validation, and permission grants. |
| Batch data | Unity Catalog tables and a managed volume hold source, baseline, scenario, optimization, comparison, and analytical data. |
| Interactive state | Lakebase stores planning inputs, rate books, scenario definitions, run state and stages, results, editor sessions, and audit events. |
| Data preparation | Lakeflow declarative pipelines implement bronze, silver, and gold transformations. |
| Route optimization | OR-Tools CVRPTW is packaged as an MLflow PyFunc model, registered in Unity Catalog, and exposed for interactive use with Model Serving. |
| Road travel | A companion Valhalla Databricks App supplies directed truck-road matrices; the caller can disclose and use a Haversine/circuity fallback. |
| Analytical serving | A serverless SQL warehouse supports SQL access and five certified metric views. |
| Governance | Unity Catalog permissions, app-resource bindings, immutable rate versions, snapshots, concurrency controls, and audit records provide layered governance. |

### Certified Metric Views

| Metric view | Decision area |
| :---- | :---- |
| `mv_route_performance` | Routes, miles, and operating cost by scenario, depot, and day. |
| `mv_scenario_comparison` | Cost, distance, and impacted-customer deltas. |
| `mv_customer_service_impact` | Customer impact and average disruption score. |
| `mv_fleet_capacity_utilization` | Vehicle capacity, driver utilization, and overtime. |
| `mv_depot_network_health` | Missed windows, late minutes, and cases across the depot network. |

## Current Implementation Boundaries

The following boundaries are important when using this document as a product or demonstration definition:

| Area | Current implementation boundary |
| :---- | :---- |
| Product role | Decision support and scenario evidence; not a transportation execution, dispatch, or order-management system. |
| Source data | Synthetic generation is the default ingest. The pipeline is designed so generation can be replaced with enterprise tables, but those connectors are not implemented here. |
| Scheduling | The batch job has no configured recurring schedule. |
| Operating scope | Interactive optimization is primarily scoped to one depot and delivery day at a time. |
| Baseline method | Historical / as-run baseline reconstruction uses deterministic grouping; scenario comparison uses an optimized baseline for like-for-like solver comparisons. |
| Batch defaults | Some notebooks retain North Depot / Tuesday defaults even though the interactive APIs support depot-day parameters. |
| Workflow approvals | There is no multi-level scenario approval hierarchy or recommendation acceptance workflow. |
| Execution integration | There is no ERP / TMS write-back, carrier tender, dispatch, shipment tracking, or driver communication. |
| Carrier operations | The product models sourcing and cost; it does not confirm carrier acceptance or live capacity. |
| Recommendations | Diagnostic suggestions are planning guidance. The application does not autonomously apply the recommended change. |
| UI framework | The interface is custom React / FastAPI, not Databricks AppKit. |

These are deliberate current-state disclosures, not implied roadmap items.

## Repository Evidence Map

| Capability | Primary source locations |
| :---- | :---- |
| Product architecture and workflow | [`README.md`](README.md), [`databricks.yml`](databricks.yml), [`resources/jobs.yml`](resources/jobs.yml) |
| Analyze and comparison experience | [`src/pages/BaselinePage.tsx`](src/pages/BaselinePage.tsx), [`src/components/DualMap.tsx`](src/components/DualMap.tsx), [`src/components/KpiDeltaGrid.tsx`](src/components/KpiDeltaGrid.tsx), [`src/components/CustomerImpactTable.tsx`](src/components/CustomerImpactTable.tsx) |
| Scenario creation and run tracking | [`src/pages/ScenarioBuilderPage.tsx`](src/pages/ScenarioBuilderPage.tsx), [`src/components/CustomScenarioBuilder.tsx`](src/components/CustomScenarioBuilder.tsx), [`backend/routes/runs.py`](backend/routes/runs.py), [`backend/services/run_state.py`](backend/services/run_state.py) |
| Optimization and diagnostics | [`route_opt/solver/ortools_cvrptw.py`](route_opt/solver/ortools_cvrptw.py), [`route_opt/solver/problem.py`](route_opt/solver/problem.py), [`route_opt/solver/diagnostics.py`](route_opt/solver/diagnostics.py) |
| Transportation sourcing and rating | [`route_opt/transportation.py`](route_opt/transportation.py), [`route_opt/rates.py`](route_opt/rates.py), [`backend/services/rates.py`](backend/services/rates.py) |
| Rate governance | [`src/pages/RatesPage.tsx`](src/pages/RatesPage.tsx), [`src/pages/ContractDetailPage.tsx`](src/pages/ContractDetailPage.tsx), [`backend/routes/rates.py`](backend/routes/rates.py), [`backend/services/lakebase_store.py`](backend/services/lakebase_store.py) |
| Input stewardship | [`src/pages/DataEditorPage.tsx`](src/pages/DataEditorPage.tsx), [`backend/routes/data_editor.py`](backend/routes/data_editor.py), [`backend/services/ground_truth_store.py`](backend/services/ground_truth_store.py) |
| Lakebase persistence | [`backend/services/lakebase_migrations.py`](backend/services/lakebase_migrations.py), [`resources/lakebase.yml`](resources/lakebase.yml) |
| Analytical metrics | [`route_opt/metric_views.py`](route_opt/metric_views.py), [`notebooks/08_publish_metric_views.py`](notebooks/08_publish_metric_views.py), [`notebooks/09_validate_metrics.py`](notebooks/09_validate_metrics.py) |
