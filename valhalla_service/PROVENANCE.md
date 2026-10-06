# Source provenance

This directory is vendored into the route-scenario-modeling repository so a clean clone
contains the Valhalla runtime, tests, and regional deployment tooling required by
`scripts/deploy-valhalla-service` and `scripts/setup-valhalla-extract`.

It originated from:

- Repository: `https://github.com/josh-melton-db/databricks-valhalla-app-poc.git`
- Vendored base commit: `c244c9bc83cb928e1ce52f796d98e50d0a7d133c`

The original nested Git metadata is retained locally at
`/.databricks/valhalla-service-git-history/`. The parent repository already ignores
`.databricks/`, so this metadata cannot become a gitlink or enter a parent commit. To
inspect the original history against the vendored working tree from the parent root:

```bash
git \
  --git-dir="$PWD/.databricks/valhalla-service-git-history" \
  --work-tree="$PWD/valhalla_service" \
  log --oneline --all
```

Do not create a `valhalla_service/.git` file or move the metadata back before staging the
vendored source: Git would treat the directory as an embedded repository/gitlink instead
of ordinary parent files. Fresh clones intentionally receive the complete service source
and deployment tooling, but not this local historical metadata archive.
