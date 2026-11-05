# OnCall Copilot: Current Status and Integration Gaps

Assessment date: 5 November 2026.

## Executive summary

The project has a monitored shop, an incident console, telemetry adapters, a
substantial knowledge-retrieval component, incident-memory functions, and safety
controls. The main remaining work is the integrated copilot that investigates an
incident, proposes an evidence-backed fix, obtains approval, verifies recovery,
and produces a reviewed postmortem.

The first completion milestone should be:

**Payment alert -> supported diagnosis -> exact approval -> flag change ->
verified recovery -> reviewed incident record.**

This assessment is based on repository code and the local environment reported
by the project owner. It does not independently verify the running deployment,
test results, generated retrieval index, or the original capstone PDF. Scope
references come from the repository's root README, which identifies itself as
the capstone build contract.

The root README's statement that runbooks and agents are still to be built is
partly outdated: knowledge retrieval and incident memory are substantially
implemented, while the agent packages remain mostly placeholders.

## 1. Current implementation

| Area | Available capability | Integration status |
| --- | --- | --- |
| Demo infrastructure | `up.sh`, `down.sh`, and Kubernetes configuration for the Astronomy Shop and incident API. | The project owner reports the shop and supporting pods running locally. |
| Alerting | `ServiceErrorRateHigh`, using a five-minute error-rate window and an additional one-minute pending period. | Alertmanager is configured to feed the incident API. |
| Incident API | Webhook, incident list/detail, decisions, health, metrics, and SQLite storage. | Connected to the console and payment approval path. |
| Incident console | Open/closed views, streamed incident snapshots, editable notes, approve/reject controls, and confirmation-code input. | Shows stored state, not a full investigation timeline. |
| Telemetry | PromQL, logs, traces, flag-state inspection, service error/request rates, p95 latency, and metric discovery. | Callable adapters exist; the live webhook does not invoke the investigation that uses them. |
| Knowledge corpus | 15 runbooks and 10 seed postmortems, including a misleading-lesson example. | Available to retrieval. |
| Retrieval | Metadata-preserving ingestion/chunking, BM25, semantic search, Chroma, rank fusion, query rewriting, reranking, and tool adapters. | Callable from the payment investigation, but not wired into live incident intake. |
| Incident memory | SQLite save, semantic search, and lesson applicability checks. | Not connected to the console's completion path. |
| Payment investigation | Telemetry reads, knowledge retrieval, payment hypothesis, and dry-run action proposal. | Implemented separately from the active API alert/approval path. |
| Flag remediation | Read/write a selected flag variant and check that flagd serves it. | Live approval is wired specifically to disable `paymentFailure`. |
| Safety | Input/output guardrails, redaction, approval service, command binding, hooks, budgets, loop limits, and kill switch. | Webhook screening and the payment write are integrated; investigation-wide enforcement is not. |
| CI | Lint/format, Python tests with coverage, API image build, and guardrail/API-security workflow. | Definitions exist; there is no full incident evaluation gate. |

### Local environment reported by the owner

| Surface | URL |
| --- | --- |
| Astronomy Shop | http://localhost:8080/ |
| Grafana | http://localhost:8080/grafana/ |
| Jaeger | http://localhost:8080/jaeger/ui/ |
| Feature flags | http://localhost:8080/feature |
| Load generator | http://localhost:8080/loadgen/ |
| Incident console | http://localhost:8000/ |
| Prometheus | http://localhost:9090/ |
| OpenSearch | http://localhost:9200/ |
| Flag configuration | http://localhost:4000/api/read |

Running pods establish infrastructure availability, not completion of the agent
workflow. A deployed image can also differ from the code inspected here.

### Component qualifications

- `recent_changes()` currently lists flags that are not off. It is not a
  timestamped change history and does not provide deployment history.
- The knowledge README reports a previously built persistent index and a
  successful retrieval smoke test. Availability of that index, dependencies,
  credentials, and provider access in the current deployment is not established.
- Incident memory records service, symptom, root cause, fix, lesson,
  preconditions, failure family, and reviewer. Retrieved lessons can be applied
  or rejected according to applicability conditions.
- Safety functions and hooks exist beyond the live path. Their presence does
  not establish that every telemetry, retrieval, or model call uses them.

## 2. Current live incident path

The API implementation follows this sequence:

