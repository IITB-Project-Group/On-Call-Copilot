"""Load and validate labeled retrieval-evaluation queries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml

from knowledge.retrieval.ingest import load_markdown_documents

QueryKind = Literal["symptom_only", "paraphrase", "ambiguous", "misleading"]
QuerySplit = Literal["dev", "heldout"]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_QUERY_FILE = Path(__file__).with_name("golden_queries.yaml")
_QUERY_KINDS = {"symptom_only", "paraphrase", "ambiguous", "misleading"}
_QUERY_SPLITS = {"dev", "heldout"}
_REQUIRED_QUERY_FIELDS = {"id", "query", "relevant_docs", "kind"}
_OPTIONAL_QUERY_FIELDS = {"split"}


@dataclass(frozen=True)
class GoldenQuery:
    """A query and its labeled relevant corpus documents."""

    id: str
    query: str
    relevant_docs: tuple[str, ...]
    kind: QueryKind
    split: QuerySplit = "dev"


def _load_corpus_document_ids(knowledge_dir: Path) -> set[str]:
    documents = [
        document
        for document in load_markdown_documents(knowledge_dir)
        if document.source.startswith(("runbooks/", "postmortems/"))
    ]
    if not documents:
        raise ValueError(f"No runbook or postmortem documents found under {knowledge_dir}")

    document_ids = [document.doc_id for document in documents]
    duplicate_ids = sorted(
        document_id for document_id in set(document_ids) if document_ids.count(document_id) > 1
    )
    if duplicate_ids:
        raise ValueError(
            "Duplicate document IDs in the runbook/postmortem corpus: " + ", ".join(duplicate_ids)
        )
    return set(document_ids)


def _require_nonempty_string(value: object, field: str, query_index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Query at index {query_index} must have a non-empty string {field!r}")
    return value


def load_golden_queries(
    path: str | Path | None = None,
    knowledge_dir: str | Path | None = None,
) -> list[GoldenQuery]:
    """Load the golden-query YAML and reject invalid or unresolved labels."""
    query_path = Path(path) if path is not None else _DEFAULT_QUERY_FILE
    corpus_path = Path(knowledge_dir) if knowledge_dir is not None else _REPOSITORY_ROOT / "knowledge"

    try:
        raw_data = yaml.safe_load(query_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML in {query_path}: {error}") from error

    if not isinstance(raw_data, dict) or set(raw_data) != {"queries"}:
        raise ValueError(f"{query_path} must contain only a top-level 'queries' field")

    raw_queries = raw_data["queries"]
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValueError(f"{query_path} must define a non-empty queries list")

    corpus_ids = _load_corpus_document_ids(corpus_path)
    parsed_queries: list[GoldenQuery] = []
    seen_query_ids: set[str] = set()

    for index, raw_query in enumerate(raw_queries):
        if not isinstance(raw_query, dict):
            raise ValueError(f"Query at index {index} must be a mapping")

        fields = set(raw_query)
        missing_fields = _REQUIRED_QUERY_FIELDS - fields
        unexpected_fields = fields - _REQUIRED_QUERY_FIELDS - _OPTIONAL_QUERY_FIELDS
        if missing_fields or unexpected_fields:
            details = []
            if missing_fields:
                details.append("missing fields: " + ", ".join(sorted(missing_fields)))
            if unexpected_fields:
                details.append("unexpected fields: " + ", ".join(sorted(unexpected_fields)))
            raise ValueError(f"Query at index {index} has " + "; ".join(details))

        query_id = _require_nonempty_string(raw_query["id"], "id", index)
        query_text = _require_nonempty_string(raw_query["query"], "query", index)
        if query_id in seen_query_ids:
            raise ValueError(f"Duplicate query ID {query_id!r}")
        seen_query_ids.add(query_id)

        kind = raw_query["kind"]
        if not isinstance(kind, str) or kind not in _QUERY_KINDS:
            raise ValueError(
                f"Query {query_id!r} has invalid kind {kind!r}; " f"expected one of {sorted(_QUERY_KINDS)}"
            )

        split = raw_query.get("split", "dev")
        if not isinstance(split, str) or split not in _QUERY_SPLITS:
            raise ValueError(
                f"Query {query_id!r} has invalid split {split!r}; " f"expected one of {sorted(_QUERY_SPLITS)}"
            )

        relevant_docs = raw_query["relevant_docs"]
        if (
            not isinstance(relevant_docs, list)
            or not relevant_docs
            or any(
                not isinstance(document_id, str) or not document_id.strip() for document_id in relevant_docs
            )
        ):
            raise ValueError(f"Query {query_id!r} must have a non-empty list of document IDs")
        if len(set(relevant_docs)) != len(relevant_docs):
            raise ValueError(f"Query {query_id!r} contains duplicate relevant document IDs")

        unknown_ids = sorted(set(relevant_docs) - corpus_ids)
        if unknown_ids:
            raise ValueError(
                f"Query {query_id!r} references unknown corpus document IDs: " + ", ".join(unknown_ids)
            )

        parsed_queries.append(
            GoldenQuery(
                id=query_id,
                query=query_text,
                relevant_docs=tuple(relevant_docs),
                kind=cast(QueryKind, kind),
                split=cast(QuerySplit, split),
            )
        )

    return parsed_queries
