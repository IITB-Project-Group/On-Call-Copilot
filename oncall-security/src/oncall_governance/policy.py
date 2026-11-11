"""Security policy as code and the release gate.

govern gate   -> exit 0 only if: required controls pass, red-team thresholds hold, no residual risk above the
                 limit, no secrets in the repository, detector false-positive rate within limit.
"""

from __future__ import annotations

from pathlib import Path

import yaml

SEV = ("critical", "high", "medium", "low")


def load_policy(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def gate(
    policy: dict, controls: list[dict], risks: list[dict], redteam_summary: dict, fp_rate: float | None
) -> dict:
    reasons = []
    st = {c["id"]: c["status"] for c in controls}
    for cid in policy.get("controls", {}).get("required", []):
        if st.get(cid) != "pass":
            reasons.append(f"required control {cid} is {st.get(cid, 'missing')}")
    limits = policy.get("redteam", {}).get("max_successful", {})
    for sev in SEV:
        got = int(str(redteam_summary.get("by_severity", {}).get(sev, "0/0")).split("/")[0])
        if got > limits.get(sev, 0):
            reasons.append(f"{got} successful {sev} attack(s) > limit {limits.get(sev, 0)}")
    import datetime as dt

    max_res = policy.get("risk", {}).get("max_residual_score", 8)
    accepted = []
    for r in risks:
        if r["residual"] > max_res:
            acc = policy.get("risk", {}).get("acceptances", {}).get(r["id"])
            valid = (
                acc
                and dt.date.fromisoformat(str(acc["until"])) >= dt.date.today()
                and acc.get("owner")
                and r["residual"] <= acc.get("max_residual", max_res)
                and not r["attacks_succeeded"]
            )
            if valid:
                accepted.append(
                    f"{r['id']} residual {r['residual']} ACCEPTED by {acc['owner']} until {acc['until']}: {acc['reason']}"
                )
            else:
                reasons.append(f"{r['id']} residual {r['residual']} > {max_res} ({r['risk']})")
    lim = policy.get("redteam", {}).get("max_false_positive_rate", 0.01)
    if fp_rate is None or fp_rate > lim:
        reasons.append(f"detector false-positive rate {fp_rate} > {lim}")
    return {"passed": not reasons, "reasons": reasons, "accepted_risks": accepted}
