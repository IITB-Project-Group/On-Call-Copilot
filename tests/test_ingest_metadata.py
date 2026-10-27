from knowledge.retrieval.ingest import load_markdown_documents


def test_ingest_preserves_source_and_date_metadata(tmp_path):
    """Ingested documents should retain source metadata and a usable source date."""
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

# Sample outage

Payment requests are failing and the alert is active.
""",
        encoding="utf-8",
    )

    documents = load_markdown_documents(tmp_path)

    assert len(documents) == 1
    doc = documents[0]
    assert doc.doc_id == "sample-1"
    assert doc.service == "payment"
    assert doc.failure_family == "payment_failure"
    assert doc.source.endswith("runbooks/sample-runbook.md")
    assert doc.source_date == "2026-10-01"
    assert "Payment requests are failing" in doc.body
