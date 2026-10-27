---
id: pm-008
service: image
symptom: "Product images loaded slowly and storefront pages showed delayed rendering"
root_cause: "imageSlowLoad enabled"
fix: "Disabled imageSlowLoad flag after approval"
preconditions:
  - "Image fetch latency is elevated and product pages render slowly"
  - "Image service responses are delayed in the request path"
  - "Feature flag imageSlowLoad is enabled"
lesson: "Slow image loads should be treated as a feature-flag issue when fetch latency and page rendering degradation are both present."
---

# Image latency incident

## Summary
The storefront rendered product pages slowly because image retrievals were delayed. Once the injected slow image flag was switched off, load time normalized.

## Timeline
- Product listing and detail pages slowed.
- Image response times climbed significantly.
- The flag review confirmed `imageSlowLoad`.
- The disable action restored page responsiveness.

## Root cause
The `imageSlowLoad` flag caused delayed image loads.

## Fix
Set `imageSlowLoad` to false and confirm image load latency falls back to the normal baseline.
