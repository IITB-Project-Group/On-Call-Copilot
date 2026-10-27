"""Chunking utilities for markdown knowledge documents.

This module follows the project's retrieval minimum bar: documents are split into
passage-sized chunks that preserve source provenance and section structure. Each
chunk retains its document metadata and a stable chunk ID so later retrieval
stages can return evidence with clear passage citations.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from .config_loader import load_retrieval_config
from .ingest import IngestedDocument


def _tokenize_to_words(text: str) -> List[str]:
    """Split text into word tokens without using heavyweight external dependencies."""
    return re.findall(r"\b\w+\b", text.lower())


def _split_sections(body: str) -> List[str]:
    """Split markdown text into section blocks while respecting headings.

    The goal is to keep each heading and its local context together so retrieval
    remains relevant and easy to cite later.
    """
    blocks: List[str] = []
    current: List[str] = []

    for line in body.splitlines():
        if re.match(r"^#+\s+", line):
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            current.append(line.strip())
        else:
            if line.strip():
                current.append(line.strip())

    if current:
        blocks.append("\n".join(current).strip())

    return [block for block in blocks if block]


def _group_sections_into_paragraphs(sections: Iterable[str]) -> List[str]:
    """Convert sections to paragraph-sized text units before chunking."""
    paragraphs: List[str] = []
    for section in sections:
        for paragraph in re.split(r"\n\s*\n+", section):
            cleaned = paragraph.strip()
            if cleaned:
                paragraphs.append(cleaned)
    return paragraphs


def _windowed_chunks(paragraphs: List[str], target_words: int, overlap_words: int) -> List[str]:
    """Build overlapped chunks from paragraph text using a simple sliding window.

    The logic prioritizes paragraph and section boundaries and only falls back to
    a sliding window when a section itself is larger than the target chunk size.
    This keeps the retrieval units coherent while still producing multiple chunks
    for longer incident notes and runbooks.
    """
    if not paragraphs:
        return []

    if target_words <= 0:
        raise ValueError("target_words must be positive")
    if overlap_words < 0:
        raise ValueError("overlap_words must be non-negative")
    if overlap_words >= target_words:
        raise ValueError("overlap_words must be smaller than target_words")

    chunks: List[str] = []
    for paragraph in paragraphs:
        paragraph_tokens = _tokenize_to_words(paragraph)
        if len(paragraph_tokens) <= target_words:
            chunks.append(paragraph.strip())
            continue

        step = target_words - overlap_words
        start = 0
        while start < len(paragraph_tokens):
            end = min(len(paragraph_tokens), start + target_words)
            chunk_tokens = paragraph_tokens[start:end]
            if not chunk_tokens:
                break
            chunks.append(" ".join(chunk_tokens))
            if end == len(paragraph_tokens):
                break
            start += step

    return [chunk.strip() for chunk in chunks if chunk.strip()]


def chunk_markdown_documents(
    documents: Iterable[IngestedDocument],
    target_words: int | None = None,
    overlap_words: int | None = None,
) -> List[Dict[str, Any]]:
    """Chunk documents into passage-sized text units with provenance metadata.

    The strategy is intentionally section-aware and paragraph-based: headings stay
    with their local context, and each chunk retains source, date, and document
    metadata so later retrieval can trace every result to a real source excerpt.
    """
    config = load_retrieval_config()
    target_words = config.target_words if target_words is None else target_words
    overlap_words = config.overlap_words if overlap_words is None else overlap_words
    chunks: List[Dict[str, Any]] = []

    for document in documents:
        sections = _split_sections(document.body)
        paragraphs = _group_sections_into_paragraphs(sections)
        windowed_chunks = _windowed_chunks(paragraphs, target_words, overlap_words)

        for index, chunk_text in enumerate(windowed_chunks):
            chunk_id = f"{document.doc_id}-{index}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": document.doc_id,
                    "source": document.source,
                    "source_date": document.source_date,
                    "service": document.service,
                    "failure_family": document.failure_family,
                    "title": document.title,
                    "text": chunk_text,
                    "metadata": document.metadata,
                }
            )

    return chunks