```text
Alertmanager webhook
  -> screen incoming alert
  -> create/deduplicate SQLite incident
  -> for payment/checkout, create predefined payment action proposal
  -> display incident and approval information
  -> engineer approves with confirmation code
  -> guarded paymentFailure-off action
  -> record approval and classify incident as closed
```

The safety gate uses a predefined payment diagnosis and plan. It does not first
invoke `run_payment_incident()` to inspect telemetry, confirm flag state, retrieve
a runbook, and establish the cause.

After approval, the flag tool checks that flagd serves the requested variant.
The API does not invoke `verify_payment_incident()` in this path. An approved
incident is classified as closed without demonstrated service recovery.

**Approval, successful configuration change, and verified recovery must be
distinct events.**

The console also classifies rejected incidents as closed. Workflow state and
human decision should be represented separately so rejection is not confused
with operational resolution.

## 3. Existing components that need integration

| Component | Required connection |
| --- | --- |
| `run_payment_incident()` | Start investigation for relevant incidents outside the immediate webhook response and persist findings. |
| Telemetry clients | Use a shared guarded executor and attach results to incident evidence. |
| Runbook retrieval | Show guidance and citations and use them to justify the action. |
| Lesson applicability | Show considered, applied, and rejected lessons with reasons. |
| Approval service | Submit the actual evidence-backed plan, not the predefined payment plan. |
| `verify_payment_incident()` | Invoke after remediation within a timed observation process and persist the outcome. |
| Recovery validators | Enforce thresholds and sustained observations rather than equating a successful write with recovery. |
| Memory functions | Save reviewed incidents after postmortem completion and retrieve them in later investigations. |
| Safety hooks | Maintain one incident-wide budget/execution state across tools, models, actions, and replans. |
| Metrics | Record actual diagnosis/recovery durations, tool calls, cost, and rollbacks. |

Shared contracts also need alignment. The graph's action proposal uses a flag
`variant`, while the safety plan uses an `enabled` argument. Both must agree on
the exact executable action, captured previous state, expected effect,
verification criteria, and rollback.

## 4. Remaining implementation

### Incident commander and durable workflow

Implement an explicit incident lifecycle:

```text
Received -> Triaging -> Investigating -> Awaiting approval
         -> Remediating -> Verifying -> Resolved
                                    -> Rollback/Replan
```

Persist hypotheses, evidence identifiers, action proposals, approvals,
observations, and transitions. Resume safely after interruption without
repeating executed actions. The current incident schema mainly represents
alerts, notes, and decisions rather than this full lifecycle.

### Agent behavior

The `agents/` packages are mostly placeholders. Declaring diagnosis read tools
does not implement parallel diagnosis.

| Agent | Behavior to implement |
| --- | --- |
| Triage | Identify affected services, customer impact, severity, and scope. |
| Diagnosis | Test competing hypotheses and return ranked, evidence-backed causes within a budget. |
| Runbook | Retrieve guidance and distinguish applicable lessons from misleading ones. |
| Remediation | Execute approved actions, observe effects, and follow rollback/failure paths. |
| Communications | Draft cited status updates and postmortems from the recorded timeline. |
| Memory/reflection | Extract conditional lessons after review and support development-time improvement. |

The payment function is a useful deterministic initial slice, not the complete
multi-agent planning system. The required demonstration of a wrong first
hypothesis followed by evidence-driven replanning still needs implementation.

### Fault and action coverage

The inspected graph explicitly supports `paymentFailure` only. Other faults,
including `aiRunawayAgent`, need evidence collection, diagnosis, applicable
runbooks, safe action selection, and verification criteria.

A generic flag writer exists, but it is not a general approved action executor.
Restart, scale, and operational rollback adapters remain to be implemented if
retained in the final build scope.

### Recovery, rollback, and replanning

The current payment verifier performs one error-ratio read. The integrated
workflow needs a defined observation window, sustained recovery criteria,
handling of missing telemetry or insufficient traffic, and a bounded
rollback/replanning path.

The five-minute metric window retains pre-fix failures, so recovery need not be
visible immediately after a flag change. Capture the actual pre-action state:
the predefined rollback assumes the flag was enabled rather than preserving
its exact previous variant.

### Communications and reviewed learning

Implement a recorded timeline, evidence citations, human review of status and
postmortem drafts, and validated memory writes. Existing note editing is not
equivalent to this workflow. External status publication needs approval.

