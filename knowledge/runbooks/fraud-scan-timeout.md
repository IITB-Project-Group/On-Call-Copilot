---
id: fraud-scan-timeout
title: Fraud scan timeouts
service: fraud
failure_family: fraud_scan_timeout
symptoms:
  - Order approvals stall while fraud checks time out
  - Payment and checkout flows see delayed confirmations
fix: Short-circuit to a safe fallback review path after approval
related_flag: null
---

# Fraud Scan Timeouts

## Scope
Use this runbook when the fraud screening service times out and blocks order processing or review workflows.

## Confirm the incident
1. Inspect fraud service latency and timeout metrics.
2. Verify whether order confirmations are delayed specifically by fraud checks.
3. Check for upstream service degradation or queue latency.

## Remediation
If the fraud service is timing out without a clear application-side bug, route to a reviewed fallback policy or safe retry route only with approval.

## Verify recovery
Observe approval time, transaction success rate, and any backlog in the fraud queue before declaring the incident resolved.

## Safety notes
- Do not bypass fraud checks without a documented policy and explicit approval.
- Record which transactions were held or routed to fallback review.
