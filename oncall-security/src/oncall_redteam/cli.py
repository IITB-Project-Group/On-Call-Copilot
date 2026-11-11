"""redteam -- run the On-Call Copilot red-team suite.

redteam list
redteam run [--profile baseline|hardened|both] [--target PATH] [--out reports]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .attacks import CATALOG


def main(argv=None) -> None:
    os.environ.setdefault("COPILOT_LLM", "off")
    ap = argparse.ArgumentParser(prog="redteam")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("--profile", default="both", choices=["baseline", "hardened", "both"])
    r.add_argument("--target", default=os.getenv("ONCALL_COPILOT_REPO", "."))
    r.add_argument(
        "--baseline-target", default=None, help="repo snapshot for the baseline (default: --target)"
    )
    r.add_argument("--out", default="reports")
    r.add_argument("--only", default=None, help="comma-separated attack ids or id prefixes (e.g. HC-,DW-04)")
    r.add_argument(
        "--quick", action="store_true", help="skip the false-positive and clean-regression measurements"
    )
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for x in CATALOG:
            print(f"{x.id:<24} {x.severity:<8} {x.owasp:<6} {x.atlas:<14} {x.name}")
        return
    from .report import write
    from .runner import clean_regression, false_positive_rate, run_catalog
    from .live import is_live_repo

    profiles = ["baseline", "hardened"] if a.profile == "both" else [a.profile]
    sel = None
    if a.only:
        keys = [k.strip() for k in a.only.split(",") if k.strip()]
        sel = [x for x in CATALOG if any(x.id == k or x.id.startswith(k) for k in keys)]
        if not sel:
            ap.error(f"no attack matches --only {a.only}")
    runs, fp, clean = {}, {}, {}
    for p in profiles:
        tgt = Path(a.baseline_target or a.target) if p == "baseline" else Path(a.target)
        print(f"== {p} ({tgt}) target={'live incident API' if is_live_repo(tgt) else 'v2 reference'}")
        runs[p] = run_catalog(p, tgt, sel)
        if not a.quick:
            fp[p] = false_positive_rate(p, tgt)
            clean[p] = clean_regression(p, target_repo=tgt)
            print(
                f"  false positives: {fp[p]['false_positives']}/{fp[p]['lines']} (rate {fp[p]['rate']})  clean: {clean[p]}"
            )
    doc = write(Path(a.out), runs, fp, clean)
    for p, s in doc["summary"].items():
        print(
            f"{p:<9} ASR {s['asr']:.0%}  successful {s['successful']}/{s['attacks']}  risk {s['risk_score']}  {s['by_severity']}"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
