---
id: pm-003
service: product-catalog
symptom: "Catalog data missing from product pages and pricing endpoints were returning incomplete payloads"
root_cause: "productCatalogFailure enabled"
fix: "Disabled productCatalogFailure flag after approval"
preconditions:
  - "Product pages or pricing endpoints show missing data or timeouts"
  - "Catalog service is the failing dependency"
  - "Feature flag productCatalogFailure is enabled"
lesson: "Catalog read failures usually resolve when the productCatalogFailure flag is disabled and the catalog dependency is confirmed."
---

# Product catalog incident

## Summary
The storefront made product requests that returned incomplete or broken catalog responses. The issue resolved once the injected catalog failure flag was removed.

## Timeline
- Product and pricing requests failed.
- Catalog service traces showed missing or invalid responses.
- The active flag review confirmed `productCatalogFailure`.
- The flag was disabled and page health returned to normal.

## Root cause
A feature-flag injected catalog failure led to the broken data path.

## Fix
Set `productCatalogFailure` to false and confirm catalog data and product pages recover.
