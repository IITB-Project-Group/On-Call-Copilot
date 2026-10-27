---
id: pm-010
service: ad
symptom: "Checkout error rate remained above 5% and payment traces showed failures"
root_cause: "paymentFailure enabled"
fix: "Disabled paymentFailure flag after approval"
preconditions:
  - "Payment traces contain errors and alert is active"
  - "The responsible fault is in the payment path"
  - "There is no evidence of CPU saturation in the ad service"
lesson: "A prior ad-high-cpu lesson should be rejected when the evidence shows payment-service errors and no ad CPU saturation."
rejected_when:
  - "Ad CPU is normal while payment traces fail"
  - "The alert is caused by payment path errors rather than ad resource exhaustion"
---

# Misleading lesson case

## Summary
This postmortem intentionally captures a case where a stale or superficially similar lesson would be wrong. The ad-high-CPU lesson appears relevant because there is a latency issue, but the real evidence shows the payment service is failing.

## Timeline
- Checkout error rate peaked and the alert fired.
- Payment traces showed failures and no persistent ad CPU saturation.
- The wrong lesson about ad high CPU was retrieved but rejected because the service-level evidence contradicted the preconditions.
- The correct fix was to disable `paymentFailure`.

## Root cause
The payment service had the injected failure, not the ad service.

## Fix
Apply the payment failure fix and ignore the misleading ad-CPU lesson because its preconditions do not match the evidence.
