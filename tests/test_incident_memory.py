import sqlite3

import pytest

from knowledge.memory import incidents as incidents_module
from knowledge.memory import MemoryStore, save_incident, search_incidents
from knowledge.memory.models import Incident
from knowledge.memory.store import SQLiteIncidentStore


class FakeEncoder:
    def encode(self, texts):
        return [self._vector(text) for text in texts]

    def _vector(self, text):
        normalized = text.lower()
        return [float(term in normalized) for term in ("payment", "queue", "checkout")]

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


def test_default_memory_store_builds_a_store(monkeypatch):
    incidents_module._default_memory_store.cache_clear()
    monkeypatch.setattr(incidents_module, "create_embedding_encoder", FakeEncoder)
    store = incidents_module._default_memory_store()
    assert isinstance(store, MemoryStore)
    incidents_module._default_memory_store.cache_clear()


def test_search_rejects_a_blank_query(tmp_path, monkeypatch):
    _configure_memory(monkeypatch, tmp_path / "incidents.sqlite3", MemoryStore(FakeEncoder()))
    with pytest.raises(ValueError, match="Search query must not be empty"):
        search_incidents(" ")
    with pytest.raises(ValueError, match="Search query must not be empty"):
        search_incidents(None)


def test_save_rejects_preconditions_that_are_not_a_sequence(tmp_path, monkeypatch):
    _configure_memory(monkeypatch, tmp_path / "incidents.sqlite3", MemoryStore(FakeEncoder()))
    with pytest.raises(ValueError, match="preconditions must be a sequence"):
        save_incident(
            service="payments",
            symptom="symptom",
            root_cause="cause",
            preconditions="not a list",
            lesson="lesson",
            fix="fix",
            reviewed_by="reviewer",
        )
    with pytest.raises(ValueError, match="preconditions must be a sequence"):
        save_incident(
            service="payments",
            symptom="symptom",
            root_cause="cause",
            preconditions=5,
            lesson="lesson",
            fix="fix",
            reviewed_by="reviewer",
        )


def test_sqlite_store_rejects_a_memory_database():
    with pytest.raises(ValueError, match="file-backed"):
        SQLiteIncidentStore(":memory:")


def test_failure_family_round_trips_and_blank_text_is_stripped(tmp_path, monkeypatch):
    database_path = tmp_path / "incidents.sqlite3"
    memory_store = MemoryStore(FakeEncoder())
    _configure_memory(monkeypatch, database_path, memory_store)

    saved = save_incident(
        service="payment",
        symptom="Checkout requests fail",
        root_cause="paymentFailure enabled",
        preconditions=["paymentFailure enabled"],
        lesson="Turn the flag off when the evidence matches",
        fix="Set paymentFailure off",
        reviewed_by="on-call lead",
        failure_family="  payment_failure  ",
    )

    assert saved.failure_family == "payment_failure"
    assert SQLiteIncidentStore(database_path).load_all()[0].failure_family == "payment_failure"
    with pytest.raises(ValueError, match="failure_family must be a string"):
        save_incident(
            service="payment",
            symptom="Checkout requests fail",
            root_cause="paymentFailure enabled",
            preconditions=["paymentFailure enabled"],
            lesson="Turn the flag off when the evidence matches",
            fix="Set paymentFailure off",
            reviewed_by="on-call lead",
            failure_family=None,
        )


def test_older_database_gains_a_failure_family_column(tmp_path):
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE incidents (
                id TEXT PRIMARY KEY,
                service TEXT NOT NULL,
                symptom TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                preconditions TEXT NOT NULL,
                lesson TEXT NOT NULL,
                fix TEXT NOT NULL,
                reviewed_by TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("old-1", "payment", "symptom", "cause", "[]", "lesson", "fix", "reviewer"),
        )

    loaded = SQLiteIncidentStore(database_path).load_all()

    assert loaded[0].failure_family == ""
    assert "failure_family" in {
        row[1] for row in sqlite3.connect(database_path).execute("PRAGMA table_info(incidents)")
    }


