---
id: pm-001
service: payment
symptom: "Checkout error rate exceeded 5% for 8 minutes and payment requests were failing"
root_cause: "paymentFailure enabled"
fix: "Disabled paymentFailure flag after approval"
preconditions:
  - "Checkout alert active for at least five minutes"
  - "Payment service traces show errors during failed checkouts"
  - "Feature flag paymentFailure is enabled"
lesson: "Payment-service errors are usually caused by the paymentFailure feature flag when trace evidence and flag state match."
---

# Payment flag incident

## Summary
A spike in checkout failures was traced to an injected payment service failure. The issue was confirmed by matching payment traces, the alert window, and the active feature flag.

## Timeline
- Alert reported checkout error rate above threshold.
- Payment traces showed request failures in the payment hop.
- Feature flag review showed `paymentFailure` enabled.
- The engineer approved the flag disable and recovery was verified.

## Root cause
The `paymentFailure` feature flag was enabled and caused payment requests to fail.

## Fix
Set `paymentFailure` to false, verify checkout success, and confirm payment service error rate returned to baseline.
