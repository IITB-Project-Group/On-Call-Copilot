# Agents Evaluation: E1, E3, E4

| | |
| --- | --- |
| Owner | Role 3, with role 5, who owns the held-out cases and the final runs |
| Status | Development runs done on the shop twin: C0, C1, C2, the single-investigator team, memory on/off × budgets 5/10/20, and Reflexion. Lessons await human review; held-out runs belong to role 5 |
| Results | C0: `eval/results/twin/`. Model runs (config `2026-11-08.4`): `eval/results/twin-model/`, with traces. Earlier tuning iteration: `eval/results/twin-model-iter1/` |

This is role 3's input to the evaluation report. It says what is measured, how, what has been run so far, and exactly what remains to run.

## 1. Protocol (guide, "Evaluation protocol")

- **Cases.**
  - 20 development cases are in `eval/cases/dev`: F1, F3, F9 and F10 with 4 variants each, two noise cases, and two two-fault cases.
  - They follow role 1's split (docs/domain-and-product.md, section 9).
  - Role 3 drafted them from role 1's catalogue, and role 1 confirms them.
  - Held-out cases (40) are written and kept by role 5 outside this repository. The runner refuses `--split heldout` without `--cases-dir`, and refuses a playbook unless it is frozen and unchanged (`eval.playbook check`).
- **Configs.** Every experiment is a file in `eval/experiments/`, not a code branch. Each row records:
  - the config version (`2026-11-07.1`);
  - the experiment name;
  - the architecture, parallel mode, memory setting, budget and playbook;
  - the exact model ids.
- **Scoring by code against the injected fault, never the agent's confidence.**
  - `score_diagnosis`: top-1 and top-3 match, by service and by fault type.
  - `classify_action`: correct, unnecessary or harmful. Blocked proposals are counted.
  - Verified recovery: the agent's sustained check passed and the fault's flag is actually off in the shop.
  - Severity against `severity_from_policy`.
- **Success.**
  - For a fault case: every injected fault's fix was proposed, recovery was verified, and there were zero harmful actions.
  - For a noise case: no action and outcome `no_action`.
- **Also reported:**
  - failed and errored runs, which are rows with `error` set;
  - tool calls, replans, rollbacks and blocked proposals;
  - cost per case;
  - p50 and p95 latency.
- **Repeats.** 3 per configuration (`repeats: 3`), with the spread reported. Held-out runs are made 3 times by role 5.
- **Where runs happen.**
  - **Development runs** use the shop twin (`eval/scenario.py`). It answers the same tool names from a case's injection.
  - **Held-out runs** use the live shop with real fault injection.
  - Twin results are always labelled "twin" and never mixed with live ones.

## 2. Experiments and commands

| Experiment | Question | Configs | Command |
| --- | --- | --- | --- |
| E1 | Does the team justify its cost? | `e1-c0-fixed`, `e1-c1-single`, `e1-c2-team` | `python -m eval.runner --experiment eval/experiments/<cfg>.yaml --out eval/results/twin/<cfg>.jsonl` |
| E1 (On-Call) | Parallel diagnosis or one investigator? | `e1-c2-team` vs `e1-c2-single-investigator` | same |
| E3 | Does the reviewed playbook help on unseen incidents? | `e3-c2-no-playbook` vs `e3-c2-playbook` (frozen) | Reflexion and review on dev (playbook.md), then role 5 runs held-out with `--split heldout --cases-dir <role 5>` |
| E4 | Does postmortem memory help, including the misleading lesson? What do budgets buy? | `e4-c2-memory-on` vs `e4-c2-memory-off`, each with `--budget 5`, `10` and `20` | `python -m eval.runner --experiment eval/experiments/e4-c2-memory-on.yaml --budget 5 --out ...` |

## 3. Results on the development cases (shop twin)

**Setup.**

- 20 development cases; one run per case per configuration.
- Config `2026-11-08.4`.
- Models: commander `openai/gpt-4.1`, specialists `openai/gpt-4.1-mini`, via OpenRouter.
- Model runs: 160, with 0 errors after re-running the ones that failed during a network outage.
- Spend for the batch: about $2.50, as reported by OpenRouter.
- Sources: `eval/results/twin/e1-c0-fixed.*` and `eval/results/twin-model/*.summary.json`.

**How much these numbers can tell you.** With 20 cases and one run each, a difference of 1 to 3 cases (5 to 15 points) is within run-to-run variation. **None of the comparisons below is a reliable ranking.** They show where each design fails. Role 5's held-out runs, with 3 repeats each, are what the report should rank on.

### E1: does the team justify its cost?

