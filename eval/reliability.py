"""pass@k and pass^k: capability versus reliability (Lecture 13, section 3.2).

Run each case k or more times, then:

* pass^1  the average single run: the share of runs that succeed.
* pass@k  the case succeeds on at least one of k runs. How good can the agent be?
* pass^k  the case succeeds on all k runs. How reliable is it? This is the tau-bench metric, and
          the one the on-call engineer feels: a fix that works two nights in three is not a fix.

With n runs of a case, c of them successful, the unbiased estimators are

    pass@k = 1 - C(n-c, k) / C(n, k)        pass^k = C(c, k) / C(n, k)

averaged over cases. With n == k they reduce to "any" and "all". The gap pass@k - pass^k is the
unreliability you would ship. A failed or errored run counts as a failure: the engineer got no fix.

    python -m eval.runner --experiment eval/experiments/e1-c2-team.yaml --split heldout \\
        --cases-dir eval/dataset/golden --repeats 3 --temperature 0.7 --out eval/results/rel/golden.jsonl
    python -m eval.reliability eval/results/rel/golden.jsonl --k 3
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from math import comb
from pathlib import Path

SOURCE_PREFIX = {"prod-": "production", "gold-": "golden", "adv-": "adversarial", "reg-": "regression"}


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that at least one of k runs drawn from the n succeeds."""
    if not 0 <= c <= n or not 1 <= k <= n:
        raise ValueError(f"need 0 <= c <= n and 1 <= k <= n, got n={n} c={c} k={k}")
    return 1.0 if n - c < k else 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Probability that all k runs drawn from the n succeed."""
    if not 0 <= c <= n or not 1 <= k <= n:
        raise ValueError(f"need 0 <= c <= n and 1 <= k <= n, got n={n} c={c} k={k}")
    return comb(c, k) / comb(n, k)


def source_of(case_id: str) -> str:
    return next((s for p, s in SOURCE_PREFIX.items() if case_id.startswith(p)), "dev")


def outcomes(rows: list[dict]) -> dict[str, dict[str, list[bool]]]:
    """experiment -> case -> successes in repeat order. A later row for the same run replaces an
    earlier one (a resumed run), so each (experiment, case, repeat) counts once."""
    runs: dict[tuple[str, str], dict[int, bool]] = defaultdict(dict)
    for row in rows:
        runs[(row.get("experiment", "?"), row["case"])][int(row.get("repeat", 0))] = bool(row.get("success"))
    out: dict[str, dict[str, list[bool]]] = defaultdict(dict)
    for (experiment, case), by_repeat in sorted(runs.items()):
        out[experiment][case] = [by_repeat[r] for r in sorted(by_repeat)]
    return dict(out)


def _scores(per_case: dict[str, list[bool]], k: int) -> dict:
    scored = {case: runs for case, runs in per_case.items() if len(runs) >= k}
    if not scored:
        return {"cases": 0}
    n_cases = len(scored)

    def mean(fn) -> float:
        return sum(fn(len(r), sum(r)) for r in scored.values()) / n_cases

    at_k, hat_k = mean(lambda n, c: pass_at_k(n, c, k)), mean(lambda n, c: pass_hat_k(n, c, k))
    return {
        "cases": n_cases,
        "runs": sum(len(r) for r in scored.values()),
        "pass_hat_1": round(mean(lambda n, c: c / n), 3),
        f"pass_at_{k}": round(at_k, 3),
        f"pass_hat_{k}": round(hat_k, 3),
        "gap": round(at_k - hat_k, 3),
    }


def report(rows: list[dict], k: int = 3) -> dict:
    """Reliability per experiment: overall, by dataset source, the flaky cases (some runs pass,
    some fail) and the cases with too few runs."""
    out = {}
    for experiment, per_case in outcomes(rows).items():
        by_source: dict[str, dict[str, list[bool]]] = defaultdict(dict)
        for case, runs in per_case.items():
            by_source[source_of(case)][case] = runs
        out[experiment] = {
            "k": k,
            **_scores(per_case, k),
            "by_source": {s: _scores(cases, k) for s, cases in sorted(by_source.items())},
            "flaky": {
                case: "".join("✓" if ok else "✗" for ok in runs)
                for case, runs in per_case.items()
                if len(runs) >= k and 0 < sum(runs) < len(runs)
            },
            "too_few_runs": {case: len(runs) for case, runs in per_case.items() if len(runs) < k},
        }
    return out


def read_rows(paths: list[str | Path]) -> list[dict]:
    rows = []
    for path in paths:
        rows += [
            json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()
        ]
    return rows


def render(result: dict) -> str:
    lines = []
    for experiment, r in result.items():
        k = r["k"]
        lines.append(f"{experiment}: {r.get('cases', 0)} cases, {r.get('runs', 0)} runs, k = {k}")
        if not r.get("cases"):
            lines.append(f"  no case has {k} runs; rerun with --repeats {k}")
            continue
        lines.append(
            f"  {'source':<12} {'cases':>5} {'pass^1':>7} {f'pass@{k}':>7} {f'pass^{k}':>7} {'gap':>6}"
        )
        for source, s in [("ALL", r)] + list(r["by_source"].items()):
            if s.get("cases"):
                lines.append(
                    f"  {source:<12} {s['cases']:>5} {s['pass_hat_1']:>7.2f} {s[f'pass_at_{k}']:>7.2f}"
                    f" {s[f'pass_hat_{k}']:>7.2f} {s['gap']:>6.2f}"
                )
        if r["flaky"]:
            lines.append(f"  flaky ({len(r['flaky'])}): passes some runs, fails others")
            lines += [f"    {pattern}  {case}" for case, pattern in r["flaky"].items()]
        if r["too_few_runs"]:
            lines.append(f"  left out, fewer than {k} runs: {', '.join(sorted(r['too_few_runs']))}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pass@k and pass^k from runner JSONL files.")
    parser.add_argument("results", nargs="+", help="Runner JSONL files (made with --repeats k or more).")
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--out", help="Also write the report as JSON.")
    args = parser.parse_args(argv)
    result = report(read_rows(args.results), args.k)
    print(render(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
