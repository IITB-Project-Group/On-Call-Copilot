# OnCall Copilot: Current Status and Integration Gaps

Assessment date: 5 November 2026.

## Executive summary

The project has a monitored shop, an incident console, telemetry adapters, a
substantial knowledge-retrieval component, incident-memory functions, and safety
controls. On the running cluster, a checkout alert can be screened, rejected
when the confirmation is wrong, and closed by turning `paymentFailure` off.
The main remaining work is the integrated copilot that investigates an
incident, proposes an evidence-backed fix, obtains approval, verifies recovery,
and produces a reviewed postmortem. Before that, `up.sh` on main does not
publish this cluster's tool ports, trace queries miss Jaeger's real path, and
the flag write does not finish when the evaluation port is silent.

The first completion milestone should be:

**Payment alert -> supported diagnosis -> exact approval -> flag change ->
verified recovery -> reviewed incident record.**

This assessment uses main, including the safety layer and the live-data
screening merged in pull request 8, and a check of the running kind cluster on
5 November 2026. It does not re-derive the original capstone PDF. Two open
branches differ from main and are named where that matters: pull request 7
makes the shop tools reach this cluster, and `safety-live-controls` starts the
copilot MCP servers. Scope references come from the repository's root README,
which identifies itself as the capstone build contract.

The root README's statement that runbooks and agents are still to be built is
partly outdated: knowledge retrieval and incident memory are substantially
implemented, while the agent packages remain mostly placeholders.

## 1. Current implementation

| Area | Available capability | Integration status |
| --- | --- | --- |
| Demo infrastructure | `up.sh`, `down.sh`, and Kubernetes configuration for the Astronomy Shop and incident API. | The kind cluster was up on 5 November 2026, with the shop and incident API answering. `up.sh` on main stops before the tool port-forwards on this chart. |
| Alerting | `ServiceErrorRateHigh`, using a five-minute error-rate window and an additional one-minute pending period. | Alertmanager is configured to feed the incident API. |
| Incident API | Webhook, incident list/detail, decisions, health, metrics, and SQLite storage. | Connected to the console and payment approval path. |
| Incident console | Open/closed views, streamed incident snapshots, editable notes, approve/reject controls, and confirmation-code input. | Shows stored state, not a full investigation timeline. |
| Telemetry | PromQL, logs, traces, flag-state inspection, service error/request rates, p95 latency, and metric discovery. | The adapters answered on the running cluster. The live webhook does not invoke the investigation that uses them. The code default trace path `/jaeger` returns 404; this shop serves traces at `/jaeger/ui`. |
| Knowledge corpus | 15 runbooks and 10 seed postmortems, including a misleading-lesson example. | Available to retrieval. |
| Retrieval | Metadata-preserving ingestion/chunking, BM25, semantic search, Chroma, rank fusion, query rewriting, reranking, and tool adapters. | Callable from the payment investigation, but not wired into live incident intake. |
| Incident memory | SQLite save, semantic search, and lesson applicability checks. | Not connected to the console's completion path. |
| Payment investigation | Telemetry reads, knowledge retrieval, payment hypothesis, and dry-run action proposal. | Implemented separately from the active API alert/approval path. |
| Flag remediation | Read/write a selected flag variant and poll flagd until it serves that variant. | Live approval is wired specifically to disable `paymentFailure`. On this cluster the pod could read the flag document and the evaluation port did not answer, so main's poll does not finish. |
| Safety | Input/output guardrails, redaction, approval service, command binding, hooks, budgets, loop limits, kill switch, and a hardened detector on live tool text. | Webhook screening, the payment write, and screening inside the log, trace, and runbook tools are integrated. The webhook does not call those tools. Investigation-wide enforcement is not. |
| CI | Lint/format, Python tests with coverage, API image build, and guardrail/API-security workflow. | Definitions exist; there is no full incident evaluation gate. |
| Copilot MCP | Read-only telemetry tools and runbook search, with FastMCP wrappers. | On main the wrappers are not started. `safety-live-controls` serves them at `http://127.0.0.1:8012/mcp` and `http://127.0.0.1:8013/mcp`, and both answered on the cluster. Agents do not call them yet. |
| Shop MCP | The Astronomy Shop Helm release runs `astronomy-shop-mcp` for cart, checkout, and product lookup. | The pod is up in the cluster on port 8011. It is not the incident tool server, and `up.sh` does not publish that port. |

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
| Telemetry MCP | http://127.0.0.1:8012/mcp |
| Runbooks MCP | http://127.0.0.1:8013/mcp |

