"""Ingestion helpers for the knowledge layer.

This module reads runbooks and postmortems from disk, keeps their metadata,
retains their source and date, and exposes a plain structured record for later
retrieval and ranking. The implementation intentionally stays lightweight so the
project can validate the retrieval pipeline before moving to a persistent vector
store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - fallback for minimal environments.
    yaml = None


@dataclass
class IngestedDocument:
    """A single knowledge document after ingestion.

    Each record carries both the content text and the metadata needed for
    retrieval and auditability: its source file, source date, and structured
    fields such as service and failure family.
    """

    doc_id: str
    source: str
    source_date: str
    service: str | None
    failure_family: str | None
    title: str | None
    body: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def _parse_yaml_front_matter(front_matter: str) -> Dict[str, Any]:
    """Parse YAML-like front matter found at the head of a markdown document."""
    if not front_matter.strip():
        return {}

    if yaml is not None:
        parsed = yaml.safe_load(front_matter) or {}
        if isinstance(parsed, dict):
            return parsed

    result: Dict[str, Any] = {}
    list_key: str | None = None
    list_buffer: List[str] = []

    for line in front_matter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            if list_key is not None:
                list_buffer.append(stripped[2:].strip())
            continue

        if ":" in stripped:
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            value = raw_value.strip()

            if list_key is not None and key:
                result[list_key] = list_buffer
                list_key = None
                list_buffer = []

            if value == "":
                list_key = key
                list_buffer = []
                result[key] = []
                continue

            if value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            elif value.startswith('"') and value.endswith('"'):
                value = value[1:-1]

            result[key] = value

    if list_key is not None:
        result[list_key] = list_buffer

    return result


def _extract_front_matter_and_body(text: str) -> tuple[Dict[str, Any], str]:
    """Split markdown front matter from the body text of a document."""
    if not text.startswith("---"):
        return {}, text.strip()

    end_marker = "\n---"
    start_index = 4
    split_index = text.find(end_marker, start_index)
    if split_index == -1:
        return {}, text.strip()

    front_matter = text[start_index:split_index]
    body = text[split_index + len(end_marker) :].strip()
    return _parse_yaml_front_matter(front_matter), body


def _relative_source(path: Path, root_dir: Path) -> str:
    """Return a repository-relative source path when possible.

    Paths are normalized to forward slashes so the stored source metadata is
    consistent across operating systems and remains easy to cite in retrieval
    results.
    """
    try:
        relative = path.relative_to(root_dir)
    except ValueError:
        relative = path
    return relative.as_posix()


def load_markdown_documents(root_dir: str | Path) -> List[IngestedDocument]:
    """Load all markdown knowledge documents under a directory.

    The returned objects keep the original document text and preserve metadata so
    later retrieval stages can cite source provenance and time information.
    """
    root = Path(root_dir)
    documents: List[IngestedDocument] = []

    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        metadata, body = _extract_front_matter_and_body(text)

        document_id = str(metadata.get("id") or path.stem)
        source = _relative_source(path, root)
        source_date = str(
            metadata.get("source_date")
            or metadata.get("date")
            or datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        )

        document = IngestedDocument(
            doc_id=document_id,
            source=source,
            source_date=source_date,
            service=metadata.get("service"),
            failure_family=metadata.get("failure_family"),
            title=metadata.get("title"),
            body=body,
            metadata=metadata,
        )
        documents.append(document)

    return documents
