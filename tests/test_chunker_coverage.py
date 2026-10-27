import pytest

from knowledge.retrieval import chunker
from knowledge.retrieval.chunker import chunk_markdown_documents
from knowledge.retrieval.ingest import IngestedDocument


def _document(body, doc_id="doc"):
    return IngestedDocument(
        doc_id=doc_id,
        source=f"runbooks/{doc_id}.md",
        source_date="2026-01-01",
        service="payment",
        failure_family="config",
        title="Title",
        body=body,
    )


def test_split_sections_handles_a_leading_heading_and_blank_lines():
    sections = chunker._split_sections("# First\n\nline one\n## Second\nline two\n")

    assert sections == ["# First\nline one", "## Second\nline two"]


def test_split_sections_keeps_preamble_before_the_first_heading():
    assert chunker._split_sections("intro\n# Heading\nbody") == ["intro", "# Heading\nbody"]


def test_group_sections_skips_blank_paragraphs():
    assert chunker._group_sections_into_paragraphs(["", "one\n\ntwo", "   "]) == ["one", "two"]


def test_windowed_chunks_returns_nothing_without_paragraphs():
    assert chunker._windowed_chunks([], 0, 0) == []


@pytest.mark.parametrize(
    ("target", "overlap", "message"),
    [
        (0, 0, "target_words must be positive"),
        (5, -1, "overlap_words must be non-negative"),
        (5, 5, "overlap_words must be smaller than target_words"),
    ],
)
def test_windowed_chunks_validates_window_settings(target, overlap, message):
    with pytest.raises(ValueError, match=message):
        chunker._windowed_chunks(["some text"], target, overlap)


def test_windowed_chunks_slides_over_long_paragraphs_with_overlap():
    paragraph = "one two three four five six seven"

    chunks = chunker._windowed_chunks([paragraph, "short para"], 4, 1)

    assert chunks == [
        "one two three four",
        "four five six seven",
        "short para",
    ]


def test_windowed_chunks_stops_when_the_final_window_is_exact():
    assert chunker._windowed_chunks(["a b c d e f"], 3, 0) == ["a b c", "d e f"]


class _ScriptedTokens(list):
    """Token list whose reported length and slices are scripted to exercise defensive loop exits."""

    def __init__(self, lengths, window):
        super().__init__()
        self._lengths = iter(lengths)
        self._window = window

    def __len__(self):
        return next(self._lengths)

    def __getitem__(self, key):
        return list(self._window)


def test_windowed_chunks_ignores_an_empty_window(monkeypatch):
    tokens = _ScriptedTokens([10, 10, 10], [])
    monkeypatch.setattr(chunker, "_tokenize_to_words", lambda _text: tokens)

    assert chunker._windowed_chunks(["anything"], 4, 1) == []


def test_windowed_chunks_stops_when_the_start_passes_the_token_count(monkeypatch):
    tokens = _ScriptedTokens([10, 10, 10, 10, 0], ["only"])
    monkeypatch.setattr(chunker, "_tokenize_to_words", lambda _text: tokens)

    assert chunker._windowed_chunks(["anything"], 4, 1) == ["only"]


def test_chunk_markdown_documents_uses_config_defaults_and_keeps_provenance():
    chunks = chunk_markdown_documents([_document("# Heading\nbody text here")])

    assert chunks == [
        {
            "chunk_id": "doc-0",
            "doc_id": "doc",
            "source": "runbooks/doc.md",
            "source_date": "2026-01-01",
            "service": "payment",
            "failure_family": "config",
            "title": "Title",
            "text": "# Heading\nbody text here",
            "metadata": {},
        }
    ]


def test_chunk_markdown_documents_accepts_explicit_window_settings():
    chunks = chunk_markdown_documents([_document("a b c d e f g h")], target_words=4, overlap_words=0)

    assert [chunk["chunk_id"] for chunk in chunks] == ["doc-0", "doc-1"]
    assert [chunk["text"] for chunk in chunks] == ["a b c d", "e f g h"]
