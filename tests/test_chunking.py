from knowledge.retrieval.chunker import chunk_markdown_documents
from knowledge.retrieval.ingest import load_markdown_documents


def test_chunk_markdown_documents_creates_provenance_carrying_chunks(tmp_path):
    """A long markdown document should split into passage chunks that keep source metadata."""
    runbook_dir = tmp_path / "runbooks"
    runbook_dir.mkdir()

    doc_path = runbook_dir / "sample-runbook.md"
    doc_path.write_text(
        """---
id: sample-1
title: Sample outage
service: payment
failure_family: payment_failure
source: runbook
source_date: 2026-10-01
---

# Root cause

Payment requests are failing because the payment service is returning repeated 500 errors.

## Evidence

The checkout alert stayed above the threshold for five minutes and the payment traces show the error path.

## Remediation

The safe fix is to disable the paymentFailure flag after approval and verify recovery.

## Verification

After the flag is disabled, the checkout error rate should return to baseline and payment errors should stop.
""",
        encoding="utf-8",
    )

    documents = load_markdown_documents(tmp_path)
    chunks = chunk_markdown_documents(documents, target_words=80, overlap_words=20)

    assert len(chunks) >= 2

    first_chunk = chunks[0]
    assert first_chunk["doc_id"] == "sample-1"
    assert first_chunk["source"] == "runbooks/sample-runbook.md"
    assert first_chunk["source_date"] == "2026-10-01"
    assert first_chunk["service"] == "payment"
    assert first_chunk["failure_family"] == "payment_failure"
    assert first_chunk["chunk_id"].startswith("sample-1-")
    assert first_chunk["text"]
