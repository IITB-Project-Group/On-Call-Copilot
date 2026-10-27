---
id: checkout-session-corruption
title: Checkout session corruption
service: checkout
failure_family: checkout_session_corruption
symptoms:
  - Shopping sessions reset unexpectedly during checkout
  - Customers lose cart or payment state mid-flow
fix: Recreate or rotate the broken checkout session safely after approval
related_flag: null
---

# Checkout Session Corruption

## Scope
Use this runbook when checkout sessions are inconsistent, stale, or invalid at critical points of the purchase flow.

## Confirm the incident
1. Inspect checkout session data and token validity.
2. Correlate with customer error patterns and session resets in logs.
3. Determine whether corruption is isolated to certain customer journeys or a broader session store issue.

## Remediation
Rotate or recreate the broken checkout session only through the allow-listed operational flow after approval.

## Verify recovery
Monitor checkout completion rate, session validity, and payment authorization success after the action.

## Safety notes
- Do not clear sessions broadly without confirming the session corruption pattern.
- Keep the evidence for session reset and verification in the incident record.
