import pytest
import yaml

from knowledge.retrieval.config_loader import RetrievalConfig, load_retrieval_config

VALID = {
    "target_words": 100,
    "overlap_words": 10,
    "candidate_k": 5,
    "rrf_k": 60,
    "query_rewrite_count": 0,
    "reranker_candidate_k": 4,
    "top_k": 3,
}


def _write(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content if isinstance(content, str) else yaml.safe_dump(content), encoding="utf-8")
    return path


def test_loads_a_valid_config_file(tmp_path):
    assert load_retrieval_config(_write(tmp_path, VALID)) == RetrievalConfig(**VALID)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"target_words": 0}, "target_words must be positive"),
        ({"overlap_words": -1}, "overlap_words must be non-negative"),
        ({"overlap_words": 100}, "overlap_words must be smaller than target_words"),
        ({"candidate_k": 0}, "candidate_k must be positive"),
        ({"rrf_k": 0}, "rrf_k must be positive"),
        ({"query_rewrite_count": -1}, "query_rewrite_count must be non-negative"),
        ({"reranker_candidate_k": 0}, "reranker_candidate_k must be positive"),
        ({"top_k": 0}, "top_k must be positive"),
    ],
)
def test_config_rejects_out_of_range_values(override, message):
    with pytest.raises(ValueError, match=message):
        RetrievalConfig(**{**VALID, **override})


def test_loader_rejects_non_mapping_yaml(tmp_path):
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_retrieval_config(_write(tmp_path, "- a\n- b\n"))


def test_loader_reports_missing_settings(tmp_path):
    incomplete = {key: value for key, value in VALID.items() if key not in {"top_k", "rrf_k"}}

    with pytest.raises(ValueError, match="missing required settings: rrf_k, top_k"):
        load_retrieval_config(_write(tmp_path, incomplete))


@pytest.mark.parametrize("bad_value", ["10", True, 1.5, None])
def test_loader_requires_integer_settings(tmp_path, bad_value):
    with pytest.raises(ValueError, match="top_k must be an integer"):
        load_retrieval_config(_write(tmp_path, {**VALID, "top_k": bad_value}))
