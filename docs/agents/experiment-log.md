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
| pending | 2026-11-07.1 | E1 C1, C2, C2 single investigator on the twin, dev, 3 repeats | Needs OPENROUTER_API_KEY |
| pending | 2026-11-07.1 | E4 memory on/off × budget 5/10/20 on the twin, dev, 3 repeats | Needs OPENROUTER_API_KEY |
| pending | 2026-11-07.1 | Reflexion on dev, review, freeze playbook v1 | Needs OPENROUTER_API_KEY and a reviewer |
