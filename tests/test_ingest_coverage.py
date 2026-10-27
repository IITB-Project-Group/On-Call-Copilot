from pathlib import Path

from knowledge.retrieval import ingest
from knowledge.retrieval.ingest import (
    _extract_front_matter_and_body,
    _parse_yaml_front_matter,
    _relative_source,
    load_markdown_documents,
)

MANUAL_FRONT_MATTER = """# a comment

- stray item
title: 'Quoted title'
name: "Double quoted"
plain: value
line without a colon
tags:
- alpha
- beta
: odd
other: x
last:
- omega
"""

MANUAL_EXPECTED = {
    "title": "Quoted title",
    "name": "Double quoted",
    "plain": "value",
    "tags": ["alpha", "beta"],
    "": "odd",
    "other": "x",
    "last": ["omega"],
}


def test_blank_front_matter_parses_to_an_empty_mapping():
    assert _parse_yaml_front_matter("  \n") == {}


def test_front_matter_falls_back_to_manual_parser_without_yaml(monkeypatch):
    monkeypatch.setattr(ingest, "yaml", None)

    assert _parse_yaml_front_matter(MANUAL_FRONT_MATTER) == MANUAL_EXPECTED


def test_front_matter_falls_back_when_yaml_does_not_produce_a_mapping():
    assert _parse_yaml_front_matter("- one\n- two\n") == {}


def test_yaml_parser_returns_mappings_directly():
    assert _parse_yaml_front_matter("id: abc\nservice: payment\n") == {"id": "abc", "service": "payment"}


def test_extract_front_matter_variants():
    assert _extract_front_matter_and_body("  plain body \n") == ({}, "plain body")
    assert _extract_front_matter_and_body("---\nid: x\nbody without end") == (
        {},
        "---\nid: x\nbody without end",
    )
    assert _extract_front_matter_and_body("---\n\n---\nbody\n") == ({}, "body")
    assert _extract_front_matter_and_body("---\nid: x\n---\n\nthe body\n") == ({"id": "x"}, "the body")


def test_relative_source_uses_posix_paths_and_falls_back_for_foreign_paths(tmp_path):
    root = tmp_path / "root"
    inside = root / "runbooks" / "a.md"
    outside = tmp_path / "elsewhere" / "b.md"

    assert _relative_source(inside, root) == "runbooks/a.md"
    assert _relative_source(outside, root) == Path(outside).as_posix()


def test_load_markdown_documents_reads_metadata_and_falls_back_to_file_details(tmp_path):
    runbooks = tmp_path / "runbooks"
    runbooks.mkdir()
    (runbooks / "with-meta.md").write_text(
        "---\nid: meta-doc\ndate: 2026-02-03\nservice: cart\nfailure_family: latency\ntitle: Meta\n---\nBody\n",
        encoding="utf-8",
    )
    (runbooks / "plain.md").write_text("Just text", encoding="utf-8")

    documents = {doc.source: doc for doc in load_markdown_documents(tmp_path)}

    meta = documents["runbooks/with-meta.md"]
    assert (meta.doc_id, meta.service, meta.failure_family, meta.title) == (
        "meta-doc",
        "cart",
        "latency",
        "Meta",
    )
    assert meta.source_date == "2026-02-03"
    assert meta.body == "Body"
    plain = documents["runbooks/plain.md"]
    assert plain.doc_id == "plain"
    assert plain.service is None
    assert plain.source_date[:2] == "20"
