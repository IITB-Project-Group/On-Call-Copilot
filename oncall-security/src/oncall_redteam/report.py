"""Red-team report writer: JSON, SARIF and Markdown."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .attacks import CATALOG
from .runner import summarize, to_sarif


def write(out: Path, runs: dict, fp: dict, clean: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    summ = {p: summarize(rs) for p, rs in runs.items()}
    doc = {"summary": summ, "false_positives": fp, "clean_regression": clean,
           "results": {p: [asdict(r) for r in rs] for p, rs in runs.items()},
           "catalog": [{"id": a.id, "name": a.name, "category": a.category, "owasp": a.owasp, "atlas": a.atlas,
                        "severity": a.severity, "layer": a.layer, "description": a.description,
                        "remediation": a.remediation} for a in CATALOG]}
    (out / "redteam_results.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    for p, rs in runs.items():
        (out / f"redteam_{p}.sarif").write_text(json.dumps(to_sarif(rs), indent=1), encoding="utf-8")
    md = ["# Red-team report: On-Call Copilot", "",
          "| Profile | Attacks | Successful | ASR | Risk score | Critical | High | Medium | Low | Errors |", "|---|---|---|---|---|---|---|---|---|---|"]
    for p, s in summ.items():
        sev = s["by_severity"]
        md.append(f"| {p} | {s['attacks']} | {s['successful']} | {s['asr']:.0%} | {s['risk_score']}/{s['max_risk_score']} | "
                  f"{sev.get('critical', '-')} | {sev.get('high', '-')} | {sev.get('medium', '-')} | {sev.get('low', '-')} | {s['errors']} |")
    md += ["", "## Results per attack", "", "| ID | Attack | Sev | OWASP | " + " | ".join(runs) + " |", "|---|---|---|---|" + "---|" * len(runs)]
    idx = {p: {r.id: r for r in rs} for p, rs in runs.items()}
    for a in CATALOG:
        cells = []
        for p in runs:
            r = idx[p].get(a.id)
            cells.append("—" if r is None else ("**SUCCESS**" if r.success else ("error" if r.error else "blocked")))
        md.append(f"| {a.id} | {a.name} | {a.severity} | {a.owasp} | " + " | ".join(cells) + " |")
    md += ["", "## Detector false positives on benign shop telemetry", ""] + [f"- {p}: {v}" for p, v in fp.items()]
    md += ["", "## Legitimate work under each profile (clean held-out incidents)", ""] + [f"- {p}: {v}" for p, v in clean.items()]
    (out / "REDTEAM_REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return doc