On 5 November 2026 the shop, Grafana, Jaeger UI, feature flags, load generator,
incident console, Prometheus, OpenSearch, and flagd URLs above answered. The
two MCP URLs answered from `safety-live-controls`, not from main. `up.sh` on
main looks for a Prometheus service named `prometheus-server`. This chart names
it `prometheus`, so that script exits before it publishes Prometheus,
OpenSearch, and flagd. Pull request 7 and `safety-live-controls` recognize the
name this cluster uses.

Running pods establish infrastructure availability, not completion of the agent
workflow. The incident API image that completed the live flag write included
the pull request 7 fallback. Main's image still waits on the evaluation port.

### Component qualifications

- `recent_changes()` currently lists flags that are not off. It is not a
  timestamped change history and does not provide deployment history.
- The knowledge README reports a previously built persistent index and a
  successful retrieval smoke test. Availability of that index, dependencies,
  credentials, and provider access in the current deployment is not established.
- Incident memory records service, symptom, root cause, fix, lesson,
  preconditions, failure family, and reviewer. Retrieved lessons can be applied
  or rejected according to applicability conditions.
- Safety functions and hooks exist beyond the live path. Logs, traces, and
  retrieved runbook text are screened when those tool functions run. Metrics,
  flag changes, and lessons are not screened on that same path, and the live
  webhook does not call the tools.
- `frontend-web` is not a known service, so an alert that names it is rejected.
- `SafetyGate.rollback` can turn `paymentFailure` back on. No console route
  calls it, and the predefined rollback assumes the flag was on rather than
  saving the previous variant.

### Checked on the running cluster

- Host tool calls returned error ratios, rates, latency, metric names, and an
  empty set of active flags. `paymentFailure` was `off`.
- Checkout traces returned spans at `/jaeger/ui`. The same call at the code
  default `/jaeger` returned HTTP 404. Payment had no error spans in the last
  hour, and a payment error-log search returned no lines.
- Alertmanager had opened incidents for `ad`, `cart`, `frontend`,
  `frontend-proxy`, and `recommendation`. None of those had a confirmation
  code. Checkout was about a 3.4% error ratio, under the 5% page line, so it
  had not paged on its own.
- A posted checkout alert stored its summary as untrusted telemetry. A wrong
  confirmation returned 400 and left the request pending. The matching code,
  against the pull request 7 image, returned `paymentFailure is off`.
- Runbook search answered and returned `EMBEDDING_PROVIDER must be
  'openrouter'`. The incident API image has no embedding key.
- The copilot telemetry server listed its nine read tools and returned a live
  error ratio. The runbooks server listed `search`. The in-cluster shop MCP
  server listed cart, checkout, and product tools.

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

After approval, main's flag tool writes the flag document and then polls
flagd's evaluation port until that port serves the variant. From the incident
API pod the flag document on port 4000 answered and the evaluation port on
8016 did not, so the poll fails. The approval can be left executed while the
incident decision stays unset. Pull request 7 accepts the flag document when
the evaluation port does not answer.

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
| Shop tool ports | `up.sh` must find the Prometheus service named `prometheus`, trace queries must use `/jaeger/ui`, and a flag write must finish when the evaluation port is silent. |
| Copilot MCP | After `safety-live-controls` merges, point the commander at the telemetry and runbooks servers. The payment function currently calls the Python clients in-process. |

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
retained in the final build scope. The flag restore on `SafetyGate.rollback`
is separate from those adapters and is not exposed by the console.

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
deployment configures flagd addresses, but not Prometheus, Jaeger, or
OpenSearch. The host tools reached those services through `up.sh` port-forwards.
Jaeger on this shop is served by the frontend proxy at `/jaeger/ui`, not at
`/jaeger` or on port 16686.

