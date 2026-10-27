---
id: email-memory-leak
title: Email service memory leak
service: email
failure_family: email_memory_leak
symptoms:
  - Email service memory growth continues over time
  - Email sends fail or respond with latency increases
fix: Disable the emailMemoryLeak feature flag after engineer approval
related_flag: emailMemoryLeak
---

# Email Service Memory Leak

## Scope
Use this runbook when memory usage in the email service is trending upward and reaches operational limits.

## Confirm the incident
1. Check process memory and heap growth in the email service.
2. Correlate with recent bulk email or notification traffic.
3. Validate whether `emailMemoryLeak` is active.

## Remediation
```yaml
action: set_flag
arguments:
  flag: emailMemoryLeak
  value: false
expected_effect: Memory growth stabilizes and email delivery recovers.
```

Only apply the action with human approval.

## Verify recovery
Observe memory usage, delivery success rate, and worker health after the change.

## Safety notes
- Memory leak symptoms can resemble general overload; confirm process growth before acting.
- Consider the impact on order confirmation and shipping notifications.
