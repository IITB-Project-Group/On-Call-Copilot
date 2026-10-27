---
id: cart-failure
title: Cart service failures
service: cart
failure_family: cart_failure
symptoms:
  - Add-to-cart and checkout requests fail intermittently
  - Latency spikes and 5xx responses from cart service
fix: Disable the cartFailure feature flag after engineer approval
related_flag: cartFailure
---

# Cart Service Failures

## Scope
Use this runbook when requests involving cart operations fail or time out in the cart service.

## Confirm the incident
1. Identify the offending request path and affected user cohort.
2. Inspect traces to confirm failures originate in the cart service.
3. Check whether the cart service has increased latency or repeated errors.
4. Validate whether the `cartFailure` flag is enabled.

## Remediation
```yaml
action: set_flag
arguments:
  flag: cartFailure
  value: false
expected_effect: Cart requests recover and checkout flow resumes normally.
```

Approval is required before the change is applied.

## Verify recovery
Monitor cart latency, error rate, and downstream checkout status. Confirm the user-facing flow returns to baseline within the observation window.

## Safety notes
- Do not retry blindly while the cart is failing.
- Keep the original failing trace as evidence for the incident note.
- If the flag is not the cause, replan before acting.
