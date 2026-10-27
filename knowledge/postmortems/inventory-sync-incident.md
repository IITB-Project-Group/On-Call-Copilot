---
id: pm-009
service: inventory
symptom: "Stock levels were stale across purchase flows and order validation reported unavailable products"
root_cause: "inventory sync lag and stale snapshot"
fix: "Triggered a controlled inventory sync retry and restored the last known-good snapshot"
preconditions:
  - "Stock values no longer match recent updates"
  - "Order validation or purchasing is failing because inventory is stale"
  - "A sync problem or stale snapshot is confirmed in the inventory path"
lesson: "Inventory drift is usually a data consistency issue when order validation and stock counters disagree across the same window."
---

# Inventory sync incident

## Summary
Inventory counts drifted and an order validation path saw outdated stock values. A controlled sync retry and snapshot restore fixed the inconsistency.

## Timeline
- Inventory counts mismatched real stock changes.
- Product availability and order validation began to fail.
- A synchronization and snapshot review confirmed the stale path.
- Recovery was verified after a controlled re-sync.

## Root cause
The stock data path had drifted and the last known-good snapshot needed to be restored.

## Fix
Trigger a safe inventory sync retry and restore the last good snapshot after approval.
