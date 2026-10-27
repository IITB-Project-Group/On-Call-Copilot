import json
from unittest.mock import patch

import pytest

from knowledge.retrieval import query_rewriter
from knowledge.retrieval.query_rewriter import OpenRouterQueryRewriter

ENV_NAMES = (
    "OPENROUTER_API_KEY",
    "EMBEDDING_API_KEY",
    "QUERY_REWRITE_MODEL",
    "OPENROUTER_BASE_URL",
    "EMBEDDING_BASE_URL",
)


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(query_rewriter, "_DOTENV_PATH", tmp_path / "missing.env")
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _rewriter():
    return OpenRouterQueryRewriter(api_key="key", model="model", base_url="https://rewrite.example/v1/")


def _respond(mocked_urlopen, content):
    body = json.dumps({"choices": [{"message": {"content": content}}]})
    mocked_urlopen.return_value.__enter__.return_value.read.return_value = body.encode("utf-8")


def test_constructor_reads_openrouter_settings_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("QUERY_REWRITE_MODEL", "rewrite-model")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://router.example/api/")

    rewriter = OpenRouterQueryRewriter()

    assert (rewriter.api_key, rewriter.model) == ("router-key", "rewrite-model")
    assert rewriter.base_url == "https://router.example/api"


def test_constructor_falls_back_to_embedding_settings_and_default_url(monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.example/v1")

    assert OpenRouterQueryRewriter(model="m").api_key == "embedding-key"
    assert OpenRouterQueryRewriter(model="m").base_url == "https://embedding.example/v1"

    monkeypatch.delenv("EMBEDDING_BASE_URL")
    assert OpenRouterQueryRewriter(model="m").base_url == "https://openrouter.ai/api/v1"


def test_constructor_requires_api_key_and_model(monkeypatch):
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterQueryRewriter(model="m")
    with pytest.raises(ValueError, match="QUERY_REWRITE_MODEL"):
        OpenRouterQueryRewriter(api_key="key")


def test_rewrite_rejects_negative_counts_and_skips_empty_work():
    rewriter = _rewriter()

    with pytest.raises(ValueError, match="count must be non-negative"):
        rewriter.rewrite("query", -1)
    with patch("knowledge.retrieval.query_rewriter.urlopen") as mocked_urlopen:
        assert rewriter.rewrite("query", 0) == []
        assert rewriter.rewrite("   ", 3) == []
    mocked_urlopen.assert_not_called()


def test_rewrite_filters_non_strings_blanks_and_duplicates_then_stops_at_count():
    queries = ["ORIGINAL", 7, "  ", "first variant", "FIRST VARIANT", "second variant", "third variant"]
    with patch("knowledge.retrieval.query_rewriter.urlopen") as mocked_urlopen:
        _respond(mocked_urlopen, json.dumps({"queries": queries}))
        rewrites = _rewriter().rewrite("original", 2)

    assert rewrites == ["first variant", "second variant"]
    sent = mocked_urlopen.call_args.args[0]
    assert sent.full_url == "https://rewrite.example/v1/chat/completions"
    assert json.loads(sent.data)["max_tokens"] == 240


def test_rewrite_returns_fewer_variants_when_the_model_supplies_fewer():
    with patch("knowledge.retrieval.query_rewriter.urlopen") as mocked_urlopen:
        _respond(mocked_urlopen, json.dumps({"queries": ["only variant"]}))

        assert _rewriter().rewrite("original", 5) == ["only variant"]


@pytest.mark.parametrize(
    "content",
    ["not json", json.dumps({"other": []}), json.dumps(["list"]), json.dumps(None)],
)
def test_rewrite_rejects_unparseable_responses(content):
    with patch("knowledge.retrieval.query_rewriter.urlopen") as mocked_urlopen:
        _respond(mocked_urlopen, content)

        with pytest.raises(ValueError, match="JSON queries array"):
            _rewriter().rewrite("original", 1)


def test_rewrite_rejects_missing_choices():
    with patch("knowledge.retrieval.query_rewriter.urlopen") as mocked_urlopen:
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = b'{"choices": []}'

        with pytest.raises(ValueError, match="JSON queries array"):
            _rewriter().rewrite("original", 1)


def test_rewrite_rejects_non_list_queries():
    with patch("knowledge.retrieval.query_rewriter.urlopen") as mocked_urlopen:
        _respond(mocked_urlopen, json.dumps({"queries": "oops"}))

        with pytest.raises(ValueError, match="'queries' must be a list"):
            _rewriter().rewrite("original", 1)
