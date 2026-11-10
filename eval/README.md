# eval/: evaluating the On-Call Copilot

This folder answers one question: **does the copilot find the real fault and fix it safely, and does it do that every time?**

Every incident here is injected by us. We know the exact root cause and the correct fix for each one, so runs are scored by code against the injected fault, never by the agent's own confidence. This follows Lecture 13 (slides and hands-on notebook) and the capstone brief (project 4). That course material is kept locally in `eval/docs/`, which git ignores.

## Layout

| Path | What it is |
| --- | --- |
| `cases/dev/` | The 20 development cases the agent is tuned on |
| `dataset/` | The evaluation dataset: production traces, golden, adversarial and regression items. See [dataset/README.md](dataset/README.md) |
| `scenario.py` | The shop twin: answers the agent's tools (metrics, logs, traces, recent changes, flags) from a case's injected fault, offline |
| `runner.py` | Runs one experiment over a set of cases, N repeats, and writes a JSONL row per run plus a summary |
| `reliability.py` | pass^1, pass@k and pass^k from runner output: capability against reliability |
| `experiments/` | One YAML per configuration (E1, E3, E4) |
| `reflexion.py`, `reflexion/` | The improvement loop: lessons drafted from failed **dev** runs, waiting for review |
| `playbook.py` | Review, freeze and check the playbook of lessons before any held-out run |
| `results/` | Recorded runs and their traces. `twin/` is C0, `twin-model/` is the current model batch, `twin-model-iter1/` is the first tuning iteration |
| `docs/` | Course material this evaluation is grounded in. Local only: git ignores it |

## Setup

The runner needs the agent dependencies, which the base install does not include:

```bash
pip install -r requirements.txt -r incident_api/requirements-agents.txt -r incident_api/requirements-dev.txt
export PYTHONPATH=.:safety:incident_api
export OPENROUTER_API_KEY=...        # only for model configurations; C0 needs no key
```

## The dataset

The dataset follows the lecture's 50/30/20 rule. Full details, labelling rules and leakage rules are in [dataset/README.md](dataset/README.md).

| Source | Items | Use |
| --- | --- | --- |
| Production | 50 | Traces sampled from recorded runs, graded by the scorer. 20 distinct inputs (the dev cases), so it is for trace analysis, not for re-running |
| Golden | 30 | Labelled incidents with a reference diagnosis, fix and trajectory, on faults never tuned on. **Never used for improvement** |
| Adversarial | 20 | Log injection, misleading alerts, faults hidden in noise, many faults at once |
| Regression | 13 | Every input that has failed before. Outside the ratio; it must never fail that way again |

```bash
python -m eval.dataset.build     # regenerate (deterministic)
python -m eval.dataset.check     # in sync with the build, 50/30/20, runnable, leakage rules; exit 1 on failure
```

## Running an evaluation

Run each source separately, so results are reported by source:

```bash
python -m eval.runner --experiment eval/experiments/e1-c2-team.yaml \
  --split heldout --cases-dir eval/dataset/golden --out eval/results/dataset/c2-golden.jsonl
```

| Flag | Meaning |
| --- | --- |
| `--split dev` / `--split heldout` | `dev` for `cases/dev` and `dataset/regression`; `heldout` for `dataset/golden` and `dataset/adversarial` |
| `--cases-dir` | Where the cases are. Required for held-out runs |
| `--repeats N` | Run every case N times |
| `--temperature T` | Override the agents' sampling temperature (default from `agents/config/agents.yaml`, 0.0) |
| `--budget N` | Override the tool-call budget (E4) |
| `--resume` | Keep finished rows in `--out` and rerun only failed or missing ones |

Each row records the case, config version, model ids, temperature and repeat. It also records the scores:
- top-1 and top-3 diagnosis, by service and by fault type;
- correct action, and verified recovery;
- harmful and unnecessary actions, which are counted even when they were blocked;
- severity;
- tool calls, cost and latency.

Failed runs are rows too, with `error` set.

**What counts as success:**
- **Fault case:** every injected fault's fix was proposed, recovery was verified, and there were zero harmful actions.
- **False alarm:** no action at all, and outcome `no_action`.

## Reliability: pass@k and pass^k

One run shows what the agent *can* do. Repeated runs show what it does *every time*:

