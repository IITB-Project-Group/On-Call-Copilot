---
id: auth-token-refresh
title: Authentication token refresh issues
service: auth
failure_family: auth_token_refresh
symptoms:
  - User sessions are dropped or re-authentication loops appear
  - Token validation errors spike for active customers
fix: Refresh or rotate the token issuer configuration after approval
related_flag: null
---

# Authentication Token Refresh Issues

## Scope
Use this runbook when authentication and user session validation fail due to token refresh or issuer problems.

## Confirm the incident
1. Review auth service errors and failed token refresh attempts.
2. Correlate with customer session drop rates or 401/403 spikes.
3. Identify whether the issue is isolated to one issuer or shared across all sessions.

## Remediation
Apply a controlled issuer or configuration refresh only after confirming the root cause and gaining approval.

## Verify recovery
Confirm that token refresh succeeds, session validity returns to baseline, and customer-facing auth errors fall back to normal.

## Safety notes
- Do not reset user sessions broadly without confirming the cause.
- Keep the evidence for repeated refresh failures and the approved change in the incident record.
