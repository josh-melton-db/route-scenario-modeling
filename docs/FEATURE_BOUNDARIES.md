# Feature boundaries

This repository is a runnable planning accelerator. Its default path uses synthetic data, Lakebase, a local OR-Tools solver, and an approximate travel matrix. The approximation is labeled in results and should not be presented as road-network travel time.

## Supported in the default path

- Inspect a synthetic network, edit a scenario, run network and depot planning, compare results, and persist a decision.
- Store scenarios, overrides, run identities, results, and audit state in Lakebase.
- Use the React interface through the FastAPI contract, including readiness, loading, empty, and error states.
- Reuse the Python optimization and synthetic generation packages independently of the App.

## Opt-in integrations

- Unity Catalog data and Lakeflow resources for governed analytical inputs.
- Model Serving for remote solver execution.
- Valhalla for validated, directed road matrices. The service, tiles, and coverage artifact are maintained separately.

## Explicit limits

- Approximate travel estimates are for development and demonstrations, not dispatch or commercial routing decisions.
- The dated depot adapter rejects carrier fallback/contracts, required equipment matching, and explicit shift-clock or route-start constraints. It reports unsupported inputs rather than silently dropping them.
- The demo's reassignment eligibility is a deterministic nearby/same-region rule, not a customer territory policy.
- In-process workers and recovery are accelerator-grade. Use Lakeflow Jobs and operational monitoring for production scale and reliability.
- The synthetic data and cost model illustrate behavior; validate real data quality, tariff logic, service policies, permissions, and performance before operational use.
