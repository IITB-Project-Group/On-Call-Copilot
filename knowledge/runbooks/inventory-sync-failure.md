---
id: inventory-sync-failure
title: Inventory sync failures
service: inventory
failure_family: inventory_sync_failure
symptoms:
  - Stock levels drift or remain stale during purchases
  - Inventory checks fail intermittently against the catalog
fix: Trigger a safe inventory sync retry or failover to the last known-good snapshot after approval
related_flag: null
---

# Inventory Sync Failures

## Scope
Use this runbook when inventory data is stale, inconsistent, or unavailable for order and fulfillment flows.

## Confirm the incident
1. Check whether inventory data is not updating after stock events.
2. Validate the upstream and downstream sync path for stock changes.
3. Confirm whether the issue affects one store, region, or the whole catalog.

## Remediation
Apply a controlled retry or revert to the last known-good inventory state only after the evidence is consistent and approval is received.

## Verify recovery
Monitor inventory consistency, order validation errors, and stock availability before closing the incident.

## Safety notes
- Inventory drift can cause sell-through errors; do not override product availability without evidence.
- Record the stale data window and the actions taken.
