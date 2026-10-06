# Demo script

This presentation tells one planning story in about 12 minutes. It emphasizes four ideas:

1. Generate governed planning data in the Lakehouse.
2. Use Lakebase for interactive operational state.
3. Build a Databricks App over both.
4. Add optimization services behind stable interfaces.

## Before the session

```bash
npm run verify:fast
```

Deploy the chosen configuration with `scripts/deploy-demo --config configs/deployment/dev-enhanced.json --profile DEFAULT --target dev`. Confirm the readiness page shows the expected Lakebase, warehouse, solver, and validated Texas routing coverage. Use a fixed `DEMO_DATE_ANCHOR` if the presentation requires a fixed calendar.

Click the **As of [date]** button and confirm the reset before presenting. This clears prior network scenarios, runs, demand changes, and depot plans; restores the generated original baseline; and starts solver endpoint warm-up in the background. Wait for warm-up to complete before the route demonstration. An active optimization must finish before reset can proceed. The minimal configuration skips remote solver warm-up.

## 1. Frame the architecture — 2 minutes

Show the architecture diagram and explain the responsibility of each layer:

- Unity Catalog holds governed planning inputs and analytical outputs.
- Lakebase holds scenarios, edits, runs, and decisions users create interactively.
- React and FastAPI form the Databricks App experience.
- The solver and travel matrix are replaceable services.

The minimal configuration uses local OR-Tools and approximate travel. The enhanced DEFAULT configuration uses Model Serving for depot solves, Valhalla truck matrices for validated Texas coverage, and labeled approximate matrices elsewhere. Network optimization uses the separate min-cost-flow optimizer.

## 2. Inspect the network — 2 minutes

Open the network page. Point out facilities, demand, capacity, baseline assignments, and the data-as-of date. Select a region or depot and explain that this view comes from canonical planning inputs.

Ask: “Where is the network under pressure, and what change should we test?”

## 3. Create and solve a scenario — 3 minutes

Select TOLA, open the baseline, and create an editable copy. Add a tariff rule with Mexico as the origin and United States as the destination, effective for the full service horizon. Demo **$0.10/case** first, then **$5/case** in a separate copy of the same baseline. The generated baseline includes Monterrey-to-Dallas and Monterrey-to-San Antonio shipments with domestic alternatives. Keep the same demand, capacity versions, and service horizon for both scenarios.

Run the scenario. Show the durable run identity and status. Compare cross-border assigned cases, tariff cost, domestic linehaul, and unmet demand. Raising tariffs makes the foreign corridor less attractive; domestic capacity and other constraints still determine whether all cross-border shipments can disappear. Check the deployment verification report for the tariff values and observed flows used in the tested demo.

DEFAULT dev acceptance on 2026-10-05 used a one-day TOLA horizon: cross-border
assigned cases were **3,761** without tariffs, **1,791** with **$0.10/case**, and
**zero** with **$5/case**. Use the same horizon and frozen input versions for a
comparable demonstration; these counts are evidence for the generated demo,
not a guarantee for other data or horizons.

## 4. Drill into a depot — 2 minutes

Open Dallas or San Antonio from the solved network. The immediate service date solves automatically; the calendar in the routes header selects later dates for lazy evaluation. Inspect routes and stops. Open **Scenarios** to add deliveries, move the facility, change a delivery time window, or adjust drivers and route limits. This tab contains constraint editors. Run the named scenario to return to **Depot** for a side-by-side dated comparison. Result execution metadata remains available in the API for verifying Model Serving and Texas Valhalla coverage; execution paragraphs are omitted from the presentation UI.

Keep the distinction clear: network planning chooses assignments; depot routing builds the daily vehicle plan.

## Optional shortage-relief story

Use a three-day horizon to distinguish **Available supply (%)** from **Handling capacity (%)**. Supply is generated daily DC stock available for dispatch; handling is daily throughput at a DC or depot. A setting of100% means normal published availability, not100% utilization. Values above100% simulate extra stock or extra throughput; they do not add a physical facility.

For a stock shortage, reduce a DC's available supply while leaving its handling capacity normal. Open the shortage action and request replenishment from a donor DC. An AIR shipment consumes donor stock and handling, arrives on a later day, and still respects destination throughput. Inspect its assigned cases, arrival date, cost, and the change in dated unmet demand. An unused request is not evidence of relief: lane limits, arrival timing, alternative direct service, or donor constraints may make it unnecessary or infeasible.

For a processing bottleneck, reduce handling capacity. Replenishing that facility cannot restore its processing ability. Use permitted direct shipments from another DC to the affected depot, or release customer assignments for another depot to serve. The solver still respects donor stock, handling, transportation, and delivery eligibility.

Depot fill shows unmet demand at the target: red at 10% or more unmet, yellow for any smaller shortage, and green for fully served. DC squares are blue; their tooltips roll up displayed child depots. Lane color shows capacity utilization (green below 95%, yellow 95–100%, red above 100%), and thickness shows shipment volume. The network map shows flat linehaul connections and express AIR arcs; customer delivery and local market lanes are omitted. Zero-volume shipments disappear. AIR uses elevated arcs. Exact values and provenance appear in facility details. Depot supply is incoming flow rather than a separate independent stock source. Apply or open the newly solved flow to view the selected scenario; pinned historical runs remain immutable.

Daily availability is a simple planning input, not a perpetual inventory ledger: normal daily stock does not accumulate between horizons. AIR inventory is carried only within its solved horizon. Reset restores normal generated inputs and removes prior scenarios.

## 5. Compare and persist — 2 minutes

Open the comparison view. Contrast the scenario with the same frozen baseline and rate inputs. Review customer impact and operational tradeoffs, then persist or propose the decision.

Reload or revisit history to show that the scenario, run, and decision live in Lakebase rather than browser state.

## 6. Close — 1 minute

Return to the complete loop:

> inspect network → create scenario → solve → drill into depot → compare → persist decision

Close with the adoption path: reuse the generator or optimizer, connect real governed inputs, add Lakebase for collaboration, and introduce road or managed compute services when accuracy and scale require them.

## Avoid during the main presentation

Skip tours of every scenario lever, notebook, and infrastructure resource. Keep provisioning history, coverage builds, endpoint operations, and migration internals for follow-up questions. The coherent business loop is the demonstration.
