import pytest

from knowledge.memory import incidents as incidents_module
from knowledge.memory import MemoryStore, save_incident, search_incidents


class FakeEncoder:
    def encode(self, texts):
        return [self._vector(text) for text in texts]

    def _vector(self, text):
        normalized = text.lower()
        return [
            float(term in normalized)
            for term in ("payment", "queue", "checkout")
        ]

    def encode_documents(self, texts):
        return [self._vector(text) for text in texts]

    def encode_queries(self, texts):
        return [self._vector(text) for text in texts]


def test_save_and_semantically_search_incidents_from_sqlite(tmp_path, monkeypatch):
    database_path = tmp_path / "incidents.sqlite3"
    memory_store = MemoryStore(FakeEncoder())
    _configure_memory(monkeypatch, database_path, memory_store)

    saved = save_incident(
        service="payments",
        symptom="Checkout requests fail",
        root_cause="Payment service outage",
        preconditions=["Payment traces show timeout errors"],
        lesson="Check payment health before retrying checkout",
        fix="Restore payment service and verify checkout",
        reviewed_by="on-call lead",
    )

    matches = search_incidents(
        "payment outage affecting checkout",
    )

    assert matches[0].incident == saved
    assert matches[0].score > 0
    assert matches[0].incident.preconditions == ("Payment traces show timeout errors",)


def test_search_loads_database_records_into_fresh_memory_store(tmp_path, monkeypatch):
    database_path = tmp_path / "incidents.sqlite3"
    encoder = FakeEncoder()
    initial_store = MemoryStore(encoder)
    _configure_memory(monkeypatch, database_path, initial_store)
    saved = save_incident(
        service="queue",
        symptom="Consumers are lagging",
        root_cause="Queue backlog",
        preconditions=[],
        lesson="Check consumer throughput",
        fix="Scale consumers",
        reviewed_by="reviewer",
    )
    fresh_store = MemoryStore(encoder)
    monkeypatch.setattr(incidents_module, "_default_memory_store", lambda: fresh_store)

    matches = search_incidents("queue backlog")

    assert len(matches) == 1
    assert matches[0].incident.id == saved.id


def test_search_returns_empty_for_empty_database(tmp_path, monkeypatch):
    _configure_memory(
        monkeypatch,
        tmp_path / "empty.sqlite3",
        MemoryStore(FakeEncoder()),
    )
    matches = search_incidents("payment failure")

    assert matches == []


def test_save_rejects_empty_required_fields(tmp_path, monkeypatch):
    _configure_memory(
        monkeypatch,
        tmp_path / "incidents.sqlite3",
        MemoryStore(FakeEncoder()),
    )
    with pytest.raises(ValueError, match="service must not be empty"):
        save_incident(
            service=" ",
            symptom="symptom",
            root_cause="cause",
            preconditions=[],
            lesson="lesson",
            fix="fix",
            reviewed_by="reviewer",
        )


def _configure_memory(monkeypatch, database_path, memory_store):
    monkeypatch.setattr(incidents_module, "DEFAULT_DATABASE_PATH", database_path)
    monkeypatch.setattr(incidents_module, "_default_memory_store", lambda: memory_store)
