"""The evaluation dataset (eval/dataset): it validates, and each check catches the fault it claims to."""

from __future__ import annotations

import copy

import pytest

from eval.cases import load_cases
from eval.dataset import build as B
from eval.dataset import check as C

SYNC, SPLIT, RUNNABLE, TRACES, SHARED, IDS, CANARY = list(C.run())


@pytest.fixture
def data():
    return copy.deepcopy(C.load())


def failed(results: dict) -> list[str]:
    return [name for name, problems in results.items() if problems]


def test_dataset_passes_every_check(capsys):
    assert failed(C.run()) == []
    assert C.main() == 0
    assert "7 passed, 0 failed" in capsys.readouterr().out


def test_split_is_50_30_20_and_production_repeats_the_dev_inputs(data):
    m = data["manifest"]
    assert m["ratios"] == {"production": 0.5, "golden": 0.3, "adversarial": 0.2}
    assert m["distinct_inputs"] == {"production": 20, "golden": 30, "adversarial": 20, "regression": 13}


def test_labelling_rule_reproduces_every_dev_severity():
    for case in load_cases("dev"):
        assert B.label(case)["severity"] == case["expected"]["severity"], case["id"]


def test_build_writes_exactly_the_committed_dataset(tmp_path, monkeypatch, capsys):
    B.write(B.cases(), tmp_path)
    (tmp_path / "golden" / "stale.yaml").write_text("id: stale\n", encoding="utf-8")
    monkeypatch.setattr(B, "HERE", tmp_path)
    assert B.main() == 0  # a rebuild removes files it no longer produces
    assert '"golden": 30' in capsys.readouterr().out
    assert C.load(tmp_path) == C.load(B.ROOT / "eval" / "dataset")


def test_only_finished_dev_runs_with_a_trace_are_sampled(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(B, "ROOT", tmp_path)
    monkeypatch.setattr(B, "RESULTS", tmp_path)
    (tmp_path / "traces" / "run").mkdir(parents=True)
    (tmp_path / "traces" / "run" / "ok.jsonl").write_text("{}")
    (tmp_path / "traces" / "run" / "other.jsonl").write_text("{}")
    rows = [
        {"case": "dev-a", "incident_id": "ok", "error": None},
        {"case": "dev-a", "incident_id": "errored", "error": "TimeoutError"},
        {"case": "dev-a", "incident_id": "no-trace", "error": None},
        {"case": "not-a-dev-case", "incident_id": "other", "error": None},
    ]
    (tmp_path / "run.jsonl").write_text("\n\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (run,) = B.recorded_runs({"dev-a": {}})
    assert (run["incident_id"], run["_run"], run["_trace"]) == ("ok", "run", "traces/run/ok.jsonl")


def test_evidence_points_at_the_query_that_shows_it(data):
    both = next(c for c in data["adversarial"] if c["id"] == "adv-ad-cpu-and-gc")
    calls = {c.get("query"): c.get("shows") for c in both["reference"]["trajectory"]["must_call"]}
    assert calls["copilot:container_cpu_ratio"] == "cpu_ratio.ad ~ 0.98"
    assert calls["copilot:gc_pause_ratio:5m"] == "gc_pause_ratio.ad ~ 0.42"


def test_a_hand_edit_a_missing_file_and_an_extra_file_are_caught(data):
    data["golden"][0]["expected"]["severity"] = "SEV-wrong"
    gone = data["adversarial"].pop()
    data["regression"].append({**data["regression"][0], "id": "reg-extra"})
    data["manifest"]["counts"]["golden"] = 31
    problems = C.run(data)[SYNC]
    assert f"golden/{data['golden'][0]['id']}: differs from a fresh build" in problems
    assert f"adversarial/{gone['id']}: built but not on disk" in problems
    assert "regression/reg-extra: on disk but not built" in problems
    assert "manifest.yaml differs from a fresh build" in problems


def test_a_wrong_split_is_caught(data):
    data["adversarial"] = data["adversarial"][:10]
    assert SPLIT in failed(C.run(data))


def test_a_case_the_twin_cannot_run_is_caught(data):
    data["golden"][0]["inject"] = [{"flag": "paymentFailure", "variant": "half%"}]
    (problem,) = C.run(data)[RUNNABLE]
    assert problem.startswith(f"golden/{data['golden'][0]['id']}: ValueError")


def test_a_missing_trace_is_caught(data):
    data["production"][0]["trace"]["path"] = "eval/results/nowhere.jsonl"
    data["regression"][0]["regression"]["seen_in"].append("eval/results/gone.jsonl")
    assert len(C.run(data)[TRACES]) == 2


def test_a_held_out_input_that_is_also_a_tuning_input_is_caught(data):
    dev = load_cases("dev")[0]
    first, second = data["golden"][0], data["golden"][1]
    for key in ("inject", "load", "alert"):
        first[key] = dev[key]
        data["adversarial"][0][key] = second[key]
    data["adversarial"][0].pop("log_lines", None)
    assert C.run(data)[SHARED] == [
        f"{first['id']}: same input as {dev['id']}",
        f"{data['adversarial'][0]['id']}: same input as {second['id']}",
    ]


def test_a_leak_into_the_improvement_loop_is_caught(tmp_path, data):
    held_out_id = data["golden"][0]["id"]
    (tmp_path / "knowledge" / "playbook").mkdir(parents=True)
    (tmp_path / "knowledge" / "playbook" / "playbook.yaml").write_text(f"lesson from {held_out_id}\n")
    (tmp_path / "docs" / "agents").mkdir(parents=True)
    (tmp_path / "docs" / "agents" / "playbook.md").write_text(f"note: {B.CANARY}\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "packed").write_text(B.CANARY)  # skipped directories are not scanned
    results = C.run(data, root=tmp_path)
    assert results[IDS] == [f"knowledge/playbook/playbook.yaml contains {held_out_id}"]
    assert results[CANARY] == ["docs/agents/playbook.md"]


def test_main_exits_1_and_names_the_problem(monkeypatch, capsys):
    monkeypatch.setattr(C, "run", lambda: {"split": ["golden: 31 of 101"], "traces": []})
    assert C.main() == 1
    out = capsys.readouterr().out
    assert "FAIL  split" in out and "golden: 31 of 101" in out and "1 passed, 1 failed" in out


def test_reflexion_refuses_held_out_cases(data):
    from eval.reflexion import run_reflexion

    case = dict(data["golden"][0], split="dev")
    with pytest.raises(ValueError, match="never feed Reflexion"):
        run_reflexion(None, [case], "unused", models=object())
