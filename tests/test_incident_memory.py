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


def test_default_memory_store_reuses_one_encoder(monkeypatch):
    incidents_module._default_memory_store.cache_clear()
    monkeypatch.setattr(incidents_module, "create_embedding_encoder", FakeEncoder)

    first = incidents_module._default_memory_store()
    second = incidents_module._default_memory_store()

    assert isinstance(first, MemoryStore)
    assert first is second
    incidents_module._default_memory_store.cache_clear()


def test_save_rejects_invalid_preconditions_and_search_rejects_a_blank_query(tmp_path, monkeypatch):
    _configure_memory(monkeypatch, tmp_path / "incidents.sqlite3", MemoryStore(FakeEncoder()))
    arguments = dict(
        service="payments",
        symptom="symptom",
        root_cause="cause",
        lesson="lesson",
        fix="fix",
        reviewed_by="reviewer",
    )

    with pytest.raises(ValueError, match="preconditions must be a sequence of strings"):
        save_incident(**arguments, preconditions="not a list")
    with pytest.raises(ValueError, match="preconditions must be a sequence of strings"):
        save_incident(**arguments, preconditions=None)
    with pytest.raises(ValueError, match="precondition must not be empty"):
        save_incident(**arguments, preconditions=["ready", " "])
    with pytest.raises(ValueError, match="Search query must not be empty"):
        search_incidents(" ")
    with pytest.raises(ValueError, match="Search query must not be empty"):
        search_incidents(None)


def test_sqlite_store_rejects_memory_and_missing_files(tmp_path):
    with pytest.raises(ValueError, match="file-backed"):
        SQLiteIncidentStore(":memory:")

    assert SQLiteIncidentStore(tmp_path / "missing.sqlite3").load_all() == []


def test_memory_store_rejects_invalid_embeddings_and_search_inputs():
    incident = _incident("payment")
    other = _incident("queue")
    store = MemoryStore(FakeEncoder())

    with pytest.raises(ValueError, match="one embedding per incident"):
        MemoryStore(_FixedDocuments([[1.0], [0.0]])).embed_incident(incident)
    with pytest.raises(ValueError, match="finite numeric values"):
        store.add(incident, [])
    with pytest.raises(ValueError, match="finite numeric values"):
        store.add(incident, [float("nan")])
    with pytest.raises(ValueError, match="zero vector"):
        store.add(incident, [0.0, 0.0])

    store.add(incident, [1.0, 0.0])
    store.add(incident, [0.0, 1.0])
    with pytest.raises(ValueError, match="consistent dimension"):
        store.add(other, [1.0])

    with pytest.raises(ValueError, match="one embedding per incident"):
        MemoryStore(_FixedDocuments([[1.0, 0.0]])).replace_all([incident, other])
    with pytest.raises(ValueError, match="consistent dimension"):
        MemoryStore(_FixedDocuments([[1.0, 0.0], [1.0]])).replace_all([incident, other])
    replaced = MemoryStore(_FixedDocuments([[1.0, 0.0], [0.0, 1.0]]))
    replaced.replace_all([incident, other])
    assert set(replaced._entries) == {incident.id, other.id}

    empty_store = MemoryStore(FakeEncoder())
    with pytest.raises(ValueError, match="Search query must not be empty"):
        empty_store.search(" ")
    with pytest.raises(ValueError, match="top_k must be positive"):
        empty_store.search("payment", top_k=0)
    assert empty_store.search("payment") == []

    mismatched_query = MemoryStore(_QueryVectors([[1.0], [0.0]]))
    mismatched_query.add(incident, [1.0, 0.0])
    with pytest.raises(ValueError, match="one embedding per query"):
        mismatched_query.search("payment")

    wrong_width = MemoryStore(_QueryVectors([[1.0]]))
    wrong_width.add(incident, [1.0, 0.0])
    with pytest.raises(ValueError, match="matching dimensions"):
        wrong_width.search("payment")

    with pytest.raises(ValueError, match="zero vector"):
        MemoryStore._cosine_similarity([0.0], [1.0])
    with pytest.raises(ValueError, match="zero vector"):
        MemoryStore._cosine_similarity([1.0], [0.0])
    assert MemoryStore._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


class _FixedDocuments:
    def __init__(self, embeddings):
        self._embeddings = embeddings

    def encode(self, texts):
        return self._embeddings

    def encode_documents(self, texts):
        return self._embeddings


class _QueryVectors:
    def __init__(self, embeddings):
        self._embeddings = embeddings

    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def encode_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def encode_queries(self, texts):
        return self._embeddings


def _incident(service):
    return Incident(
        service=service,
        symptom="symptom",
        root_cause="cause",
        preconditions=("ready",),
        lesson="lesson",
        fix="fix",
        reviewed_by="reviewer",
    )


def _configure_memory(monkeypatch, database_path, memory_store):
    monkeypatch.setattr(incidents_module, "DEFAULT_DATABASE_PATH", database_path)
    monkeypatch.setattr(incidents_module, "_default_memory_store", lambda: memory_store)
