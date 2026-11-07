# Lessons, Memory and the Playbook (L9, L12)

## 1. Two kinds of lesson

| Kind | Where | How it gets there | How it is used |
| --- | --- | --- | --- |
| Seed lessons from past postmortems | `knowledge/playbook/seed-lessons.yaml` (pm-001 to pm-008) | Role 3 converted role 2's postmortems into structured preconditions; role 2 confirms each | Memory on (E4): recalled by `memory_search` and in the diagnosis prompt, only when the preconditions match |
| Playbook from Reflexion | `knowledge/playbook/playbook.yaml` (currently empty) | Reflexion on development cases, reviewed by a person, then frozen | E3 "after" config; the same recall rules |

## 2. When a lesson applies

- **What a lesson states.** Each lesson gives its preconditions as observation keys, which the tools record during the incident (`agents/toolbox.py: record_observations`). Examples:
  - `cpu_ratio.ad gte 0.9`
  - `flag.adHighCpu eq true`
  - `error_ratio.payment gte 0.05`
- **The check at recall.** Code runs `InputGuardrails.check_lesson`. A lesson is rejected, with the reason, when it:
  - was not reviewed by a person;
  - is older than 365 days;
  - contains instruction-like text;
  - has a precondition that is not met;
  - has a precondition that was not observed. An unknown condition is not a satisfied one.
- **Applied lessons** reach the specialists as data, inside the prompt's context slot.
- **Rejected lessons** are reported by the runbook specialist with the failed precondition.

### Misleading lesson: pm-006 is rejected (demo item 3)

pm-006 says ad latency comes from `adHighCpu` when ad CPU is saturated. On the payment incident `dev-f1-50pct` it looks relevant, as in role 2's pm-010 case, but recall rejects it.

From [traces/guardrails-and-lessons.json](traces/guardrails-and-lessons.json):

```
pm-006  applicable: false
reason: cpu_ratio.ad: expected gte 0.9, observed 0.25; flag.adHighCpu: expected eq True, observed False
```

E4 measures this at scale. With memory on, the misleading lesson is offered on every ad-latency incident. The held-out F4 `adManualGc` is the case where applying it would lead to the wrong flag. Memory off is the control.

## 3. Reflexion loop and review

1. **Run.** `python -m eval.reflexion --experiment eval/experiments/e3-c2-no-playbook.yaml` runs the team on the **development** cases.
2. **Evaluate.** For each failed case, the evaluator (checker code) writes the feedback: the injected fault, what the team concluded, the action, verification and harm.
3. **Reflect.** The reflection model gets that feedback and a compact trajectory from the trace. It writes one `LessonDraft` with observable preconditions, never case ids. Each draft lands in `eval/reflexion/pending.jsonl`.
4. **Review.** A person reviews each draft in `decisions.yaml`, writing `approve` or `reject: <reason>`. Then run:

   ```
   python -m eval.playbook review --pending eval/reflexion/pending.jsonl --decisions decisions.yaml --reviewer <name>
   ```

   - Approved lessons must pass `validate_memory_write`: a human reviewer, preconditions, and a known service and fault type.
   - Rejected lessons go to `knowledge/playbook/rejected.yaml`, with the reason. **The submission shows at least one.**
5. **Freeze.** `python -m eval.playbook freeze` writes `playbook.lock.json`, the hash of the playbook. Held-out runs refuse an unfrozen or changed playbook, and `memory_write` is refused while frozen.

During incidents (not evaluation), the same review happens in the graph's `learn` interrupt. The postmortem proposes lessons, and a person approves or rejects each one before it is stored.

## 4. Status

| Item | Status |
| --- | --- |
| Seed lessons with preconditions | Done (8); role 2 to confirm the conversions |
| Precondition recall and rejection | Done and tested; pm-006 rejection shown above |
| Reflexion pipeline, review, freeze, held-out guard | Done and tested with scripted models |
| Playbook v1 lessons and a rejected Reflexion lesson | **Pending a real model run.** The commands are above. The rejected example will come from that review, not be invented |

Not converted: pm-009 names a service the shop does not have (inventory). pm-010 is itself the misleading-lesson scenario, which pm-006's rejection demonstrates.
