---
id: ad-high-cpu
title: Ad service high CPU
service: ad
failure_family: ad_high_cpu
symptoms:
  - Ad service CPU saturates and response latency spikes
  - Ad requests begin timing out or being retried
fix: Disable the adHighCpu feature flag after engineer approval
related_flag: adHighCpu
---

# Ad Service High CPU

## Scope
Use this runbook when the ad service is saturating compute and degrading downstream user experience.

## Confirm the incident
1. Inspect service CPU and saturation metrics for the ad tier.
2. Correlate with app requests that depend on ad rendering.
3. Check whether the `adHighCpu` flag is enabled.

## Remediation
```yaml
action: set_flag
arguments:
  flag: adHighCpu
  value: false
expected_effect: CPU load drops and ad latency normalizes.
```

Approval is required before toggling the flag.

## Verify recovery
Confirm CPU returns to normal, latency falls back to baseline, and page load health recovers.

## Safety notes
- CPU saturation can appear as a broader storefront issue; verify the ad service before acting.
- Keep the CPU evidence and cure in the incident trace.
