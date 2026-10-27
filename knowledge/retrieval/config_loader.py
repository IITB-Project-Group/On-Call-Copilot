"""Load and validate retrieval and chunking settings from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).with_name("retrieval_config.yaml")


@dataclass(frozen=True)
class RetrievalConfig:
    """Tunable defaults shared by passage chunking and retrieval."""

    target_words: int
    overlap_words: int
    candidate_k: int
    rrf_k: int
    query_rewrite_count: int
    reranker_candidate_k: int
    top_k: int

    def __post_init__(self) -> None:
        """Reject invalid settings before they affect indexing or search."""
        if self.target_words <= 0:
            raise ValueError("target_words must be positive")
        if self.overlap_words < 0:
            raise ValueError("overlap_words must be non-negative")
        if self.overlap_words >= self.target_words:
            raise ValueError("overlap_words must be smaller than target_words")
        if self.candidate_k <= 0:
            raise ValueError("candidate_k must be positive")
        if self.rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        if self.query_rewrite_count < 0:
            raise ValueError("query_rewrite_count must be non-negative")
        if self.reranker_candidate_k <= 0:
            raise ValueError("reranker_candidate_k must be positive")
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")


def load_retrieval_config(config_path: str | Path | None = None) -> RetrievalConfig:
    """Read the configured YAML file and validate all required integer values."""
    path = Path(config_path) if config_path is not None else _CONFIG_PATH
    with path.open("r", encoding="utf-8") as config_file:
        raw_config: Any = yaml.safe_load(config_file)

    if not isinstance(raw_config, dict):
        raise ValueError(f"Retrieval config must be a YAML mapping: {path}")

    required_keys = {
        "target_words",
        "overlap_words",
        "candidate_k",
        "rrf_k",
        "query_rewrite_count",
        "reranker_candidate_k",
        "top_k",
    }
    missing_keys = required_keys - raw_config.keys()
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise ValueError(f"Retrieval config is missing required settings: {missing}")

    settings: dict[str, Any] = {}
    for key in required_keys:
        value = raw_config[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Retrieval config setting {key} must be an integer")
        settings[key] = value
    return RetrievalConfig(**settings)
