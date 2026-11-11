"""govern -- security governance for the On-Call Copilot.

govern check  --profile baseline|hardened [--redteam reports/redteam_results.json]
govern gate   --profile hardened           (exit code 1 on failure; used in CI)
govern report                              (both profiles -> reports/GOVERNANCE_REPORT.md)
govern inventory | sbom | scan-secrets PATH | users  (generate API users + tokens)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .controls import Ctx, evaluate
from .policy import gate, load_policy
from .report import coverage, write
from .risk import assess

HERE = Path(__file__).resolve().parents[2]


def assess_profile(profile: str, target: Path, redteam_json: Path, policy: dict) -> dict:
    from . import protect

    (
        protect.install_runtime_protections()
        if profile == "hardened"
        else protect.uninstall_runtime_protections()
    )
    rt = json.loads(Path(redteam_json).read_text(encoding="utf-8"))
    res = {r["id"]: bool(r["success"]) for r in rt["results"].get(profile, [])}
    summ = rt["summary"].get(profile, {})
    fp = rt.get("false_positives", {}).get(profile, {}).get("rate")
    ctx = Ctx(
        profile,
        target,
        HERE,
        res,
        {"attacks": summ.get("attacks", 0), "profile": profile, "false_positive_rate": fp},
        policy,
    )
    controls = evaluate(ctx)
    risks = assess({c["id"]: c["status"] for c in controls}, res)
    return {
        "controls": controls,
        "risks": risks,
        "gate": gate(policy, controls, risks, summ, fp),
        "coverage": coverage(controls),
        "redteam_summary": summ,
    }


def main(argv=None) -> None:
    os.environ.setdefault("COPILOT_LLM", "off")
    ap = argparse.ArgumentParser(prog="govern")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "gate", "report"):
        p = sub.add_parser(name)
        p.add_argument("--profile", default="hardened", choices=["baseline", "hardened"])
        p.add_argument("--target", default=os.getenv("ONCALL_COPILOT_REPO", "."))
        p.add_argument("--baseline-target", default=None)
        p.add_argument("--redteam", default=str(HERE / "reports" / "redteam_results.json"))
        p.add_argument("--policy", default=str(HERE / "policy" / "security_policy.yaml"))
        p.add_argument("--out", default=str(HERE / "reports"))
    sub.add_parser("inventory")
    sub.add_parser("sbom")
    sub.add_parser("users")
    sv = sub.add_parser("serve")
    sv.add_argument("--users", default=str(HERE / "policy" / "users.yaml"))
    sv.add_argument("--policy", default=str(HERE / "policy" / "security_policy.yaml"))
    sv.add_argument("--audit", default="data/audit.jsonl")
    sv.add_argument("--port", type=int, default=8443)
    sv.add_argument("--target", default=os.getenv("ONCALL_COPILOT_REPO", "."))
    sv.add_argument("--db", default="data/incidents.sqlite3")
    sv.add_argument(
        "--dry-flags",
        action="store_true",
        help="log flag writes instead of calling flagd (no cluster needed)",
    )
    s = sub.add_parser("scan-secrets")
    s.add_argument("path")
    for name in ("pin-runbooks", "verify-runbooks"):
        pr = sub.add_parser(name)
        pr.add_argument("--target", default=os.getenv("ONCALL_COPILOT_REPO", "."))
        if name == "pin-runbooks":
            pr.add_argument("--reviewer", required=True, help="the person who reviewed the runbooks")
    a = ap.parse_args(argv)
    if a.cmd == "inventory":
        from .inventory import build_inventory

        print(json.dumps(build_inventory(), indent=1))
        return
    if a.cmd == "sbom":
        from .inventory import sbom

        print(json.dumps(sbom(), indent=1))
        return
    if a.cmd == "scan-secrets":
        from .protect.secrets_scan import scan

        r = scan(Path(a.path))
        print(json.dumps(r["real_findings"], indent=1))
        sys.exit(0 if r["clean"] else 1)
    if a.cmd in ("pin-runbooks", "verify-runbooks"):
        from .controls import RUNBOOK_MANIFEST
        from .protect.integrity import pin_markdown_runbooks, verify_markdown_runbooks

        t = Path(a.target)
        if a.cmd == "pin-runbooks":
            doc = pin_markdown_runbooks(t / "knowledge" / "runbooks", t / RUNBOOK_MANIFEST, a.reviewer)
            print(
                f"pinned {len(doc['runbooks'])} runbooks -> {t / RUNBOOK_MANIFEST} (reviewed by {a.reviewer})"
            )
            return
        r = verify_markdown_runbooks(t / "knowledge" / "runbooks", t / RUNBOOK_MANIFEST)
        for k, v in r.items():
            print(f"  {v:<9} {k}")
        bad = [k for k, v in r.items() if v != "ok"]
        print("no manifest" if not r else ("OK" if not bad else f"FAILED: {bad}"))
        sys.exit(0 if r and not bad else 1)
    if a.cmd == "serve":  # hardened production service
        import uvicorn
        from . import protect
        from .protect.auth import UserStore
        from .protect.secure_app import build_hardened_app

        protect.install_runtime_protections()
        Path(a.audit).parent.mkdir(parents=True, exist_ok=True)
        store = UserStore.from_yaml(a.users)
        from oncall_redteam.live import ensure_paths, is_live_repo

        if is_live_repo(Path(a.target)):  # live product: wrap incident_api (audit lives next to the DB)
            if not os.getenv("COPILOT_WEBHOOK_SECRET"):
                print(
                    "WARNING: COPILOT_WEBHOOK_SECRET is unset; /webhooks/alert will answer 503 (fail closed)"
                )
            ensure_paths(Path(a.target))
            from .protect.live_app import build_hardened_incident_app

            Path(a.db).parent.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("INCIDENT_DB", str(Path(a.db).resolve()))
            writer = None
            if a.dry_flags:

                def writer(flag="paymentFailure", variant="off"):
                    print(f"[dry-flags] would set {flag} = {variant}", flush=True)
                    return f"{flag} is {variant} (dry run)"

            uvicorn.run(
                build_hardened_incident_app(
                    store, load_policy(Path(a.policy)), db_path=str(Path(a.db).resolve()), write_flag=writer
                ),
                host="0.0.0.0",
                port=a.port,
            )
            return
        app = build_hardened_app(store, load_policy(Path(a.policy)), audit_path=a.audit)
        app.state.monitor.store = store
        uvicorn.run(app, host="0.0.0.0", port=a.port)
        return
    if a.cmd == "users":
        from .protect.auth import DEFAULT_TEAM, UserStore

        store, toks = UserStore.generate(DEFAULT_TEAM)
        import yaml

        Path(HERE / "policy" / "users.yaml").write_text(
            yaml.safe_dump(
                {
                    "users": [
                        {"id": u.user_id, "roles": sorted(u.roles), "token_sha256": u.token_sha256}
                        for u in store.users.values()
                    ]
                }
            ),
            encoding="utf-8",
        )
        print("wrote policy/users.yaml (hashes only). Tokens -- shown ONCE, hand each person their own:")
        for k, v in toks.items():
            print(f"  {k:<13} {v}")
        return
    policy = load_policy(Path(a.policy))
    if a.cmd == "report":
        res = {
            "profiles": {
                p: assess_profile(
                    p,
                    Path(a.baseline_target or a.target) if p == "baseline" else Path(a.target),
                    Path(a.redteam),
                    policy,
                )
                for p in ("baseline", "hardened")
            }
        }
        write(Path(a.out), res)
        for p, r in res["profiles"].items():
            from collections import Counter

            c = Counter(x["status"] for x in r["controls"])
            print(
                f"{p:<9} controls pass={c.get('pass', 0)} partial={c.get('partial', 0)} fail={c.get('fail', 0)}  gate={'PASSED' if r['gate']['passed'] else 'FAILED'} ({len(r['gate']['reasons'])} reasons)"
            )
        return
    r = assess_profile(a.profile, Path(a.target), Path(a.redteam), policy)
    for c in r["controls"]:
        print(f"{c['id']:<7} {c['status']:<8} {c['title'][:55]:<55} {c['evidence'][:60]}")
    print("GATE", "PASSED" if r["gate"]["passed"] else "FAILED", *r["gate"]["reasons"], sep="\n  ")
    if a.cmd == "gate":
        sys.exit(0 if r["gate"]["passed"] else 1)


if __name__ == "__main__":  # pragma: no cover
    main()
