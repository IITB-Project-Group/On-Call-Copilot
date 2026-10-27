---
id: recommendation-cache-failure
title: Recommendation cache failures
service: recommendation
failure_family: recommendation_cache_failure
symptoms:
  - Product recommendations are stale, empty, or return errors
  - Cache-related latency and eviction spikes
fix: Disable the recommendationCacheFailure feature flag after engineer approval
related_flag: recommendationCacheFailure
---

# Recommendation Cache Failures

## Scope
Use this runbook when the recommendation service is serving stale or broken data because cache health is degraded.

## Confirm the incident
1. Inspect recommendation requests and cache metrics for failed reads or large eviction rates.
2. Verify whether the recommendation path is failing before or after cache access.
3. Check whether `recommendationCacheFailure` is active.

## Remediation
```yaml
action: set_flag
arguments:
  flag: recommendationCacheFailure
  value: false
expected_effect: Recommendations recover, caching stabilizes, and stale results disappear.
```

Proceed only after approval.

## Verify recovery
Check recommendation response quality, cache hit rate, and storefront behavior for the next observation window.

## Safety notes
- A cache issue can mimic a recommendation service outage; confirm the exact failing layer.
- Keep the diagnosis and verification results in the trace.