| Config | Success | Top-1 service / fault | Top-3 service / fault | Correct action | Verified recovery | Severity | Harmful proposed / executed | Blocked proposals | Tool calls | Model cost, 20 cases (USD) | Latency p50 / p95 (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C0 fixed workflow | **1.00** | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 | 1.00 | 0.90 | 0 / 0 | 0 | 16.9 | 0 | 0.04 / 0.10 |
| C1 single agent | 0.80 | 0.75 / 0.65 | 0.75 / 0.65 | 0.85 | 0.89 | 0.60 | 0 / 0 | 12 | 18.3 | 0.27 | 19 / 44 |
| C2 team, one investigator | 0.75 | 0.65 / 0.70 | 0.70 / 0.85 | 0.80 | 0.83 | 0.60 | 9 / 0 | 11 | 18.6 | 0.30 | 27 / 58 |
| C2 team, parallel diagnosis | 0.65 | 0.70 / 0.65 | 0.90 / 0.90 | 0.70 | 0.72 | 0.75 | 12 / 0 | 16 | 18.6 | 0.40 | 25 / 65 |

Model cost is the cost hook's estimate from token counts.

**Where they fail** (successes per group of cases):

| Config | F1 payment and pair F1+F9 | F3 cart and pair F3+F10 | F9 ad CPU | F10 Kafka | Noise |
| --- | --- | --- | --- | --- | --- |
| C0 | 5/5 | 5/5 | 4/4 | 4/4 | 2/2 |
| C1 | 4/5 | 4/5 | 4/4 | 4/4 | 0/2 |
| C2, one investigator | 3/5 | 4/5 | 4/4 | 4/4 | 0/2 |
| C2, parallel | 3/5 | 4/5 | 4/4 | 2/4 | 0/2 |

**What the results show.**

1. **No model setup closes a false alarm.**
   - On both noise cases every model configuration escalated to a person instead of closing with no action. That is safe, but costs an engineer's attention.
   - C0's rule only acts when an active flag's service shows the matching signal, so it closes them.
2. **Two faults at once.** The model setups usually fix the first fault and stop. Both pair cases count as failures in every model configuration.
3. **Harmful proposals were all blocked; none were executed.** Harmful proposed / executed is 12 / 0 for the team.
   - Every harmful proposal (restarting flagd, a protected service; switching a failure flag on) was refused by the guardrails or the dry run.
   - The guide counts proposals, so they appear in the table.
4. **The team does better at ranking, worse at the top choice.**
   - Parallel diagnosis gives the best top-3 recall (0.90). Separate diagnosers each put their own suspect on the list.
   - Its top-1 choice is no better than the single agent's. The merged list sometimes ranks a knock-on service first.
   - That is what the guide asked us to test with "parallel diagnosis vs one investigator".
5. **C0 is the cost and accuracy ceiling on the twin.** The twin makes the active flag visible and its effect clean, which suits C0's rule.
   - As predicted, the held-out faults F2 (`paymentUnreachable`) and F4 (`adManualGc`) should break that rule. That is where the model setups are expected to earn their cost.
   - This is a prediction, not a result.

### E4: postmortem memory and tool budgets

| Budget | Memory on | Memory off |
| --- | --- | --- |
| 5 | 0.55 (top-1 service 0.60, harmful proposed 10, cost 0.42) | 0.75 (0.70, 1, 0.32) |
| 10 | 0.65 (0.70, 12, 0.40). The E1 team run | 0.70 (0.70, 1, 0.38) |
| 20 | 0.65 (0.75, 5, 0.52) | 0.70 (0.75, 5, 0.49) |

Each cell is success, then in brackets top-1 service, harmful proposed and model cost for 20 cases in USD. Harmful executed was 0 everywhere.

- **Memory on did not help on the development cases, and at budget 5 it hurt.**
  - With a budget this small, the runbook specialist's `memory_search` call takes one of the few tool calls left for investigation.
  - The seed lessons describe the same faults the agents already find. On these cases they add context but no new information.
- **The misleading lesson.** The misleading-lesson test (pm-006 on an ad incident with normal CPU) is the held-out F4 case. On development cases pm-006's preconditions hold only for F9, where it is correct. In the traces, pm-006 was applied only in F9 cases, and every other seed lesson only in its own fault group (pm-001 on F1, pm-002 on F3, pm-005 on F10).
- **Budget.** Going from 10 to 20 calls raised cost by about 30% and tool calls from about 19 to 26. Success did not change.

### Iteration history

`eval/results/twin-model-iter1/` holds the first model batch (configs `2026-11-08.1` and `.2`), before the fixes in the experiment log.

- In that batch, C1 scored 0% on fault type: the hand-off schema allowed free text.
- The team proposed switching a failure flag on, and restarts this deployment cannot execute.

The jump from iteration 1 to the current numbers comes from tuning on the development cases. That is allowed, and every change is logged. **The held-out cases have not been seen.**

### E3: playbook (Reflexion)

- Reflexion reflected on the 7 failed team runs: `eval/reflexion/pending.jsonl`.
- Suggested review decisions are in `eval/reflexion/decisions.yaml`: approve 3, reject 4, with reasons.
- After a person reviews, run `python -m eval.playbook review ...` and then `freeze`.
- Role 5 then runs `e3-c2-no-playbook` and `e3-c2-playbook` on the held-out cases.

## 4. Threats to validity

1. **Twin ≠ shop.** The twin has one effect model per flag. Development tuning on the twin may not transfer, so held-out runs must be live.
2. **The simulated engineer approves every proposal that passed the guardrails.** This measures what the agent proposes, not how a person would decide. Harmful proposals are still counted, because blocked proposals are classified too.
3. **The same model is used across C1 and C2 specialists.** The C2 commander uses a stronger model, which the guide asks for. A strictly equal-model comparison needs a run with `models: {commander: openai/gpt-4.1-mini}` in the C2 config, which is one line to add.
4. **Budgets are equal in total but split differently.** C1 spends its budget freely; C2 spends it per role.
