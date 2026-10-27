---
id: product-catalog-failure
title: Product catalog failures
service: product-catalog
failure_family: product_catalog_failure
symptoms:
  - Product pages and pricing responses fail or return incomplete data
  - Catalog service latency spikes and timeouts
fix: Disable the productCatalogFailure feature flag after engineer approval
related_flag: productCatalogFailure
---

# Product Catalog Failures

## Scope
Use this runbook when catalog reads fail or product data is missing from the storefront.

## Confirm the incident
1. Inspect product page and cart requests for catalog dependency errors.
2. Trace the catalog dependency path and isolate the failing service calls.
3. Review recent catalog errors and confirm whether the injected flag is enabled.

## Remediation
```yaml
action: set_flag
arguments:
  flag: productCatalogFailure
  value: false
expected_effect: Product metadata loads normally and storefront errors drop.
```

Only apply with explicit engineer approval.

## Verify recovery
Check catalog request success rate, page rendering health, and cart/product page reliability before closing the incident.

## Safety notes
- Product failures may look like frontend issues; confirm the dependency chain before acting.
- Record which products or routes were affected in the status note.
