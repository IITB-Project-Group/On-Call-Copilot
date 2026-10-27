---
id: image-slow-load
title: Slow image loads
service: image
failure_family: image_slow_load
symptoms:
  - Product images load slowly or stall
  - Page rendering is delayed by image fetch latency
fix: Disable the imageSlowLoad feature flag after engineer approval
related_flag: imageSlowLoad
---

# Slow Image Loads

## Scope
Use this runbook when image retrieval latency degrades page rendering or storefront experience.

## Confirm the incident
1. Check image endpoint latency and client-side image load timings.
2. Correlate performance drops with product and listing pages.
3. Validate whether `imageSlowLoad` is enabled.

## Remediation
```yaml
action: set_flag
arguments:
  flag: imageSlowLoad
  value: false
expected_effect: Image load latency returns to normal and page rendering improves.
```

Run only after explicit approval.

## Verify recovery
Monitor image fetch time, page rendering time, and request success rate during the recovery window.

## Safety notes
- Distinguish image latency from CDN or browser issues before changing flags.
- Keep the affected page and underlying timing data in the incident record.
