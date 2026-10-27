---
id: pm-002
service: cart
symptom: "User could not add items to cart and checkout requests intermittently failed"
root_cause: "cartFailure enabled"
fix: "Disabled cartFailure flag after approval"
preconditions:
  - "Add-to-cart and cart API calls fail or timeout"
  - "Cart service traces show errors during request path"
  - "Feature flag cartFailure is enabled"
lesson: "Cart errors are strongly linked to the cartFailure flag when cart service traces and recent flag changes align."
---

# Cart flag incident

## Summary
A cart issue caused failed add-to-cart events and checkout interruptions. The cause was confirmed by matching the cart service error signature with the active injected flag.

## Timeline
- Latency and error rate rose for cart operations.
- The cart service returned 5xx errors for the user workflow.
- The feature flag review showed `cartFailure` enabled.
- The change was approved and immediately improved request reliability.

## Root cause
The `cartFailure` feature flag was active.

## Fix
Set `cartFailure` to false and verify cart and checkout metrics returned to normal.
