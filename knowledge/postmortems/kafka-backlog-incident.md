---
id: pm-005
service: kafka
symptom: "Asynchronous jobs accumulated and downstream email and notification tasks were delayed"
root_cause: "kafkaQueueProblems enabled"
fix: "Disabled kafkaQueueProblems flag after approval"
preconditions:
  - "Kafka consumer lag is elevated or queueing is growing"
  - "Downstream services are falling behind due to blocked events"
  - "Feature flag kafkaQueueProblems is enabled"
lesson: "Kafka queue issues are likely when consumer lag and asynchronous job backlog both rise together."
---

# Kafka backlog incident

## Summary
The queue was blocked and downstream jobs stopped processing promptly. The fault was tied to an injected queue problem and was resolved by disabling the flag.

## Timeline
- Consumer lag increased and backlog grew.
- Email and recommendation tasks slowed or failed.
- The active feature flag review showed `kafkaQueueProblems`.
- The queue recovered after the flag was disabled.

## Root cause
The `kafkaQueueProblems` flag caused backlog and lag.

## Fix
Set `kafkaQueueProblems` to false and verify queue depth begins to normalize.
