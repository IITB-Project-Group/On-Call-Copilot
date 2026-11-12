# Evaluation report — On-Call Copilot

**Full method notes:** [agents/evaluation.md](agents/evaluation.md) · **Experiment log:** [agents/experiment-log.md](agents/experiment-log.md) · **Results:** `eval/results/`.

## 1. Setup

| Item | Choice |
| --- | --- |
| System | On-Call Copilot vs OpenTelemetry Astronomy Shop faults |
| Cases | 20 development cases in-repo (`eval/cases/dev`); held-out owned by role 5 outside the tuner’s path |
| Scoring | Code-first against the injected fault — never the agent’s confidence (`score_diagnosis`, `classify_action`, verified recovery) |
| Success | Fault case: correct fix proposed, recovery verified, **zero harmful executed**; noise: no action |
| Also counted | Failed/timed-out runs, blocked proposals, tool calls, cost, p50/p95 latency |
| Dev runs | Shop **twin** (`eval/scenario.py`) — labelled twin, never mixed with live |
| Held-out | Live shop × **3 repeats** (role 5) |
| Config batch reported here | `2026-11-08.4` · commander `openai/gpt-4.1` · specialists `openai/gpt-4.1-mini` · ~160 model runs · ~$2.50 |

## 2. E1 — Does the team justify its cost?

| Config | Success | Top-1 svc / fault | Correct action | Verified recovery | Harmful prop. / exec. | Blocked | Tool calls | Cost (20) | p50 / p95 (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C0 fixed workflow | **1.00** | 1.00 / 1.00 | 1.00 | 1.00 | 0 / 0 | 0 | 16.9 | $0 | 0.04 / 0.10 |
| C1 single agent | 0.80 | 0.75 / 0.65 | 0.85 | 0.89 | 0 / 0 | 12 | 18.3 | $0.27 | 19 / 44 |
| C2 one investigator | 0.75 | 0.65 / 0.70 | 0.80 | 0.83 | 9 / 0 | 11 | 18.6 | $0.30 | 27 / 58 |
| C2 parallel diagnosis | 0.65 | 0.70 / 0.65 | 0.70 | 0.72 | 12 / 0 | 16 | 18.6 | $0.40 | 25 / 65 |

**Reading.** With 20 cases × 1 run, gaps of 1–3 cases are within noise — **not a final ranking**. Patterns that matter:

1. Every model setup **escalates** both noise cases (safe, costs attention); C0’s rule closes them.  
2. Two-fault pairs: models usually fix one fault and stop.  
3. **Harmful proposals were blocked; none executed** (still counted per guide).  
4. Parallel diagnosis best top-3 recall; top-1 no better than C1.  
5. C0 dominates on the twin (visible flag). Held-out F2/F4 are where models should earn cost — prediction until role 5 runs live.

## 3. E4 — Memory on/off × budgets 5 / 10 / 20

| Budget | Memory on (success) | Memory off (success) |
| --- | --- | --- |
| 5 | 0.55 | **0.75** |
| 10 | 0.65 | 0.70 |
| 20 | 0.65 | 0.70 |

Harmful **executed** = 0 everywhere. Memory on did **not** help on these twin development cases; at budget 5 it hurt (memory_search consumes scarce tool calls). Seed lessons largely restate faults the agents already find. Misleading-lesson behaviour (pm-006) is checked by precondition recall — see [MEMORY_POLICY.md](MEMORY_POLICY.md) and demo item 3; held-out F4 is the stress case.

## 4. E3 — Did lessons help?

Reflexion produced 7 drafts from failed E1 team runs (`eval/reflexion/pending.jsonl`); suggested review (3 approve / 4 reject) is ready for human review. After review + `freeze`, Role 5 runs held-out before/after playbook. Held-out before/after deltas will be added when those runs complete.

## 5. E2 / security (pointer)

Defences and red-team evidence live in `safety/` and `oncall-security/reports/` (attack success with defences off/on, false blocks). Threat summary: [THREAT_MODEL.md](THREAT_MODEL.md).

## 6. Threats to validity

1. Twin ≠ live shop.  
2. Simulated engineer approves every guardrail-passing proposal.  
3. C2 commander uses a stronger model than specialists (guide-aligned); equal-model ablation still open.  
4. Same total budget, different per-role splits for C1 vs C2.

## 7. Follow-on work

- Human review and freeze of playbook v1  
- Role 5 held-out ×3: C0, C1, C2, E3 before/after, E4 memory × budgets  
- Report spread (min/mean/max) on held-out and fold those tables into this report  