Package retrieval dependencies, index storage, provider configuration, and
incident memory for the chosen execution location. Runbook search on the host
rejected `EMBEDDING_PROVIDER=local` and requires `openrouter`. Wiring that
search into the pod before the deployment has a provider and a key will fail
closed.

The incident database uses Kubernetes `emptyDir`, so it does not survive pod
replacement. Approval requests and the live gate's audit are held in process
memory. Add durable storage and safe approval/workflow recovery.

Wire lifecycle tracing, agent Grafana panels, and alerts for loops or repeated
rollbacks. Several metrics are declared by the API but are not populated by a
complete investigation lifecycle.

### End-to-end safety integration

Logs, traces, and retrieved runbook text are screened in the tool functions,
and an MCP server refuses a tool description that carries an instruction.
Metrics, flag changes, and lessons still need that screening before a model or
a decision uses them. Validate generated diagnoses, plans, communications, and
memory writes. Exercise injection and budget controls through the real
commander, not only isolated safety functions.

The live webhook supports optional signatures: when its secret is unset,
unsigned local alerts are accepted with a log message. The live approval path
uses a fixed `oncall` identity rather than authenticated reviewer identity.
Production-facing deployment needs an explicit authentication and access
policy. A confirmation code binds an action; it is not user authentication.

## 5. Recommended delivery sequence

| Priority | Deliverable | Completion criterion |
| --- | --- | --- |
| 1 | Reachable shop tools | `up.sh` publishes Prometheus, OpenSearch, and flagd for this chart; traces use `/jaeger/ui`; a flag write finishes when the evaluation port is silent. |
| 2 | Payment investigation integration | A live alert produces persisted telemetry evidence, knowledge citations, and a supported proposal. Runbook search can run in the place that investigation runs. |
| 3 | Approved action and recovery | The actual generated action is approved and executed; resolution follows sustained recovery, not approval alone. The console can roll the flag back. |
| 4 | Durable safe lifecycle | Workflow/approval state survives restart; incident-wide budgets, rollback, and replanning are connected. |
| 5 | Reviewed communications and memory | Cited postmortems are reviewed, stored, and reused only under matching preconditions. |
| 6 | Broader faults and agents | Additional faults and real parallel diagnosis operate through the same contracts and safety controls. The commander calls the copilot MCP servers. |
| 7 | Evaluation and observability | Ground-truth incident suite, required comparisons, held-out gate, and agent dashboards are operational. |

## 6. Source map

| Concern | Primary files |
| --- | --- |
| Scope | `README.md` |
| Shop alert/deployment | `deploy/shop-values.yaml`, `deploy/incident-api.yaml` |
| API lifecycle | `incident_api/incident_api/app.py`, `incident_api/incident_api/store.py` |
| Console | `ui/page.py`, `api/stream.py` |
| Live safety/approval | `api/safety_gate.py`, `safety/approval_service.py`, `safety/hooks.py` |
| Live tool screening | `api/live_screen.py`, `safety/hardened_detector.py` |
| Safety validation | `safety/input_guardrails.py`, `safety/output_guardrails.py` |
| Payment slice | `graph/steps.py` |
| Telemetry/actions | `tools/telemetry/`, `tools/actions/set_flag.py` |
| Copilot MCP | `tools/mcp_runtime.py`, `tools/telemetry/server.py`, `tools/runbooks/server.py`, `up.sh`. The HTTP servers and the `up.sh` launch are on `safety-live-controls`; main has the tool modules and does not start them. |
| Knowledge/memory | `knowledge/README.md`, `knowledge/retrieval/`, `knowledge/memory/` |
| Agent placeholders | `agents/` |
| Evaluation | `eval/cases.py`, `knowledge/evaluation/golden_queries.yaml` |
| CI | `.github/workflows/ci.yml`, `.github/workflows/security-gate.yml` |

Use code as the authority for current behavior. Some older narrative sections
in the root README and security integration plan describe earlier states.
