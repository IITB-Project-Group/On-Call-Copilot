---
id: shipping-delay
title: Shipping delay anomalies
service: shipping
failure_family: shipping_delay
symptoms:
  - Order shipping estimates worsen unexpectedly
  - Fulfillment responses are delayed or inconsistent
fix: Restart the shipping worker or fall back to cached dispatch rules after approval
related_flag: null
---

# Shipping Delay Anomalies

## Scope
Use this runbook when shipping service behavior is slower than expected or fulfillment times degrade in a way that affects order completion.

## Confirm the incident
1. Inspect shipping service latency and fulfillment queue depth.
2. Correlate with recent order volume and dependency call failures.
3. Check for upstream service errors or queue saturation.

## Remediation
Use a minimal, approved operational control such as restarting the shipping worker or switching to a safe fallback behavior, if the evidence supports it.

## Verify recovery
Confirm that fulfillment response time returns to baseline and backlogged orders are drained without worsening failure rate.

## Safety notes
- Shipping delays may be a downstream effect of broader queue issues; trace the dependency chain first.
- Do not bypass inventory or order validation logic unless the runbooks explicitly allow it.
