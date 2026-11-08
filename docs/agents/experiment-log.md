# Experiment Log (role 3)

One entry per run or change that affects results. Config version refers to `agents/config/agents.yaml`.

| Date | Config | What | Result / note |
| --- | --- | --- | --- |
| 2026-11-07 | 2026-11-07.1 | Initial agent config: commander `openai/gpt-4.1`, specialists `openai/gpt-4.1-mini`, judge `google/gemini-3.1-flash-lite`; investigation budget 10 (split 30/50/20), reserve 14 calls for the action and verification, cost cap $0.50 per incident, replan cap 3 | Baseline config |
| 2026-11-07 | 2026-11-07.1 | Verification changed from 3 fixed samples to sampling through the window until 3 consecutive samples hold | The first sample after a flag change still shows the old error rate (the effect fades one sample later); 3 fixed samples failed every correct fix |
| 2026-11-07 | 2026-11-07.1 | Two-fault cases: the diagnosis given to `validate_plan` drops already-resolved hypotheses and re-ranks | Second fix was refused as `not_top_hypothesis` |
| 2026-11-07 | 2026-11-07.1 | Metric results reach the model compacted to service, value and evidence id | Full JSON was truncated at the context limit and could not be read |
| 2026-11-07 | 2026-11-07.1 | A no-fault verdict that cites no gathered evidence escalates instead of closing | `validate_diagnosis` flags it as `ungrounded_no_fault`; closing would hide a possible fault |
| 2026-11-07 | 2026-11-07.1 | E1 C0 on the twin, dev split, 3 repeats (60 runs) | Success 1.00, harmful 0, severity 0.90; 2 severity mismatches on startup-window cases (case vs policy question for role 1). `eval/results/twin/e1-c0-fixed.summary.json` |
| 2026-11-08 | 2026-11-07.1 | First real-model smoke runs: C2 on dev-f1-50pct (OpenRouter, gpt-4.1 commander, gpt-4.1-mini specialists). Judge price in the config corrected to OpenRouter's listed $0.25 / $1.50 per million tokens | Run 1 halted with `too_many_blocked_attempts`: once their share of the budget was spent, specialists kept calling tools, and every hook refusal counted toward the halt. Fixed: the toolset refuses over-budget calls itself, and the triage record update runs as the commander |
| 2026-11-08 | 2026-11-07.1 | Run 2 of the same case | The guardrails refused an action that did not target the hypothesised service (`target_mismatch`); the team replanned, fixed paymentFailure and verified recovery (samples 0.5, 0.002, 0.002, 0.002). Then a second hypothesis blaming the same flag led to proposing the same fix again, and the loop detector halted the run. Fixed: after a verified fix, hypotheses naming the fixed flag count as resolved. Cost $0.021 |
| 2026-11-08 | 2026-11-07.1 | Model wrote `copilot:service_p95_latency_seconds` without the `:2m` window | A metric name without its suffix now resolves when exactly one catalogue metric matches |
| 2026-11-08 | 2026-11-07.1 | Parallel diagnosis budget split | 5 calls over 3 diagnosers gave 1 each and lost 2 to integer division; the remainder now goes to the top suspects (2, 2, 1) |
| 2026-11-08 | 2026-11-07.1 | Run 3 stopped: OpenRouter HTTP 402, account credits 0 (the $50 on the key is a spending limit, not credit) | Waiting for credits. Total model spend so far about $0.13 |
| pending | 2026-11-07.1 | E1 C1, C2, C2 single investigator on the twin, dev, 3 repeats | Needs OpenRouter credits |
| pending | 2026-11-07.1 | E4 memory on/off × budget 5/10/20 on the twin, dev, 3 repeats | Needs OPENROUTER_API_KEY |
| pending | 2026-11-07.1 | Reflexion on dev, review, freeze playbook v1 | Needs OPENROUTER_API_KEY and a reviewer |
