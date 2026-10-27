import pytest

from knowledge.evaluation import load_golden_queries


def _write_corpus_and_queries(tmp_path, query_yaml):
    knowledge_dir = tmp_path / "knowledge"
    runbooks_dir = knowledge_dir / "runbooks"
    runbooks_dir.mkdir(parents=True)
    (runbooks_dir / "known.md").write_text(
        "---\nid: known-doc\n---\n# Known document\n",
        encoding="utf-8",
    )
    query_file = tmp_path / "queries.yaml"
    query_file.write_text(query_yaml, encoding="utf-8")
    return query_file, knowledge_dir


def test_loads_and_validates_all_golden_queries_against_corpus():
    queries = load_golden_queries()

    assert len(queries) == 1
    assert queries[0].id == "q01"
    assert queries[0].relevant_docs == ("payment-failure", "pm-001")
    assert queries[0].split == "dev"
    assert queries[0].kind == "symptom_only"


def test_rejects_unknown_relevant_document_id(tmp_path):
    query_file, knowledge_dir = _write_corpus_and_queries(
        tmp_path,
        """queries:
  - id: q01
    query: "A valid query"
    kind: symptom_only
    relevant_docs: [missing-doc]
""",
    )

    with pytest.raises(ValueError, match="unknown corpus document IDs: missing-doc"):
        load_golden_queries(query_file, knowledge_dir)


def test_rejects_duplicate_query_ids(tmp_path):
    query_file, knowledge_dir = _write_corpus_and_queries(
        tmp_path,
        """queries:
  - id: q01
    query: "First query"
    kind: symptom_only
    relevant_docs: [known-doc]
  - id: q01
    query: "Second query"
    kind: paraphrase
    relevant_docs: [known-doc]
""",
    )

    with pytest.raises(ValueError, match="Duplicate query ID 'q01'"):
        load_golden_queries(query_file, knowledge_dir)


def test_rejects_invalid_kind(tmp_path):
    query_file, knowledge_dir = _write_corpus_and_queries(
        tmp_path,
        """queries:
  - id: q01
    query: "A valid query"
    kind: unsupported
    relevant_docs: [known-doc]
""",
    )

    with pytest.raises(ValueError, match="invalid kind"):
        load_golden_queries(query_file, knowledge_dir)
