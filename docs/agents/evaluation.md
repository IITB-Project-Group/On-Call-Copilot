# Agents Evaluation: E1, E3, E4

| | |
| --- | --- |
| Owner | Role 3, with role 5, who owns the held-out cases and the final runs |
| Status | Harness, configs and the C0 baseline done. Model runs (C1, C2, Reflexion) pending an OpenRouter key |
| Results | `eval/results/twin/` (JSONL rows plus `.summary.json`) |

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

## 3. Results so far

### C0 fixed workflow on the twin, development cases, 3 repeats (60 runs)

Source: `eval/results/twin/e1-c0-fixed.summary.json`.

| Metric | Value |
| --- | --- |
| Runs / errors | 60 / 0 |
| Success | 1.00 |
| Top-1 service / fault type | 1.00 / 1.00 |
| Top-3 service / fault type | 1.00 / 1.00 |
| Correct action proposed | 1.00 |
| Verified recovery (fault cases) | 1.00 |
| Severity matches the case | 0.90 |
| Harmful / unnecessary actions | 0 / 0 |
| Mean tool calls per incident | 16.9 (7 investigation reads, 1 runbook search, 1 dry run, 1 action, about 4 verification samples, 3 ticket writes; two-fault cases about 23) |
| Model cost | 0 (no model) |
| Latency p50 / p95 | 0.04 s / 0.05 s on the twin; not comparable with live runs |

**What this shows, and its limits.**

- **Why C0 scores so high:** on the twin, C0 is close to an oracle for single-flag faults. Its rule reads the flag state, and on the development faults the active flag's service always shows the fault's signal.
- **Why C0 is still useful:** it is the cost and latency floor that C1 and C2 must beat on harder cases.
- **Where C0 is expected to fail.** Two held-out faults break its rule (predicted, not measured):
  - F2 `paymentUnreachable`: payment shows no errors because no requests reach it.
  - F4 `adManualGc`: the fault shares a service and fault type with F9.
  - In both, an active flag's service does not show the signal the rule expects, so C0 can only escalate.
- **Live differs from the twin.** On the live shop the telemetry is noisier than the twin's, and flagd reports no change times. The development numbers will not carry over unchanged.
- **Two severity misses.** These are `dev-f10-startup-window-normal` and `dev-noise-startup-burst`.
  - The twin's startup burst puts frontend at about 3% errors. Under the written policy that is SEV3 (any service at 1% or more), while the case files say SEV4.
  - This is a case-design question for role 1: should startup-window noise count toward severity? It is recorded in the experiment log, and the cases were not changed to match.

### Pending (needs `OPENROUTER_API_KEY`)

| Run | Produces | Est. cost |
| --- | --- | --- |
| E1: C1, C2, C2 single investigator, on dev × 3 | Single vs team comparison; real replan and wrong-first-hypothesis traces | About 20 cases × 3 × 3 configs × about 15 model calls; under $10 at gpt-4.1-mini prices with the gpt-4.1 commander |
| E4: memory on/off × budgets 5/10/20, on dev × 3 | Memory and budget ablation, including pm-006 rejection rates | Similar |
| Reflexion on dev, then review and freeze | Playbook v1 and at least one rejected lesson | Small |
| Held-out (role 5): C0, C1, C2 and E3 before/after, × 3 | The numbers for the report | Role 5 |

The cost cap hook (`max_cost_usd: 0.50` per incident) stops any single runaway run.

## 4. Threats to validity

1. **Twin ≠ shop.** The twin has one effect model per flag. Development tuning on the twin may not transfer, so held-out runs must be live.
2. **The simulated engineer approves every proposal that passed the guardrails.** This measures what the agent proposes, not how a person would decide. Harmful proposals are still counted, because blocked proposals are classified too.
3. **The same model is used across C1 and C2 specialists.** The C2 commander uses a stronger model, which the guide asks for. A strictly equal-model comparison needs a run with `models: {commander: openai/gpt-4.1-mini}` in the C2 config, which is one line to add.
4. **Budgets are equal in total but split differently.** C1 spends its budget freely; C2 spends it per role.