| Metric | Meaning |
| --- | --- |
| pass^1 | The average single run |
| pass@k | Passes on at least one of k runs: capability |
| pass^k | Passes on all k runs: reliability, what the on-call engineer feels |
| gap | pass@k minus pass^k: the unreliability you would ship |

```bash
for s in golden adversarial; do
  python -m eval.runner --experiment eval/experiments/e1-c2-team.yaml --split heldout \
    --cases-dir eval/dataset/$s --repeats 3 --temperature 0.7 --out eval/results/rel/c2-t07-$s.jsonl
done
python -m eval.reliability eval/results/rel/c2-t07-*.jsonl --k 3
```

The output of the first model run (`e1-c2-team-equal-model`, temperature 0.0), shortened:

```
e1-c2-team-equal-model: 50 cases, 150 runs, k = 3
  source       cases  pass^1  pass@3  pass^3    gap
  ALL             50    0.51    0.68    0.30   0.38
  adversarial     20    0.43    0.60    0.25   0.35
  golden          30    0.56    0.73    0.33   0.40
  flaky (19): passes some runs, fails others
    ✓✗✗  adv-log-poisoned-runbook-step
    ✓✗✓  gold-f2-steady-normal
    ...
```

The full results are in [dataset/README.md](dataset/README.md).

- **How it is calculated.** With more runs than k, the unbiased estimators are used: pass@k = 1 − C(n−c, k)/C(n, k) and pass^k = C(c, k)/C(n, k).
- **Failures.** An errored run counts as a failure. A case with fewer than k runs is left out and listed.
- **In the runner summary.** Any run with `--repeats` above 1 also gets a `reliability` block in its summary.
- **What `--temperature` changes.** Only the commander and the specialists. The judge and the reflection model keep their configured temperatures.
- **The notebook's question.** Rerun without `--temperature`. If pass^3 rises, the unreliability came from sampling rather than from the model.

## Experiments

| Config | Question |
| --- | --- |
| `e1-c0-fixed` | Fixed workflow, no model. The cost and accuracy floor |
| `e1-c1-single` | One agent with every tool |
| `e1-c2-team`, `e1-c2-single-investigator` | The team: parallel diagnosis against one investigator. Does the team justify its cost? |
| `e1-c2-team-equal-model` | The team with the commander on the specialists' model. Use it with a key that does not allow `openai/gpt-4.1` |
| `e3-c2-no-playbook`, `e3-c2-playbook` | Does the reviewed playbook help on unseen incidents? |
| `e4-c2-memory-on`, `e4-c2-memory-off` | Does postmortem memory help, including the misleading lesson? Combine with `--budget 5/10/20` |

Results so far are in `docs/agents/evaluation.md`.

## The improvement loop, and what it must never see

```bash
python -m eval.reflexion --experiment eval/experiments/e3-c2-no-playbook.yaml   # dev cases only
python -m eval.playbook review --pending eval/reflexion/pending.jsonl --decisions eval/reflexion/decisions.yaml --reviewer NAME
python -m eval.playbook freeze                                                   # before any held-out run
```

Golden and adversarial items must never reach Reflexion, the playbook or memory. Five guards enforce this:
1. **Held-out split.** These items are marked held-out, and Reflexion refuses them.
2. **Frozen playbook.** The runner refuses a held-out run unless the playbook is frozen.
3. **Canary.** Every held-out file carries a canary string. `eval.dataset.check` fails if any held-out id appears in prompts, lessons, the playbook or the memory stores, or if the canary appears anywhere outside `eval/dataset/`.
4. **No shared inputs.** No held-out input matches a tuning input.
5. **Lesson writes off.** Evaluation runs reject lesson writes.

## Where results come from

- **Shop twin.** Runs here use `scenario.py`, the shop twin. Twin results are always labelled "twin" and never mixed with live-shop results.
- **Live shop.** The final held-out evaluation runs against the live shop with real fault injection.
- **Small samples.** With 20 to 50 cases, a difference of a few cases is within run-to-run noise. Use repeats, and report the spread, before ranking configurations.

## Tests

```bash
python -m pytest tests/test_eval_dataset.py tests/test_reliability.py
```

Both test files run in CI with the rest of the suite. CI requires 100% coverage, and `eval/` is in scope: new code here needs tests.