def test_embed_incident_rejects_the_wrong_number_of_vectors():
    store = MemoryStore(_ScriptedEncoder(documents=[]))
    with pytest.raises(ValueError, match="one embedding per incident"):
        store.embed_incident(_incident("payments"))


def test_add_and_replace_accept_matching_dimensions():
    store = MemoryStore(FakeEncoder())
    store.add(_incident("payments"), [1.0, 0.0])
    store.add(_incident("queue"), [0.0, 1.0])
    store.replace_all([_incident("payments"), _incident("queue")])
    assert len(store.search("payment")) == 2
    store = MemoryStore(FakeEncoder())
    store.add(_incident("payments"), [1.0, 0.0])
    with pytest.raises(ValueError, match="consistent dimension"):
        store.add(_incident("queue"), [1.0])


def test_replace_all_rejects_a_short_embedding_batch():
    store = MemoryStore(_ScriptedEncoder(documents=[[1.0, 0.0]]))
    with pytest.raises(ValueError, match="one embedding per incident"):
        store.replace_all([_incident("payments"), _incident("queue")])


def test_replace_all_rejects_mixed_dimensions():
    store = MemoryStore(_ScriptedEncoder(documents=[[1.0, 0.0], [1.0]]))
    with pytest.raises(ValueError, match="consistent dimension"):
        store.replace_all([_incident("payments"), _incident("queue")])


def test_search_rejects_blank_queries_and_non_positive_limits():
    store = MemoryStore(FakeEncoder())
    store.add(_incident("payments"), [1.0, 0.0])
    with pytest.raises(ValueError, match="Search query must not be empty"):
        store.search(" ")
    with pytest.raises(ValueError, match="top_k must be positive"):
        store.search("payment", top_k=0)


def test_search_rejects_a_query_embedding_batch_of_the_wrong_size():
    store = MemoryStore(_ScriptedEncoder(documents=[[1.0, 0.0]], queries=[]))
    store.add(_incident("payments"), [1.0, 0.0])
    with pytest.raises(ValueError, match="one embedding per query"):
        store.search("payment")


def test_search_rejects_a_query_vector_with_a_different_dimension():
    store = MemoryStore(_ScriptedEncoder(documents=[[1.0, 0.0]], queries=[[1.0]]))
    store.add(_incident("payments"), [1.0, 0.0])
    with pytest.raises(ValueError, match="matching dimensions"):
        store.search("payment")


def test_embedding_validation_rejects_empty_non_finite_and_zero_vectors():
    with pytest.raises(ValueError, match="finite numeric"):
        MemoryStore._validate_embedding([])
    with pytest.raises(ValueError, match="finite numeric"):
        MemoryStore._validate_embedding([float("nan")])
    with pytest.raises(ValueError, match="zero vector"):
        MemoryStore._validate_embedding([0.0, 0.0])
    with pytest.raises(ValueError, match="zero vector"):
        MemoryStore._cosine_similarity([0.0], [1.0])


def test_encoder_without_document_methods_uses_encode():
    store = MemoryStore(_EncodeOnly())
    incident = _incident("payments")
    store.add(incident, store.embed_incident(incident))
    store.replace_all([incident])
    matches = store.search("payment")
    assert matches[0].incident == incident


def _incident(service):
    return Incident(
        service=service,
        symptom="symptom",
        root_cause="cause",
        preconditions=(),
        lesson="lesson",
        fix="fix",
        reviewed_by="reviewer",
    )


class _ScriptedEncoder:
    def __init__(self, documents, queries=None):
        self.documents = documents
        self.queries = documents if queries is None else queries

    def encode_documents(self, texts):
        return self.documents

    def encode_queries(self, texts):
        return self.queries

    def encode(self, texts):
        return self.documents


class _EncodeOnly:
    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _configure_memory(monkeypatch, database_path, memory_store):
    monkeypatch.setattr(incidents_module, "DEFAULT_DATABASE_PATH", database_path)
    monkeypatch.setattr(incidents_module, "_default_memory_store", lambda: memory_store)
