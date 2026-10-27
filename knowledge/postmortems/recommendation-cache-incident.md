---
id: pm-004
service: recommendation
symptom: "Recommendation responses were stale, empty, or failed under high traffic"
root_cause: "recommendationCacheFailure enabled"
fix: "Disabled recommendationCacheFailure flag after approval"
preconditions:
  - "Recommendation responses are stale or empty"
  - "Cache-related errors or evictions spike"
  - "Feature flag recommendationCacheFailure is enabled"
lesson: "Recommendation cache degradation is recoverable by disabling the active cache failure flag when the cache is the failing component."
---

# Recommendation cache incident

## Summary
The recommendation engine served stale or invalid suggestions after the cache layer failed. The fix was to disable the injected cache failure flag and monitor cache health.

## Timeline
- Recommendation traffic dropped in quality and availability.
- Product pages had empty or stale recommendations.
- Cache-specific errors aligned with the active flag.
- Recovery was confirmed after the flag was disabled.

## Root cause
The `recommendationCacheFailure` flag caused the recommendation cache to fail.

## Fix
Set `recommendationCacheFailure` to false and verify recommendation quality returned to baseline.