Implement the Reflexion development loop: compare investigations with injected
ground truth, propose lessons with preconditions, review them, and freeze the
lesson set before held-out evaluation.

### Evaluation

`eval/cases.py` returns an empty list. Safety scoring helpers exist, but there is
no integrated incident-evaluation runner.

The repository contract calls for about 60 incidents covering fault variants,
noisy alerts, and simultaneous faults.

| Measure | Required outcome/comparison |
| --- | --- |
| Root-cause accuracy | Top-1 and top-3 service/fault identification. |
| Efficiency | Diagnosis time and tool calls. |
| Action quality | Correct, unnecessary, and harmful actions. |
| Recovery | Observed recovery after remediation. |
| Memory | With/without memory, including misleading lessons. |
| Investigation strategy | Parallel diagnosis versus a single investigator. |
| Budgets | 5, 10, and 20 tool calls. |
| Safety | Target of zero harmful actions. |

Retrieval evaluation currently has one labeled development smoke-test query.
Expand it with representative development and held-out queries; one query
cannot establish broad retrieval quality.

### Runtime and operational readiness

If the commander runs in the incident API pod, telemetry URLs must use cluster
service addresses rather than laptop `localhost` endpoints. The inspected
deployment configures flagd addresses, but not the other telemetry endpoints.

Package retrieval dependencies, index storage, provider configuration, and
incident memory for the chosen execution location.

The incident database uses Kubernetes `emptyDir`, so it does not survive pod
replacement. Approval requests and the live gate's audit are held in process
memory. Add durable storage and safe approval/workflow recovery.

Wire lifecycle tracing, agent Grafana panels, and alerts for loops or repeated
rollbacks. Several metrics are declared by the API but are not populated by a
complete investigation lifecycle.

### End-to-end safety integration

Screen telemetry, runbooks, tool descriptions, and lessons before they reach
models or decision logic. Validate generated diagnoses, plans, communications,
and memory writes. Exercise injection and budget controls through the real
commander, not only isolated safety functions.

The live webhook supports optional signatures: when its secret is unset,
unsigned local alerts are accepted with a log message. The live approval path
uses a fixed `oncall` identity rather than authenticated reviewer identity.
Production-facing deployment needs an explicit authentication and access
policy. A confirmation code binds an action; it is not user authentication.

## 5. Recommended delivery sequence

| Priority | Deliverable | Completion criterion |
| --- | --- | --- |
| 1 | Payment investigation integration | A live alert produces persisted telemetry evidence, knowledge citations, and a supported proposal. |
| 2 | Approved action and recovery | The actual generated action is approved/executed; resolution follows sustained recovery, not approval alone. |
| 3 | Durable safe lifecycle | Workflow/approval state survives restart; incident-wide budgets, rollback, and replanning are connected. |
| 4 | Reviewed communications and memory | Cited postmortems are reviewed, stored, and reused only under matching preconditions. |
| 5 | Broader faults and agents | Additional faults and real parallel diagnosis operate through the same contracts and safety controls. |
| 6 | Evaluation and observability | Ground-truth incident suite, required comparisons, held-out gate, and agent dashboards are operational. |

## 6. Source map

| Concern | Primary files |
| --- | --- |
| Scope | `README.md` |
| Shop alert/deployment | `deploy/shop-values.yaml`, `deploy/incident-api.yaml` |
| API lifecycle | `incident_api/incident_api/app.py`, `incident_api/incident_api/store.py` |
| Console | `ui/page.py`, `api/stream.py` |
| Live safety/approval | `api/safety_gate.py`, `safety/approval_service.py`, `safety/hooks.py` |
| Safety validation | `safety/input_guardrails.py`, `safety/output_guardrails.py` |
| Payment slice | `graph/steps.py` |
| Telemetry/actions | `tools/telemetry/`, `tools/actions/set_flag.py` |
| Knowledge/memory | `knowledge/README.md`, `knowledge/retrieval/`, `knowledge/memory/` |
| Agent placeholders | `agents/` |
| Evaluation | `eval/cases.py`, `knowledge/evaluation/golden_queries.yaml` |
| CI | `.github/workflows/ci.yml`, `.github/workflows/security-gate.yml` |

Use code as the authority for current behavior. Some older narrative sections
in the root README and security integration plan describe earlier states.
