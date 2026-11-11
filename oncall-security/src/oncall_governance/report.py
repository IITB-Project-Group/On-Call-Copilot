"""Governance report: control status, framework coverage, risk register, gate."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


def write(out: Path, results: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "governance_results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    md = ["# Security governance report: On-Call Copilot", ""]
    for prof, r in results["profiles"].items():
        c = Counter(x["status"] for x in r["controls"])
        md += [f"## Profile: {prof}", "", f"Controls: {c.get('pass', 0)} pass, {c.get('partial', 0)} partial, {c.get('fail', 0)} fail "
               f"of {len(r['controls'])}. Gate: **{'PASSED' if r['gate']['passed'] else 'FAILED'}**", ""]
        md += ["| Control | Title | Status | Evidence | Attacks that succeeded |", "|---|---|---|---|---|"]
        md += [f"| {x['id']} | {x['title']} | {x['status']} | {x['evidence'][:80]} | {', '.join(x['attacks_succeeded']) or '-'} |"
               for x in r["controls"]]
        md += ["", "| Risk | Inherent | Residual | Attacks that succeeded |", "|---|---|---|---|"]
        md += [f"| {x['id']} {x['risk']} | {x['inherent']} ({x['inherent_band']}) | {x['residual']} ({x['residual_band']}) | "
               f"{', '.join(x['attacks_succeeded']) or '-'} |" for x in r["risks"]]
        if r["gate"]["reasons"]:
            md += ["", "Gate failures:"] + [f"- {x}" for x in r["gate"]["reasons"]]
        md.append("")
    (out / "GOVERNANCE_REPORT.md").write_text("\n".join(md), encoding="utf-8")


def coverage(controls: list[dict]) -> dict:
    fw = defaultdict(set)
    for c in controls:
        for k in str(c["owasp"]).replace("/", " ").split():
            if k.startswith("LLM"):
                fw["owasp"].add(k)
        fw["nist"].add(c["domain"])
    return {k: sorted(v) for k, v in fw.items()}
