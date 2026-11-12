# Memory policy (L9 / L12) — one page

Written policy for what On-Call Copilot stores, when it is used, who can change it, and how it is corrected. Implementation detail: [agents/playbook.md](agents/playbook.md), `agents/memory/`, `knowledge/playbook/`, `safety/input_guardrails.py` (`check_lesson`, `validate_memory_write`).

## 1. What is stored

| Kind | Content | Location |
| --- | --- | --- |
| Incident record | Service, symptom, root cause, fix, verification outcome | Incident store / postmortem path |
| Seed lessons | Structured lessons from past postmortems | `knowledge/playbook/seed-lessons.yaml` (pm-001…pm-008) |
| Reflexion playbook | Lessons from failed **development** runs after human review | `knowledge/playbook/playbook.yaml` (frozen before held-out) |
| Rejected drafts | Lesson text + rejection reason | `knowledge/playbook/rejected.yaml` |

A lesson is at least: `{id, service, fault_type, lesson, preconditions, reviewed_by, created_at}`.

## 2. Preconditions (mandatory)

Preconditions are machine-checkable observations recorded by tools during the incident (e.g. `error_ratio.payment gte 0.05`, `flag.adHighCpu eq true`, `cpu_ratio.ad gte 0.9`).  
A lesson **without** preconditions is refused. An **unobserved** precondition counts as **not** satisfied.

## 3. Recall (read path)

A lesson may change ranking only if `InputGuardrails.check_lesson` passes:

1. Reviewed by a named person  
2. Younger than **365 days**  
3. No instruction-like / injection text  
4. **Every** precondition holds on evidence observed in **this** incident  

Otherwise it is rejected with a reason (demo item 3: pm-006 on a payment incident — CPU / flag preconditions fail). Applied lessons are passed to specialists as **data** in the context slot, never as executable instructions.

## 4. Writes (write path)

Agents only **propose** lessons. A named human must approve (graph `learn` interrupt, or offline `eval.playbook review`).

`validate_memory_write` requires:

- Human `reviewed_by`  
- Preconditions present  
- Known service / fault type  
- Verified outcome (`verified_recovery` / `verified_failure`) where applicable  
- No echoed destructive commands  
- Store **not** frozen  

Reflexion drafts (dev only) additionally need ≥2 preconditions, at least one discriminating (flag, liveness, log signature, deploy, resource metric — not only “error rate is high”), and no contradiction with an existing lesson.

## 5. Freeze, retention, correction

| Control | Rule |
| --- | --- |
| Freeze | Before held-out runs, `eval.playbook freeze` writes `playbook.lock.json`. Later writes are refused; a modified frozen file fails the hash check on load |
| Retention | Lessons older than 365 days stop applying and must be re-reviewed |
| Correction / delete | Rejected lessons keep a reason in `rejected.yaml`. Approved lessons are corrected by a new reviewed write after unfreeze (never silent edit of a frozen file) |
| Who can read | On-call graph roles that need context (runbook / diagnosis prompts); evaluation harness. No cross-tenant personal data is stored |

## 6. Evaluation link

**E4** compares memory on vs off (including the misleading-lesson case) and tool budgets 5 / 10 / 20 — see [agents/evaluation.md](agents/evaluation.md).  
**E3** compares held-out results before vs after the frozen Reflexion playbook (role 5).
