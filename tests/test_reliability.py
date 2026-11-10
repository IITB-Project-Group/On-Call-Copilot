"""pass@k and pass^k (eval.reliability), the temperature override, and the runner's reliability summary."""

from __future__ import annotations

from itertools import combinations

import pytest

from agents.settings import Experiment, load_config
from eval.reliability import pass_at_k, pass_hat_k, render, report


def brute(n: int, c: int, k: int) -> tuple[float, float]:
    """Over every k-subset of n runs (c successes): share with any success, share with all."""
    runs = [True] * c + [False] * (n - c)
    subsets = list(combinations(runs, k))
    return sum(any(s) for s in subsets) / len(subsets), sum(all(s) for s in subsets) / len(subsets)


@pytest.mark.parametrize("n", range(1, 7))
def test_estimators_match_enumerating_every_subset(n):
    for c in range(n + 1):
        for k in range(1, n + 1):
            at, hat = brute(n, c, k)
            assert pass_at_k(n, c, k) == pytest.approx(at)
            assert pass_hat_k(n, c, k) == pytest.approx(hat)


def test_with_n_equal_k_they_are_any_and_all():
    assert pass_at_k(3, 1, 3) == 1.0 and pass_hat_k(3, 1, 3) == 0.0
    assert pass_at_k(3, 3, 3) == 1.0 and pass_hat_k(3, 3, 3) == 1.0
    assert pass_at_k(3, 0, 3) == 0.0


def test_k_larger_than_n_is_refused():
    with pytest.raises(ValueError):
        pass_at_k(2, 1, 3)
    with pytest.raises(ValueError):
        pass_hat_k(2, 1, 3)


def rows(case: str, results: list[bool], experiment: str = "x") -> list[dict]:
    return [
        {"experiment": experiment, "case": case, "repeat": i, "success": ok} for i, ok in enumerate(results)
    ]


def test_report_scores_flags_flaky_cases_and_splits_by_source():
    data = (
        rows("gold-a", [True, True, True])
        + rows("gold-b", [True, False, True])
        + rows("adv-c", [False, False, False])
        + rows("prod-001", [True, True])  # too few runs for k = 3
    )
    r = report(data, k=3)["x"]
    assert r["cases"] == 3 and r["runs"] == 9
    assert r["pass_hat_1"] == pytest.approx(round(5 / 9, 3))
    assert r["pass_at_3"] == pytest.approx(round(2 / 3, 3))
    assert r["pass_hat_3"] == pytest.approx(round(1 / 3, 3))
    assert r["gap"] == pytest.approx(0.333)
    assert r["flaky"] == {"gold-b": "✓✗✓"}
    assert r["too_few_runs"] == {"prod-001": 2}
    assert r["by_source"]["golden"]["pass_hat_3"] == 0.5
    assert r["by_source"]["adversarial"]["pass_at_3"] == 0.0
    assert r["by_source"]["production"] == {"cases": 0}
    text = render({"x": r})
    assert "pass@3" in text and "✓✗✓  gold-b" in text and "fewer than 3 runs: prod-001" in text
    assert "production" not in text  # a source with no scored case gets no row


def test_cli_reads_runner_files_and_writes_the_report(tmp_path, capsys):
    import json

    from eval.reliability import main

    results = tmp_path / "r.jsonl"
    results.write_text(
        "\n".join(json.dumps(r) for r in rows("gold-a", [True, False])) + "\n\n", encoding="utf-8"
    )
    out = tmp_path / "report.json"
    assert main([str(results), "--k", "2", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["x"]["pass_at_2"] == 1.0
    assert "gold-a" in capsys.readouterr().out
    results.write_text(json.dumps(rows("gold-a", [True])[0]), encoding="utf-8")
    assert main([str(results), "--k", "1"]) == 0  # nothing flaky, nothing left out
    assert "flaky" not in capsys.readouterr().out
    assert main([str(results)]) == 0  # k = 3 by default: no case has enough runs
    assert "rerun with --repeats 3" in capsys.readouterr().out


def test_a_resumed_run_counts_once():
    data = rows("gold-a", [False, True, True]) + [
        {"experiment": "x", "case": "gold-a", "repeat": 0, "success": True}
    ]
    r = report(data, k=3)["x"]
    assert r["runs"] == 3 and r["pass_hat_3"] == 1.0


def test_experiments_are_reported_separately():
    data = rows("gold-a", [True] * 3, "t0") + rows("gold-a", [True, False, False], "t0.7")
    r = report(data, k=3)
    assert r["t0"]["pass_hat_3"] == 1.0 and r["t0.7"]["pass_hat_3"] == 0.0


def test_temperature_override_reaches_only_the_agent_models():
    from agents.llm import ModelFactory

    seen = {}

    def builder(model_id, slot, config):
        return seen.setdefault(model_id + str(len(seen)), slot["temperature"])

    config = load_config()
    factory = ModelFactory(Experiment(name="e").with_temperature(0.7), config, builder=builder)
    assert factory.get("commander") == 0.7
    assert factory.get("triage") == 0.7
    assert factory.get("reflection") == config["models"]["reflection"]["temperature"]
    assert factory.get("judge") == config["models"]["judge"]["temperature"]
    assert Experiment(name="e").with_temperature(0.7).name == "e-t0.7"
    with pytest.raises(ValueError):
        Experiment(temperature=3.0)


def test_default_temperature_is_the_configured_one():
    config = load_config()
    assert Experiment().temperature_for("commander", config) == config["models"]["commander"]["temperature"]


def test_runner_summary_carries_reliability_with_repeats():
    from eval.cases import load_cases
    from eval.runner import run_experiment

    cases = load_cases("dev")[:2]
    result = run_experiment(Experiment(name="c0", architecture="c0", learn=False), cases, repeats=2)
    rel = result["summary"]["reliability"]
    assert rel["k"] == 2 and rel["cases"] == 2 and rel["runs"] == 4
    assert rel["pass_at_2"] == rel["pass_hat_2"]  # C0 is deterministic: no gap
    assert result["rows"][0]["temperature"] == {"commander": 0.0, "specialist": 0.0}
    single = run_experiment(Experiment(name="c0", architecture="c0", learn=False), cases, repeats=1)
    assert "reliability" not in single["summary"]


def test_runner_temperature_flag_names_and_records_the_run(tmp_path):
    import json

    from eval import runner

    out = tmp_path / "r.jsonl"
    args = ["--experiment", "eval/experiments/e1-c0-fixed.yaml", "--out", str(out), "--repeats", "1"]
    assert runner.main([*args, "--temperature", "0.7"]) == 0
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["experiment"] == "e1-c0-fixed-t0.7"
    assert row["temperature"] == {"commander": 0.7, "specialist": 0.7}
