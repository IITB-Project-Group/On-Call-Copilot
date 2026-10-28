"""Build or refresh the persistent Chroma index from runbooks and postmortems."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .chunker import chunk_markdown_documents
from .index import ChromaPassageStore, EmbeddingEncoder, OpenRouterError, create_embedding_encoder
from .ingest import IngestedDocument, load_markdown_documents

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class IndexingSummary:
    """Counts and location returned after synchronizing the corpus index."""

    document_count: int
    chunk_count: int
    changed_count: int
    collection_count: int
    persist_directory: Path


def load_retrieval_documents(knowledge_dir: str | Path) -> list[IngestedDocument]:
    """Load only runbooks and postmortems, excluding policy and retrieval docs."""
    documents = load_markdown_documents(knowledge_dir)
    return [document for document in documents if document.source.startswith(("runbooks/", "postmortems/"))]


def index_knowledge_corpus(
    knowledge_dir: str | Path | None = None,
    persist_directory: str | Path | None = None,
    collection_name: str = "knowledge_passages",
    batch_size: int = 32,
    encoder: EmbeddingEncoder | None = None,
) -> IndexingSummary:
    """Chunk and synchronize the runbook/postmortem corpus into persistent Chroma."""
    source_directory = Path(knowledge_dir or (_REPOSITORY_ROOT / "knowledge"))
    documents = load_retrieval_documents(source_directory)
    if not documents:
        raise ValueError(f"No runbook or postmortem documents found under {source_directory}")

    chunks = chunk_markdown_documents(documents)
    if not chunks:
        raise ValueError("The runbook and postmortem documents produced no passage chunks")

    selected_encoder = encoder or create_embedding_encoder()
    store = ChromaPassageStore(
        selected_encoder,
        persist_directory=persist_directory,
        collection_name=collection_name,
        batch_size=batch_size,
    )
    changed_count = store.sync_chunks(chunks)
    return IndexingSummary(
        document_count=len(documents),
        chunk_count=len(chunks),
        changed_count=changed_count,
        collection_count=store.count,
        persist_directory=store.persist_directory,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run corpus indexing from the command line and print non-secret status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-dir", type=Path, default=_REPOSITORY_ROOT / "knowledge")
    parser.add_argument("--persist-directory", type=Path, default=None)
    parser.add_argument("--collection-name", default="knowledge_passages")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args(argv)

    try:
        summary = index_knowledge_corpus(
            knowledge_dir=args.knowledge_dir,
            persist_directory=args.persist_directory,
            collection_name=args.collection_name,
            batch_size=args.batch_size,
        )
    except OpenRouterError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Source documents: {summary.document_count}")
    print(f"Passage chunks: {summary.chunk_count}")
    print(f"New or updated passages: {summary.changed_count}")
    print(f"Total passages in collection: {summary.collection_count}")
    print(f"Persistent store: {summary.persist_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
