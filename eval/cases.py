"""Load evaluation cases.

Development cases live in eval/cases/dev and are the only cases the agent is tuned on. Held-out
cases are written and kept by role 5 outside this repository's agent-readable paths; pass their
directory explicitly when role 5 runs the held-out evaluation.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CASES_DIR = Path(__file__).resolve().parent / "cases"
REQUIRED = ("id", "split", "inject", "alert", "ground_truth", "expected")


def load_cases(split: str = "dev", directory: str | Path | None = None) -> list[dict]:
    folder = Path(directory) if directory else CASES_DIR / split
    if not folder.is_dir():
        return []
    cases = []
    for path in sorted(folder.glob("*.yaml")):
        case = yaml.safe_load(path.read_text(encoding="utf-8"))
        missing = [key for key in REQUIRED if key not in case]
        if missing:
            raise ValueError(f"{path.name} is missing {missing}")
        if case["split"] != split:
            raise ValueError(f"{path.name} is marked {case['split']}, not {split}")
        cases.append(case)
    return cases
