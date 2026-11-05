"""Environment settings for read-only shop telemetry."""

from __future__ import annotations

import os


class Settings:
    """Read endpoint settings when a tool runs, so tests can change the environment."""

    @property
    def PROMETHEUS_URL(self) -> str:
        return _url("PROMETHEUS_URL", "http://localhost:9090")

    @property
    def JAEGER_URL(self) -> str:
        return _url("JAEGER_URL", "http://localhost:8080")

    @property
    def JAEGER_BASE_PATH(self) -> str:
        return os.environ.get("JAEGER_BASE_PATH", "/jaeger").rstrip("/")

    @property
    def OPENSEARCH_URL(self) -> str:
        return _url("OPENSEARCH_URL", "http://localhost:9200")

    @property
    def FLAGD_UI_URL(self) -> str:
        # up.sh publishes flagd on localhost. The incident API pod sets this to the cluster address.
        return _url("FLAGD_UI_URL", "http://localhost:4000")

    @property
    def DEFAULT_RANGE_WINDOW(self) -> str:
        return os.environ.get("DEFAULT_RANGE_WINDOW", "5m")

    @property
    def ERROR_RATIO_WINDOW(self) -> str:
        return os.environ.get("ERROR_RATIO_WINDOW", "5m")

    def apply_ca_bundle_to_env(self) -> None:
        """Point TLS clients at COPILOT_CA_BUNDLE when the process has not set one."""
        bundle = os.environ.get("COPILOT_CA_BUNDLE", "").strip()
        if not bundle:
            return
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)


def _url(name: str, default: str) -> str:
    return os.environ.get(name, default).rstrip("/")


settings = Settings()
