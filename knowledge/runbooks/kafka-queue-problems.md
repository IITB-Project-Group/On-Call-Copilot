---
id: kafka-queue-problems
title: Kafka queue problems
service: kafka
failure_family: kafka_queue_problems
symptoms:
  - Asynchronous tasks accumulate and fall behind
  - Queue lag rises and consumers error or stall
fix: Disable the kafkaQueueProblems feature flag after engineer approval
related_flag: kafkaQueueProblems
---

# Kafka Queue Problems

## Scope
Use this runbook when the event bus is dropping, stalling, or delaying messages that support asynchronous store actions.

## Confirm the incident
1. Inspect Kafka consumer lag, producer errors, and broker health.
2. Identify whether checkout, email, or recommendation flows are blocked by queue backlog.
3. Check for active `kafkaQueueProblems` injection.

## Remediation
```yaml
action: set_flag
arguments:
  flag: kafkaQueueProblems
  value: false
expected_effect: Queue lag drops and downstream workers recover.
```

Apply only after the engineer approves the exact action.

## Verify recovery
Observe queue lag, consumer throughput, and the affected downstream service error rate over the next observation window.

## Safety notes
- Queue issues can be transient; be careful not to restart services before confirming the queue health state.
- If data is backed up, document queue depth and expected backlog recovery.
