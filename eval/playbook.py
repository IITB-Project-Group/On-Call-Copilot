"""Review, freeze and check the playbook of lessons.

    python -m eval.playbook review --pending eval/reflexion/pending.jsonl --decisions decisions.yaml --reviewer NAME
    python -m eval.playbook freeze
    python -m eval.playbook check

``decisions.yaml`` maps each pending lesson id to ``approve`` or ``reject: <reason>``. Approved
lessons must pass ``validate_memory_write`` (a human reviewer, preconditions, known service and
fault type). Rejected lessons are kept with their reason; the submission shows at least one.
Freezing writes the playbook's hash; held-out runs refuse an unfrozen or changed playbook.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
from output_guardrails import validate_memory_write

from agents.memory.lessons import PLAYBOOK_DIR

PLAYBOOK = PLAYBOOK_DIR / "playbook.yaml"
REJECTED = PLAYBOOK_DIR / "rejected.yaml"
LOCK = PLAYBOOK_DIR / "playbook.lock.json"


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("lessons", [])


def _write(path: Path, lessons: list[dict], header: str) -> None:
    path.write_text(
        header + yaml.safe_dump({"lessons": lessons}, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def review(
    pending: list[dict],
    decisions: dict[str, str],
    reviewer: str,
    *,
    playbook: Path | None = None,
    rejected: Path | None = None,
    now: str | None = None,
) -> dict:
    playbook, rejected = playbook or PLAYBOOK, rejected or REJECTED
    if LOCK.exists() and playbook == PLAYBOOK:
        raise ValueError(
            "the playbook is frozen; unfreeze only by a team decision recorded in the experiment log"
        )
    approved, refused = _load(playbook), _load(rejected)
    stamp = now or datetime.now(timezone.utc).isoformat()
    results = {"approved": [], "rejected": [], "invalid": [], "undecided": []}
    for item in pending:
        decision = str(decisions.get(item["id"], "")).strip()
        draft = item.get("draft")
        if not decision or draft is None:
            results["undecided"].append(item["id"])
            continue
        lesson = {
            "id": item["id"],
            **draft,
            "reviewed_by": reviewer,
            "created_at": stamp,
            "source": item["case"],
        }
        if decision.lower() == "approve":
            check = validate_memory_write(lesson, frozen=False, incident_outcome="verified_failure")
            if check.blocked:
                results["invalid"].append({"id": item["id"], "codes": sorted(check.codes)})
                continue
            approved.append(lesson)
            results["approved"].append(item["id"])
        else:
            reason = decision.split(":", 1)[1].strip() if ":" in decision else "rejected"
            refused.append({**lesson, "rejected_reason": reason})
            results["rejected"].append(item["id"])
    _write(
        playbook,
        approved,
        "# Reviewed lessons from Reflexion on development cases. Frozen before held-out.\n",
    )
    _write(
        rejected, refused, "# Lessons a reviewer rejected, with the reason. Kept as evidence; never loaded.\n"
    )
    return results


def freeze(playbook: Path | None = None, lock: Path | None = None) -> dict:
    playbook, lock = playbook or PLAYBOOK, lock or LOCK
    digest = hashlib.sha256(playbook.read_bytes()).hexdigest()
    record = {
        "playbook": playbook.name,
        "sha256": digest,
        "lessons": len(_load(playbook)),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
    }
    lock.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def check(playbook: Path | None = None, lock: Path | None = None) -> bool:
    playbook, lock = playbook or PLAYBOOK, lock or LOCK
    if not lock.exists() or not playbook.exists():
        return False
    return (
        json.loads(lock.read_text(encoding="utf-8"))["sha256"]
        == hashlib.sha256(playbook.read_bytes()).hexdigest()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review, freeze and check the playbook")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("review")
    r.add_argument("--pending", required=True)
    r.add_argument("--decisions", required=True)
    r.add_argument("--reviewer", required=True)
    sub.add_parser("freeze")
    sub.add_parser("check")
    args = parser.parse_args(argv)
    if args.command == "review":
        pending = [
            json.loads(line) for line in Path(args.pending).read_text(encoding="utf-8").splitlines() if line
        ]
        decisions = yaml.safe_load(Path(args.decisions).read_text(encoding="utf-8")) or {}
        print(json.dumps(review(pending, decisions, args.reviewer), indent=2))
    elif args.command == "freeze":
        print(json.dumps(freeze(), indent=2))
    else:
        ok = check()
        print("playbook frozen and unchanged" if ok else "playbook is not frozen, or changed since freezing")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
