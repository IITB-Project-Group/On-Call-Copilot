"""Run one incident from the command line: the stop-and-resume demo, decisions, the diagram.

    python -m graph.cli diagram --arch c2 > docs/agents/graph-c2.mmd
    python -m graph.cli run --case dev-f1-50pct --arch c0 --workdir demo --crash-after assess
    python -m graph.cli resume --workdir demo                 # continues from the last checkpoint
    python -m graph.cli decide --workdir demo --decision approve --approver oncall --code ABCD1234
    python -m graph.cli status --workdir demo

The run uses the shop twin; its state, the checkpoints (SQLite) and the trace live in --workdir,
so ``resume`` in a new process continues exactly where the killed one stopped.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sqlite3
import sys
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agents.settings import Experiment
from eval.cases import load_cases
from eval.runner import ROSTER, build_twin_run
from eval.scenario import ShopTwin
from graph.incident_graph import build_graph


def _graph(workdir: Path, arch: str, case: dict | None = None, models=None):
    meta_path = workdir / "run.json"
    if case is not None:
        meta = {"case": case, "arch": arch, "incident_id": f"{case['id']}-demo", "twin": None}
    else:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    experiment = Experiment(name=f"cli-{meta['arch']}", architecture=meta["arch"], learn=False)
    twin, deps, incident_id = build_twin_run(
        meta["case"],
        experiment,
        models=models,
        traces_dir=str(workdir / "traces"),
        incident_id=meta["incident_id"],
    )
    if meta.get("twin"):
        restored = ShopTwin.from_dict(meta["twin"])
        twin.__dict__.update(restored.__dict__)
    approvals = workdir / "approvals.pkl"
    if approvals.exists():  # the approval service is in memory; the CLI keeps it between processes
        deps.approvals._requests, deps.approvals._rejections = pickle.loads(approvals.read_bytes())
    saver = SqliteSaver(sqlite3.connect(str(workdir / "checkpoints.sqlite3"), check_same_thread=False))
    return build_graph(deps, saver), deps, twin, meta, meta_path


def _save(meta: dict, twin: ShopTwin, deps, path: Path) -> None:
    path.write_text(json.dumps({**meta, "twin": twin.to_dict()}), encoding="utf-8")
    (path.parent / "approvals.pkl").write_bytes(
        pickle.dumps((deps.approvals._requests, deps.approvals._rejections))
    )


def _stream(graph, value, config, twin, meta, meta_path, crash_after: str | None, out, deps) -> None:
    for update in graph.stream(value, config, stream_mode="updates", durability="sync"):
        for node in update:
            print(f"step done: {node}", file=out)
            _save(meta, twin, deps, meta_path)
            if node == crash_after:  # pragma: no cover - ends the process like a kill would
                print(f"simulated crash after {node}; run `resume` to continue", file=out)
                out.flush()
                os._exit(3)
    _save(meta, twin, deps, meta_path)


def status(graph, config) -> dict:
    snapshot = graph.get_state(config)
    values = snapshot.values or {}
    pending = snapshot.interrupts[0].value if snapshot.interrupts else None
    return {
        "next": list(snapshot.next),
        "status": values.get("status"),
        "outcome": values.get("outcome"),
        "plan_version": (values.get("plan") or {}).get("version"),
        "pending": None
        if pending is None
        else {k: pending.get(k) for k in ("kind", "command", "confirmation_code")},
    }


def main(argv: list[str] | None = None, out=sys.stdout) -> int:
    parser = argparse.ArgumentParser(description="Run one incident graph from the command line")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("diagram")
    d.add_argument("--arch", default="c2", choices=("c0", "c1", "c2"))
    for name in ("run", "resume", "decide", "status"):
        p = sub.add_parser(name)
        p.add_argument("--workdir", required=True)
    run = sub.choices["run"]
    run.add_argument("--case", required=True)
    run.add_argument("--arch", default="c0", choices=("c0", "c1", "c2"))
    run.add_argument("--crash-after")
    sub.choices["resume"].add_argument("--crash-after")
    decide = sub.choices["decide"]
    decide.add_argument("--decision", required=True, choices=("approve", "reject", "edit"))
    decide.add_argument("--approver", default=ROSTER[0].approver_id)
    decide.add_argument("--code", default="")
    decide.add_argument("--text", default="")
    args = parser.parse_args(argv)

    if args.command == "diagram":
        case = load_cases("dev")[0]
        _, deps, _ = build_twin_run(case, Experiment(architecture=args.arch), models=object())
        print(build_graph(deps).get_graph().draw_mermaid(), file=out)
        return 0
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    case = next(c for c in load_cases("dev") if c["id"] == args.case) if args.command == "run" else None
    graph, deps, twin, meta, meta_path = _graph(workdir, getattr(args, "arch", "c0"), case)
    config = {"configurable": {"thread_id": meta["incident_id"]}}
    if args.command == "run":
        _stream(
            graph,
            {"incident_id": meta["incident_id"], "alert": twin.alert()},
            config,
            twin,
            meta,
            meta_path,
            args.crash_after,
            out,
            deps,
        )
    elif args.command == "resume":
        _stream(graph, None, config, twin, meta, meta_path, args.crash_after, out, deps)
    elif args.command == "decide":
        decision = {
            "decision": args.decision,
            "approver": args.approver,
            "confirmation": args.code,
            "text": args.text,
            "comms_approver": "incident-commander",
        }
        _stream(graph, Command(resume=decision), config, twin, meta, meta_path, None, out, deps)
    print(json.dumps(status(graph, config), indent=2), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
