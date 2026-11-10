"""Reflexion on development cases (L12): agent -> evaluator -> reflection -> lessons for review.

    python -m eval.reflexion --experiment eval/experiments/e3-c2-no-playbook.yaml --out eval/reflexion

1. The team (C2) runs each development case.
2. The evaluator is code: it compares the diagnosis and the action with the injected fault
   (``score_diagnosis``, ``classify_action``) and checks verified recovery.
3. For each failure, the reflection model writes one lesson and the observable conditions under
   which it applies.
4. Lessons go to ``pending.jsonl``. Nothing is stored until a person reviews them
   (``python -m eval.playbook review``); the playbook is then frozen before the held-out run.

Only development cases are used. The evaluator's feedback names the injected fault, which is the
learning signal; lessons must be stated as observable preconditions, never as case ids.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hooks import GuardedExecutor, HookManager, default_hooks
from input_guardrails import InputGuardrails

from agents.handoffs import LessonDraft
from agents.llm import ModelFactory
from agents.react import run_react
from agents.settings import Experiment, load_config, load_experiment, render_prompt
from eval.cases import load_cases
from eval.runner import run_case


def feedback_for(case: dict, row: dict) -> str:
    """The evaluator's verdict in words. Code decides; no judge is needed for these checks."""
    faults = case["ground_truth"].get("faults") or []
    truth = (
        "; ".join(f"{f['service']} {f['fault_type']} (fix {f['fix']['args']})" for f in faults) or "no fault"
    )
    got = (
        "; ".join(
            f"{h['service']} {h['fault_type']} {h.get('flag') or ''} [{h['status']}]"
            for h in row.get("top_hypotheses") or []
        )
        or "no hypothesis"
    )
    parts = [
        f"Injected: {truth}.",
        f"Diagnosis: {got}.",
        f"Actions proposed: {row.get('actions')}.",
        f"Correct action: {row.get('correct_action')}. Verified recovery: {row.get('verified_recovery')}.",
        f"Harmful actions: {row.get('harmful_actions')}. Outcome: {row.get('outcome')}. Error: {row.get('error')}.",
    ]
    return " ".join(parts)


def trajectory(traces_dir: Path, incident_id: str | None, limit: int = 3000) -> str:
    if not incident_id:
        return "no trace"
    path = traces_dir / f"{incident_id}.jsonl"
    if not path.exists():
        return "no trace"
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(raw)
        if event["kind"] in (
            "plan",
            "tool_call",
            "assess",
            "proposal",
            "proposal_blocked",
            "verification",
            "escalate",
        ):
            lines.append(
                json.dumps({k: v for k, v in event.items() if k not in ("ts", "incident")}, default=str)[:300]
            )
    text = "\n".join(lines)
    return text[-limit:]


def reflect(feedback: str, steps: str, models, config: dict) -> LessonDraft | None:
    executor = GuardedExecutor(HookManager(default_hooks(input_guardrails=InputGuardrails())), {})

    class NoTools:
        def schemas(self):
            return []

        def call(self, name, args):  # pragma: no cover - the reflection step has no tools
            return "{}"

    result = run_react(
        role="reflection",
        model=models.get("reflection"),
        model_id=models.model_id("reflection"),
        executor=executor,
        incident_id="reflection",
        system=render_prompt("reflection", {"feedback": feedback, "trajectory": steps}, config),
        task="Write one lesson and submit it.",
        toolset=NoTools(),
        submit=LessonDraft,
        max_steps=3,
    )
    return result.output


def run_reflexion(
    experiment: Experiment,
    cases: list[dict],
    out_dir: str | Path,
    *,
    models=None,
    results: str | Path | None = None,
    traces_dir: str | Path | None = None,
) -> list[dict]:
    """Reflect on each failed development case. With ``results`` (a runner JSONL and its traces),
    the cases already run are reused instead of being run again."""
    if any(case["split"] != "dev" for case in cases):
        raise ValueError("Reflexion runs on development cases only")
    if any(case.get("canary") or case.get("source") in ("golden", "adversarial") for case in cases):
        raise ValueError("Golden and adversarial cases never feed Reflexion (eval/dataset/README.md)")
    config = load_config()
    out = Path(out_dir)
    traces = Path(traces_dir) if traces_dir else out / "traces"
    models = models or ModelFactory(experiment, config)
    done = {}
    if results:
        rows = [json.loads(line) for line in Path(results).read_text(encoding="utf-8").splitlines() if line]
        done = {row["case"]: row for row in rows if row.get("repeat", 0) == 0}
    pending = []
    for case in cases:
        row = done.get(case["id"]) or run_case(case, experiment, models=models, traces_dir=str(traces))
        if row.get("success"):
            continue
        feedback = feedback_for(case, row)
        draft = reflect(feedback, trajectory(traces, row.get("incident_id")), models, config)
        pending.append(
            {
                "id": f"lesson-{case['id']}",
                "case": case["id"],
                "feedback": feedback,
                "draft": None if draft is None else draft.model_dump(),
                "status": "pending",
            }
        )
    out.mkdir(parents=True, exist_ok=True)
    (out / "pending.jsonl").write_text("".join(json.dumps(p) + "\n" for p in pending), encoding="utf-8")
    return pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reflexion on development cases")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--out", default="eval/reflexion")
    parser.add_argument("--results", help="Reuse a runner JSONL on the dev split instead of re-running it.")
    parser.add_argument("--traces", help="Trace directory of that run.")
    args = parser.parse_args(argv)
    pending = run_reflexion(
        load_experiment(args.experiment),
        load_cases("dev"),
        args.out,
        results=args.results,
        traces_dir=args.traces,
    )
    print(f"{len(pending)} lesson(s) waiting for review in {args.out}/pending.jsonl")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
