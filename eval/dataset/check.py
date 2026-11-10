"""Validate the evaluation dataset. Exit code 1 if any check fails, so CI can gate on it.

    python -m eval.dataset.check

1. In sync. The files on disk are exactly what ``eval.dataset.build`` produces now. This catches a
   hand-edited label, a missing or extra file, and a dataset left stale after new runs were
   recorded or the severity policy changed. Labels are derived by the build, so "in sync" also
   means every label follows the written policy and the fault catalogue.
2. Split. Production, golden and adversarial are 50/30/20.
3. Runnable. Every case builds a shop twin and answers every read tool.
4. Traces. Every production and regression item points at a recorded trace that exists.
5. Leakage (golden and adversarial must never reach the improvement loop):
   a. no held-out input is the same as a development, production or regression input;
   b. no held-out id appears anywhere the agent, Reflexion, the playbook or memory reads or
      writes (prompts, knowledge/, eval/reflexion/, eval/cases/, experiments), including inside
      the SQLite memory stores, which are scanned as bytes;
   c. the canary string appears nowhere in the repository outside eval/dataset.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from eval.dataset import build as B

HELD_OUT = ("golden", "adversarial")
# Everything the agent, Reflexion, the playbook and memory read or write.
IMPROVEMENT_SURFACES = (
    "agents",
    "knowledge",
    "graph",
    "eval/reflexion",
    "eval/cases",
    "eval/experiments",
    "docs/agents/playbook.md",
)
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}


def load(folder: Path | None = None) -> dict:
    """The dataset as it is on disk: the manifest and every item, by source."""
    folder = folder or B.HERE
    data = {
        source: [
            yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((folder / source).glob("*.yaml"))
        ]
        for source in B.SOURCES
    }
    data["manifest"] = yaml.safe_load((folder / "manifest.yaml").read_text(encoding="utf-8"))
    return data


def files_under(base: Path, skip: Path | None = None):
    if base.is_file():
        yield base
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and Path(dirpath) / d != skip]
        yield from (f for f in (Path(dirpath) / name for name in filenames) if f.is_file())


def in_sync(data: dict) -> list[str]:
    fresh = B.cases()
    problems = [] if data["manifest"] == B.manifest(fresh) else ["manifest.yaml differs from a fresh build"]
    for source in B.SOURCES:
        want = {c["id"]: c for c in fresh[source]}
        have = {c["id"]: c for c in data[source]}
        problems += [f"{source}/{i}: built but not on disk" for i in want.keys() - have.keys()]
        problems += [f"{source}/{i}: on disk but not built" for i in have.keys() - want.keys()]
        problems += [
            f"{source}/{i}: differs from a fresh build"
            for i in want.keys() & have.keys()
            if want[i] != have[i]
        ]
    return sorted(problems)


def split(data: dict) -> list[str]:
    counts = {s: len(data[s]) for s in B.TARGET}
    total = sum(counts.values()) or 1
    return [
        f"{s}: {counts[s]} of {total} is {counts[s] / total:.0%}, needs {B.TARGET[s]}%"
        for s in B.TARGET
        if abs(100 * counts[s] / total - B.TARGET[s]) > 1
    ]


def runnable(data: dict) -> list[str]:
    from eval.scenario import ShopTwin

    problems = []
    for source in B.SOURCES:
        for case in data[source]:
            try:
                tools = ShopTwin(case).tools()
                tools["promql_query"]("copilot:service_error_ratio:5m")
                tools["log_search"]("otel-logs-*", "*", "now-15m", "now")
                tools["trace_search"](case["alert"]["service"], 900)
                tools["recent_changes"](900)
            except Exception as exc:  # noqa: BLE001 - any failure means the case cannot run
                problems.append(f"{source}/{case.get('id')}: {type(exc).__name__}: {exc}")
    return problems


def traces(data: dict) -> list[str]:
    paths = [(c["id"], c["trace"]["path"]) for c in data["production"]]
    paths += [(c["id"], p) for c in data["regression"] for p in c["regression"]["seen_in"]]
    return [f"{cid}: missing trace {p}" for cid, p in paths if not (B.ROOT / p).is_file()]


def shared_inputs(data: dict) -> list[str]:
    from eval.cases import load_cases

    seen: dict[str, str] = {}
    for case in load_cases("dev") + data["production"] + data["regression"]:
        seen.setdefault(B.signature(case), case["id"])
    problems = []
    for source in HELD_OUT:
        for case in data[source]:
            sig = B.signature(case)
            if sig in seen:
                problems.append(f"{case['id']}: same input as {seen[sig]}")
            seen.setdefault(sig, case["id"])
    return problems


def leaked_ids(data: dict, root: Path) -> list[str]:
    needles = [c["id"].encode() for s in HELD_OUT for c in data[s]]
    return [
        f"{file.relative_to(root)} contains {needle.decode()}"
        for rel in IMPROVEMENT_SURFACES
        for file in files_under(root / rel)
        for blob in [file.read_bytes()]
        for needle in needles
        if needle in blob
    ]


def leaked_canary(root: Path) -> list[str]:
    canary = B.CANARY.encode()
    return [str(f.relative_to(root)) for f in files_under(root, skip=B.HERE) if canary in f.read_bytes()]


def run(data: dict | None = None, root: Path | None = None) -> dict[str, list[str]]:
    """Every check by name, with the problems it found (an empty list means it passed).
    ``root`` is where the leakage scans look; it defaults to the repository."""
    data, root = data or load(), root or B.ROOT
    return {
        "in sync: files on disk are what the build produces": in_sync(data),
        "split: production/golden/adversarial is 50/30/20": split(data),
        "runnable: every case drives the shop twin": runnable(data),
        "traces: production and regression items point at recorded runs": traces(data),
        "leakage: no golden or adversarial input is also a tuning input": shared_inputs(data),
        "leakage: no held-out id in prompts, playbook, lessons or memory": leaked_ids(data, root),
        "leakage: the canary appears only inside eval/dataset": leaked_canary(root),
    }


def main() -> int:
    results = run()
    for name, problems in results.items():
        print(f"{'FAIL' if problems else 'PASS'}  {name}")
        for problem in problems:
            print(f"        {problem}")
    failed = sum(1 for problems in results.values() if problems)
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
