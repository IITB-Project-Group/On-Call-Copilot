# Memory policy

## Purpose
The memory store stores past incidents and lessons and provides retrieval results only when the evidence supports a match. The retrieval layer must not apply a past lesson simply because the service or symptom looks similar.

## Required fields
Every incident and lesson record must include:
- service
- symptom summary
- root cause or failure family
- fix or remediation
- evidence references
- preconditions for use

## Matching rule
A lesson is considered applicable only when all of the lesson preconditions match the current incident.

A lesson is rejected when any of the following are true:
- Service mismatch
- Failure family mismatch
- Signal pattern mismatch (for example, CPU saturation vs transaction errors)
- The incident is still under active investigation and the evidence is insufficient

## Retrieval behavior
1. Retrieve candidate runbooks by service, symptom and failure family.
2. Retrieve similar incident records by metadata and evidence similarity.
3. Rank lessons by evidence match and precondition compatibility.
4. Return the candidate with a reason string describing why it matched or was rejected.
5. Require a human review if a lesson would be applied to a new incident without a direct match.

## Misleading lesson guardrail
A lesson is considered misleading when it matches the service or symptom superficially but contradicts the real evidence. In those cases, the memory system must store the mismatch and prevent automatic application. The system should prefer a no-match result over a weak match.

## Retention
Lessons are frozen after a review step and only updated through a governed change process. Unreviewed or contradictory lessons must be excluded from held-out evaluation runs.
