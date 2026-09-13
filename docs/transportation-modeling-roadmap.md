# Transportation Modeling Roadmap

This roadmap prioritizes extensions to the current deterministic route-scenario product. AI-agent capabilities are intentionally out of scope and can be layered in later.

## Prioritized use cases

1. **Rich operating constraints** — Model driver shifts and breaks, vehicle types and capacities, customer compatibility, route limits, dock capacity, calendars, and pickup-and-delivery dependencies so plans are operationally executable.
2. **Transportation choices** — Optimize whether demand should use the private fleet, overtime, an added vehicle, or an outsourced carrier based on cost, capacity, and service commitments.
3. **Rate and contract modeling** — Calculate transparent carrier costs from lane, mileage, stop, minimum-charge, fuel-surcharge, accessorial, volume-tier, capacity-commitment, and effective-date rules.
4. **Network design** — Evaluate facility openings, closures, and relocations; territory changes; customer-to-depot allocation; multi-depot balancing; and cross-dock options.
5. **Robustness analysis and stress testing** — Run repeated demand, travel-time, capacity, outage, and service-time shocks to measure cost distributions, failure probability, and network resilience.
6. **Demand planning** — Replace fixed inputs with forecasts, seasonality, daily variability, growth patterns, and demand uncertainty across a multi-day planning horizon.
7. **Plan-versus-actual learning** — Compare planned routes, travel times, service times, costs, and delivery outcomes with actual execution to expose bias and recalibrate model assumptions.
8. **Sustainability modeling** — Measure emissions and empty miles while evaluating alternative-fuel vehicles and explicit cost-versus-carbon tradeoffs.
9. **Operational replanning** — Ingest traffic, weather, breakdowns, late orders, and cancellations; preserve completed or committed work; and repair the remaining plan during execution.

## Recommended next product slice

Build **fleet-or-carrier optimization with realistic driver and vehicle constraints** by combining priorities 1–3. For each scenario, the model should choose among regular fleet capacity, overtime, an additional vehicle, outsourced service, or an unserved delivery, then explain the selected option through constraint utilization and an itemized cost breakdown.

Operational replanning remains last because it requires live event ingestion, order and vehicle state, dispatch workflows, and notifications in addition to optimization logic.
