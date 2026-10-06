# Contributing

Thank you for improving this accelerator. Start with [Getting Started](docs/GETTING_STARTED.md) and keep the default path runnable with synthetic data, Lakebase, local OR-Tools, and an approximate travel matrix.

## Before opening a change

1. Create a branch and keep your changes scoped. Never commit `.env`, credentials, a workspace host, personal profile, resource IDs, or generated deployment artifacts.
2. Run `npm run verify:fast` while developing and `npm run verify:full` before proposing a change. If your change touches deployment, run the setup doctor and bundle validation with an explicitly selected `--profile`.
3. Explain the behavior change, any data or schema migration, and how you verified it. Include a screenshot for visible UI changes.

Keep API changes aligned with `src/api/types.ts` and the FastAPI routes. Changes to durable Lakebase data need an idempotent numbered migration and a test covering upgrade from an existing schema. Preserve saved run identities and historical scenario results.

If a feature needs Model Serving, Valhalla, or additional Unity Catalog grants, keep it opt-in and document its resources in [Advanced Routing](docs/ADVANCED_ROUTING.md). In-process workers are suitable for an accelerator or workshop; durable production orchestration should use Lakeflow Jobs.

This project uses the [MIT License](LICENSE). Contributions are submitted under that license.
