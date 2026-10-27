---
id: recommendation-ranking-degradation
title: Recommendation ranking degradation
service: recommendation
failure_family: recommendation_ranking_degradation
symptoms:
  - Recommendations are low quality, irrelevant, or stale
  - CTR drops while recommendation service itself remains available
fix: Restore the ranking model or roll back the last recommendation model change after approval
related_flag: null
---

# Recommendation Ranking Degradation

## Scope
Use this runbook when the recommendation pipeline stays operational but ranking quality degrades enough to affect conversion.

## Confirm the incident
1. Compare ranking quality metrics against the recent model or feature update.
2. Inspect recommendation output quality and CTR trends.
3. Validate whether the service is healthy but ranking logic has regressed.

## Remediation
Roll back the last safe deployment or restore the last known-good model only after evidence supports the model regression and approval is granted.

## Verify recovery
Check CTR, recommendation quality, and user engagement before closing the incident.

## Safety notes
- This issue is not the same as cache failure or service outage; confirm the exact cause before rollback.
- Keep the model version or deployment evidence in the incident log.
