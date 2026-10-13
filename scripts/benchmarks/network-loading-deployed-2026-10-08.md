# Deployed network loading measurements — October 8, 2026

Deployed to the existing `route-scenario-modeling-dev` app using profile `DEFAULT`.
Deployment completed successfully; authenticated health returned HTTP 200.
Requests originate from the developer workstation and include HTTP transport and
response reading, using the same method as the earlier deployed measurements.

Context: all regions, all lane types, assigned flow, October 8–November 4;
default demand/capacity versions selected from the deployed options API.

| Request | Before deployed change | After deployed change | Response bytes before → after |
| --- | --- | --- | --- |
| Baseline planning context | 7.263 / 8.098 s | 0.296 / 0.284 / 0.277 s | 5,034,958 → 323 |
| Network map | 4.231 / 4.129 s | First after deployment: 5.629 s; cached: 0.658 / 0.505 s | 3,550,880 → 128,930 |

The first map request after deployment has an empty application overview cache.
The earlier measurements were repeated requests against a running application,
so they are not equivalent cold-start samples. The smaller response reduces
transport and serialization; it does not remove cold network data loading and
overview construction. Repeat map requests are approximately 7× faster, while
planning-context requests are approximately 27× faster by arithmetic means.

A full overview reference read returned 3,550,880 bytes in 1.002 s with the cache
populated. Its KPIs and facility data matched the compact map response exactly.
Default full API responses remain available; only the home-page request opts into
the compact projection. No solve was triggered by this measurement, and these
changes do not reduce large scenario snapshot persistence costs.
