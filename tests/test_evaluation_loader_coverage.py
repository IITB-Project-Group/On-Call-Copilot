import pytest

from knowledge.evaluation import load_golden_queries


def _make_corpus(tmp_path, documents=None):
    knowledge_dir = tmp_path / "knowledge"
    for relative, content in (
        documents or {"runbooks/known.md": "---\nid: known-doc\n---\n# Known\n"}
    ).items():
        path = knowledge_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    knowledge_dir.mkdir(exist_ok=True)
    return knowledge_dir


def _load(tmp_path, query_yaml, documents=None):
    knowledge_dir = _make_corpus(tmp_path, documents)
    query_file = tmp_path / "queries.yaml"
    query_file.write_text(query_yaml, encoding="utf-8")
    return load_golden_queries(query_file, knowledge_dir)


VALID_QUERY = """queries:
  - id: q01
    query: "A valid query"
    kind: symptom_only
    relevant_docs: [known-doc]
"""


def test_loads_queries_with_explicit_split_and_postmortem_labels(tmp_path):
    documents = {
        "runbooks/known.md": "---\nid: known-doc\n---\n# Known\n",
        "postmortems/old.md": "---\nid: pm-old\n---\n# Old\n",
        "policies/ignored.md": "---\nid: policy-doc\n---\n# Policy\n",
    }
    queries = _load(
        tmp_path,
        """queries:
  - id: q01
    query: "Find it"
    kind: misleading
    split: heldout
    relevant_docs: [known-doc, pm-old]
""",
        documents,
    )

    assert len(queries) == 1
    assert queries[0].split == "heldout"
    assert queries[0].kind == "misleading"
    assert queries[0].relevant_docs == ("known-doc", "pm-old")


def test_loader_uses_default_split_when_omitted(tmp_path):
    assert _load(tmp_path, VALID_QUERY)[0].split == "dev"


def test_rejects_corpus_without_runbooks_or_postmortems(tmp_path):
    documents = {"policies/other.md": "# Not a runbook\n"}

    with pytest.raises(ValueError, match="No runbook or postmortem documents"):
        _load(tmp_path, VALID_QUERY, documents)


def test_rejects_duplicate_corpus_document_ids(tmp_path):
    documents = {
        "runbooks/a.md": "---\nid: same\n---\n# A\n",
        "postmortems/b.md": "---\nid: same\n---\n# B\n",
    }

    with pytest.raises(ValueError, match="Duplicate document IDs.*same"):
        _load(tmp_path, VALID_QUERY, documents)


def test_rejects_invalid_yaml(tmp_path):
    with pytest.raises(ValueError, match="Invalid YAML"):
        _load(tmp_path, "queries: [unclosed\n")


@pytest.mark.parametrize(
    "query_yaml",
    ["- just\n- a list\n", "queries: []\nextra: 1\n", "other: 1\n"],
)
def test_rejects_wrong_top_level_shape(tmp_path, query_yaml):
    with pytest.raises(ValueError, match="top-level 'queries' field"):
        _load(tmp_path, query_yaml)


@pytest.mark.parametrize("query_yaml", ["queries: []\n", "queries: not-a-list\n"])
def test_rejects_empty_or_non_list_queries(tmp_path, query_yaml):
    with pytest.raises(ValueError, match="non-empty queries list"):
        _load(tmp_path, query_yaml)


def test_rejects_non_mapping_query(tmp_path):
    with pytest.raises(ValueError, match="index 0 must be a mapping"):
        _load(tmp_path, "queries:\n  - just a string\n")


def test_rejects_missing_and_unexpected_fields(tmp_path):
    with pytest.raises(ValueError, match="missing fields: kind, relevant_docs"):
        _load(tmp_path, "queries:\n  - id: q01\n    query: hi\n")
    with pytest.raises(ValueError, match="unexpected fields: bogus"):
        _load(
            tmp_path,
            VALID_QUERY.replace("    kind:", "    bogus: 1\n    kind:"),
        )
    with pytest.raises(ValueError, match="missing fields: id.*unexpected fields: bogus"):
        _load(
            tmp_path,
            "queries:\n  - query: hi\n    kind: paraphrase\n    relevant_docs: [known-doc]\n    bogus: 1\n",
        )


@pytest.mark.parametrize(
    ("query_id", "query_text", "field"),
    [
        ('"  "', '"ok"', "'id'"),
        ("7", '"ok"', "'id'"),
        ("q01", '""', "'query'"),
        ("q01", "12", "'query'"),
    ],
)
def test_rejects_blank_or_non_string_id_and_query(tmp_path, query_id, query_text, field):
    query_yaml = (
        f"queries:\n  - id: {query_id}\n    query: {query_text}\n"
        "    kind: paraphrase\n    relevant_docs: [known-doc]\n"
    )

    with pytest.raises(ValueError, match=f"non-empty string {field}"):
        _load(tmp_path, query_yaml)


def test_rejects_non_string_kind(tmp_path):
    with pytest.raises(ValueError, match="invalid kind"):
        _load(tmp_path, VALID_QUERY.replace("kind: symptom_only", "kind: 5"))


def test_rejects_invalid_split(tmp_path):
    with pytest.raises(ValueError, match="invalid split 'later'"):
        _load(tmp_path, VALID_QUERY.replace("    kind:", "    split: later\n    kind:"))
    with pytest.raises(ValueError, match="invalid split"):
        _load(tmp_path, VALID_QUERY.replace("    kind:", "    split: 3\n    kind:"))


@pytest.mark.parametrize(
    "docs",
    ["known-doc", "[]", "[1]", '["  "]'],
)
def test_rejects_malformed_relevant_docs(tmp_path, docs):
    with pytest.raises(ValueError, match="non-empty list of document IDs"):
        _load(tmp_path, VALID_QUERY.replace("[known-doc]", docs))


def test_rejects_duplicate_relevant_docs(tmp_path):
    with pytest.raises(ValueError, match="duplicate relevant document IDs"):
        _load(tmp_path, VALID_QUERY.replace("[known-doc]", "[known-doc, known-doc]"))
