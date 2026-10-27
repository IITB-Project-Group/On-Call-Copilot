---
id: pm-007
service: email
symptom: "Email service memory usage grew continuously and delivery latency rose sharply"
root_cause: "emailMemoryLeak enabled"
fix: "Disabled emailMemoryLeak flag after approval"
preconditions:
  - "Memory usage is steadily climbing in the email process"
  - "Notifications or emails fail or slow as memory pressure increases"
  - "Feature flag emailMemoryLeak is enabled"
lesson: "Memory leaks in the email service are likely when sustained heap growth matches the active flag and delivery health degrades."
---

# Email memory leak incident

## Summary
The email service memory footprint grew without recovery and degraded notification processing until the injected memory leak flag was disabled.

## Timeline
- Heap usage climbed continuously.
- Email delivery times increased and some sends failed.
- The active feature flag review showed `emailMemoryLeak`.
- Recovery followed the approved flag disable.

## Root cause
The `emailMemoryLeak` flag caused the service to leak memory.

## Fix
Set `emailMemoryLeak` to false and confirm memory remains stable and email delivery recovers.
