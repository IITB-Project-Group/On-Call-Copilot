---
id: search-index-lag
title: Search index lag
service: search
failure_family: search_index_lag
symptoms:
  - Product search becomes stale or misses newly added inventory
  - Search results lag behind catalog updates
fix: Trigger a safe reindex or index refresh after approval
related_flag: null
---

# Search Index Lag

## Scope
Use this runbook when product search is stale because the search index is delayed or failing to keep up with catalog updates.

## Confirm the incident
1. Compare recent catalog updates to search result freshness.
2. Inspect search indexing queue length, lag, and failed index operations.
3. Confirm whether the issue is limited to one index shard or the whole search path.

## Remediation
Perform a controlled reindex or refresh only if evidence confirms stale index data and approval is in place.

## Verify recovery
Check that new product and catalog data appear in search results and that indexing lag returns to normal.

## Safety notes
- Search lag may look like catalog failure; confirm the index freshness before acting.
- Record the time window of stale results and the reindex action.
