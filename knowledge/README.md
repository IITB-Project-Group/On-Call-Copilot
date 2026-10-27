# On-Call Copilot

On-Call Copilot is a knowledge and memory foundation for incident response. It
organizes operational runbooks and past incidents, retrieves passage-level
evidence, and defines guardrails for safely reusing lessons. The current
implementation covers the knowledge and retrieval foundation; it is not yet a
complete autonomous incident-response agent.

## Current Status

The repository currently contains 15 runbooks and 10 postmortems. They are
ingested, chunked into 140 passage records, and indexed in the persistent local
Chroma collection. The corpus index was built with OpenRouter `baai/bge-m3` and
verified by reopening the collection in a separate process. The embedding API
key is kept in the local root `.env`, which is excluded from source control.

## Completed Components

### Knowledge corpus

- `knowledge/runbooks/` contains 15 operational guides covering service and
  failure scenarios such as payment failures, authentication refresh, Kafka
  backlogs, inventory sync, and recommendation degradation.
- `knowledge/postmortems/` contains 10 seed incidents, including a deliberately
  misleading lesson case for exercising memory safeguards.
- Markdown front matter carries fields such as IDs, service, failure family,
  title, and source date.

### Memory schema and safety policy

- `knowledge/memory/incident_memory_schema.yaml` defines incident, lesson, and
  retrieval-result structures.
- `knowledge/memory/memory-policy.md` requires evidence-backed preconditions
  before a lesson is considered applicable. Service or failure-family
  mismatches and insufficient evidence must lead to rejection rather than
  automatic reuse.
- `knowledge/retrieval/contracts.py` defines incident retrieval request/result
  records and a policy check for service, failure-family, and lesson
  preconditions.

### Ingestion and passage chunking

- `knowledge/retrieval/ingest.py` loads Markdown and retains document metadata,
  source path, and source date.
- `knowledge/retrieval/chunker.py` splits content along Markdown section and
  paragraph boundaries. The defaults target 350 words with 75-word overlap
  when a paragraph is longer than the target.
- Each passage has a stable chunk ID and retains document and citation
  provenance for retrieval results.

### Lexical and semantic retrieval

- BM25 ranks passages by lexical term matches.
- OpenRouter creates semantic embeddings. The supported model choices are
  `baai/bge-m3` and `intfloat/multilingual-e5-large`.
- Multilingual E5 receives `passage:` prefixes for indexed passages and
  `query:` prefixes for search queries. BGE-M3 does not use these prefixes.
- BM25 and semantic results are combined by `search_hybrid()` using Reciprocal
  Rank Fusion (RRF). The default candidate pool is 50 results per channel and
  the default RRF constant is 60. Fused results are deduplicated by `chunk_id`
  and retain their citation metadata.
- `search_reranked()` keeps the original query, generates up to two configured
  rewrites, retrieves each through BM25 and batched Chroma semantic search,
  fuses all rankings with RRF, then reranks the top 20 against the original
  query and returns the final top 10. If rewriting fails, it falls back to the
  original query.

### Persistent vector storage

- `knowledge/retrieval/index.py` implements `ChromaPassageStore`, which stores
  passage text, embeddings, and citation metadata in Chroma.
- The default persistent collection is `knowledge_passages` in `.chroma/`.
  Both `.chroma/` and `.env` are excluded by the root `.gitignore`.
- Indexing is repeatable: unchanged passages are not re-embedded, changed
  passages are updated, and passages removed from the source corpus are removed
  from the collection.
- The store checks the configured embedding model against the collection model
  to help prevent comparing incompatible vectors.

### Retrieval evaluation

- `knowledge/evaluation/golden_queries.yaml` currently contains 1 labeled
  smoke-test query (`dev` split). Each query has a `kind` tag (symptom-only,
  paraphrase, ambiguous, or misleading), a `dev` or `heldout` split, and
  relevant runbook/postmortem document IDs.
- `knowledge/evaluation/loader.py` loads the dataset into typed records and
  validates query structure, unique query IDs, supported tags, and every
  relevant document ID against the runbook/postmortem corpus.
- `knowledge/evaluation/metrics.py` computes document-level Recall@k and Hit@k.
  Passages are collapsed to unique documents before the cutoff is applied.
- `knowledge/evaluation/run_eval.py` runs the queries through the real
  runbooks-kb pipeline and reports per-query misses, overall scores, and
  breakdowns by kind and split. It makes live OpenRouter calls:

```powershell
& .\.venv\Scripts\python.exe -m knowledge.evaluation.run_eval
& .\.venv\Scripts\python.exe -m knowledge.evaluation.run_eval --rewrite-counts 0 2
```

  `--rewrite-counts` compares query rewriting settings without editing
  `retrieval_config.yaml`; `--split dev|heldout` limits the queries.

**Latest result (2026-10-25, 1 query):** Recall@5 and Hit@5 were 1.000 for both
`query_rewrite_count` 0 and 2. One query cannot show whether multi-query helps,
so the default stays at 2 until a larger labeled set is run.

## File Guide

This section describes the purpose of the main project files. The `.env` file
and `.chroma/` database are local runtime data; the README never contains the
API key or generated vector contents.

### Root files and local data

- `README.md` — project overview, status, setup, indexing instructions, and
  remaining retrieval work.
- `requirements.txt` — Python runtime dependencies, including `rank-bm25`,
  `python-dotenv`, `chromadb`, and `PyYAML`.
- `.gitignore` — excludes the local `.env` credentials file and `.chroma/`
  database from source control.
- `.env` — local OpenRouter provider, embedding and reranker model, and API key
  settings. It is ignored by Git and must not be shared or committed.
- `.chroma/` — generated persistent Chroma database containing embedded
  passages and their source metadata.

### Memory files

- `knowledge/memory/incident_memory_schema.yaml` — field definitions for
  incidents, reusable lessons, and retrieval results.
- `knowledge/memory/memory-policy.md` — applicability and retention guardrails;
  lessons require matching service, failure family, and evidence-backed
  preconditions.

### Retrieval files

- `knowledge/retrieval/__init__.py` — public exports for the retrieval
  contracts, ingestion, chunking, encoder, and Chroma store.
- `knowledge/retrieval/contracts.py` — request/response data structures and
  the lesson precondition policy check, plus ranked-passage and complete-runbook
  response records. `postmortem_ids` identifies retrieved postmortems. The
  standalone `LessonCandidate` type and policy check are retained for future
  Memory integration, but are not fields in the RAG response.
- `knowledge/retrieval/ingest.py` — reads Markdown documents and extracts
  front matter, source paths, dates, service, and failure-family metadata.
- `knowledge/retrieval/chunker.py` — splits documents into section-aware
  passage chunks and assigns stable chunk IDs with provenance.
- `knowledge/retrieval/index.py` — OpenRouter embedding client, BM25 passage
  retrieval, persistent Chroma indexing/search, metadata serialization,
  semantic similarity results, RRF hybrid fusion, and OpenRouter reranking.
- `knowledge/retrieval/config_loader.py` and
  `knowledge/retrieval/retrieval_config.yaml` — typed, validated defaults for
  chunking, query rewriting, candidate limits, and RRF.
- `knowledge/retrieval/query_rewriter.py` — OpenRouter query rewrite client;
  the model is configured by `QUERY_REWRITE_MODEL` in `.env`.
- `knowledge/retrieval/build_index.py` — command-line corpus indexer; selects
  runbooks and postmortems, chunks them, and synchronizes new, changed, or
  removed passages with Chroma.
- `knowledge/retrieval/service.py` — in-process orchestration entry point for
  the `runbooks-kb` tool. It accepts a query-only request, calls
  `search_reranked()`, returns ranked runbook/postmortem passages, and attaches
  full source text and front matter for matched runbooks. It does not access
  Memory or apply lessons yet.
- `knowledge/retrieval/runtime.py` — one-time startup function that loads
  documents/chunks and composes the encoder, Chroma store, hybrid index, and
  retrieval service.
- `knowledge/retrieval/runbooks_kb_tool.py` — reusable callable adapter for an
  MCP/tool host plus a terminal CLI that prints the response as JSON.
- `knowledge/evaluation/golden_queries.yaml` — 30-query labeled evaluation
  dataset with `dev` and `heldout` splits.
- `knowledge/evaluation/loader.py` — typed dataset loader and corpus-label
  validator for evaluation queries.

### Runbooks

Each runbook defines the scope and signals for an operational failure, how to
confirm it, a remediation procedure, and verification steps.

- `knowledge/runbooks/ad-high-cpu.md` — investigate and remediate high CPU on
  the ad service.
- `knowledge/runbooks/auth-token-refresh.md` — diagnose and recover
  authentication token refresh failures.
- `knowledge/runbooks/cart-failure.md` — diagnose cart service failures that
  affect add-to-cart and checkout flows.
- `knowledge/runbooks/checkout-session-corruption.md` — investigate corrupted
  checkout session state.
- `knowledge/runbooks/email-memory-leak.md` — respond to memory growth and
  degradation in the email service.
- `knowledge/runbooks/fraud-scan-timeout.md` — diagnose and remediate fraud
  scan timeouts.
- `knowledge/runbooks/image-slow-load.md` — investigate slow storefront image
  retrieval and rendering.
- `knowledge/runbooks/inventory-sync-failure.md` — recover inventory
  synchronization and stale stock data.
- `knowledge/runbooks/kafka-queue-problems.md` — investigate Kafka queue
  backlog and processing lag.
- `knowledge/runbooks/payment-failure.md` — diagnose payment-path failures and
  verify recovery.
- `knowledge/runbooks/product-catalog-failure.md` — troubleshoot broken or
  incomplete product catalog responses.
- `knowledge/runbooks/recommendation-cache-failure.md` — recover from
  recommendation cache failures or stale results.
- `knowledge/runbooks/recommendation-ranking-degradation.md` — investigate
  degraded recommendation ranking quality.
- `knowledge/runbooks/search-index-lag.md` — diagnose indexing delays and
  stale search results.
- `knowledge/runbooks/shipping-delay.md` — investigate shipping delay
  anomalies.

### Postmortems

Each postmortem records an incident summary, timeline, root cause, remediation,
and follow-up lessons or evidence conditions.

- `knowledge/postmortems/ad-cpu-incident.md` — ad-service CPU saturation caused
  by the `adHighCpu` failure flag.
- `knowledge/postmortems/cart-flag-incident.md` — cart and checkout disruption
  linked to the active `cartFailure` flag.
- `knowledge/postmortems/email-memory-leak-incident.md` — email processing
  degradation caused by a memory leak.
- `knowledge/postmortems/image-latency-incident.md` — storefront image latency
  caused by delayed image retrieval.
- `knowledge/postmortems/inventory-sync-incident.md` — inventory drift
  resolved through a controlled retry and known-good snapshot restore.
- `knowledge/postmortems/kafka-backlog-incident.md` — Kafka backlog and
  downstream processing lag caused by a queue failure.
- `knowledge/postmortems/misleading-lesson-case.md` — guardrail example where
  an ad CPU lesson appears superficially relevant, but payment evidence points
  to a different root cause.
- `knowledge/postmortems/payment-flag-incident.md` — checkout failures traced
  to the active `paymentFailure` flag and payment evidence.
- `knowledge/postmortems/product-catalog-incident.md` — incomplete catalog
  responses caused by an injected catalog failure.
- `knowledge/postmortems/recommendation-cache-incident.md` — stale or invalid
  recommendations caused by a cache failure.

### Tests

- `tests/test_chunking.py` — checks passage chunk creation and provenance.
- `tests/test_hybrid_index.py` — checks lexical/semantic retrieval, OpenRouter
  configuration and prefixes, multi-query RRF, rewrite behavior, rerank
  request/mapping, Chroma persistence, and repeatable corpus sync.
- `tests/test_ingest_metadata.py` — checks that source and document metadata
  survive ingestion.
- `tests/test_retrieval_contract.py` — checks retrieval data contracts and
  acceptance/rejection of lessons under the memory policy.
- `tests/test_retrieval_service.py` — checks request-to-query construction,
  passage grouping, full-runbook attachment, and separation of postmortem
  context without making API calls.
- `tests/test_runbooks_kb_tool.py` — checks one-time initialization, repeated
  query forwarding, blank-query rejection, and JSON output without API calls.
- `tests/test_evaluation_loader.py` — checks the labeled dataset and rejects
  unknown document IDs, duplicate query IDs, and unsupported query kinds.
- `tests/test_live_runbook_retrieval.py` — opt-in live test of a supplied query
  through Chroma, RRF, and OpenRouter; skipped unless
  `RUN_LIVE_RETRIEVAL_TESTS=1` is set and requires `LIVE_RETRIEVAL_QUERY`.

## Setup

The project uses Python, `uv`, and the dependencies in `requirements.txt`. From
PowerShell at the repository root:

```powershell
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

Create or edit the root `.env` file locally. Do not commit it or share its
contents:

```dotenv
EMBEDDING_PROVIDER=openrouter
EMBEDDING_MODEL=baai/bge-m3
QUERY_REWRITE_MODEL=openai/gpt-4.1-mini
RERANKER_MODEL=cohere/rerank-v3.5
EMBEDDING_API_KEY=your-openrouter-api-key
```

You can instead set `EMBEDDING_MODEL=intfloat/multilingual-e5-large`. The
optional `EMBEDDING_BASE_URL` defaults to `https://openrouter.ai/api/v1`. Shell
environment variables take precedence over values in `.env`. OpenRouter usage
may incur charges; configure an appropriate spending limit for the key.

## Build Or Refresh The Chroma Index

From the repository root, run:

```powershell
& .\.venv\Scripts\python.exe -m knowledge.retrieval.build_index
```

The command reads only `knowledge/runbooks/` and `knowledge/postmortems/`,
chunks their contents, embeds new or changed passages in batches of 32, and
synchronizes the default Chroma collection. The last successful indexing run
reported 25 source documents and 140 passages. Re-running after no source
changes should report zero new or updated passages and make no passage
embedding requests.

The indexer supports `--knowledge-dir`, `--persist-directory`,
`--collection-name`, and `--batch-size` options. For example, use
`--persist-directory .chroma-dev` to write to a separate local store.

Chunking and retrieval parameters are configured in
`knowledge/retrieval/retrieval_config.yaml`: `target_words=350`,
`overlap_words=75`, `candidate_k=50`, `rrf_k=60`, `query_rewrite_count=2`,
and default `top_k=10`. The reranker candidate limit is
`reranker_candidate_k=20`; its model is set with `RERANKER_MODEL` in `.env`.
`QUERY_REWRITE_MODEL` selects the OpenRouter chat model used to generate query
variants. Embeddings for all variants are batched into one request, and the
original query is used for reranking. Rewriting adds one chat-completion request
per search. `top_k` is the final number returned to the agent; reranker
candidates are controlled separately. Changing chunk sizes changes passage
boundaries; rerun corpus indexing afterward, which may create new embedding
requests.

## Query The Semantic Store

After building the index, semantic search can reopen the persisted collection:

```python
from knowledge.retrieval import (
  ChromaPassageStore,
  HybridCandidateIndex,
  chunk_markdown_documents,
  create_embedding_encoder,
)
from knowledge.retrieval.build_index import load_retrieval_documents

encoder = create_embedding_encoder()
store = ChromaPassageStore(encoder)
documents = load_retrieval_documents("knowledge")
chunks = chunk_markdown_documents(documents)
index = HybridCandidateIndex(chunks, encoder, vector_store=store)
results = index.search_hybrid("payment authorization failures", top_k=5)

for result in results:
  print(result.chunk["chunk_id"], result.chunk["source"], result.score)
```

Each result includes the passage text and citation metadata, including the
source path and date. Query embedding requests are made through OpenRouter.
Hybrid search combines in-memory BM25 candidate ranks with persistent Chroma
semantic candidate ranks; the BM25 index is rebuilt from the loaded chunks.
To use OpenRouter reranking instead, call
`index.search_reranked("payment authorization failures")`. That method uses the
configured 20-passage RRF pool and returns up to 10 reranked passages by default.

For the Runbooks KB tool, initialize once at host startup and reuse it for each
query:

```python
from knowledge.retrieval.contracts import RetrievalResponse
from knowledge.retrieval.runbooks_kb_tool import create_runbooks_kb_tool

runbooks_kb = create_runbooks_kb_tool()

def search_knowledge(query: str) -> RetrievalResponse:
  """Return runbook and postmortem retrieval results for an incident query."""
  return runbooks_kb(query)

response = search_knowledge("Payment authorization requests are failing.")
```

To run one query from PowerShell and print the full `RetrievalResponse` as JSON:

```powershell
& .\.venv\Scripts\python.exe -m knowledge.retrieval.runbooks_kb_tool --query "Payment authorization requests are failing."
```

## Tests

Run the test suite from the repository root:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests -q
```

Tests cover retrieval contracts and policy checks, ingestion metadata, passage
chunking, BM25 and semantic candidate search, OpenRouter configuration and E5
prefixes, query rewriting, RRF fusion, reranking, Chroma persistence, repeatable
corpus synchronization, the runbooks-kb tool wrapper, and evaluation dataset
validation and Recall@5 metrics. The latest full run passed 49 tests, with the opt-in live test
skipped. Chroma
currently emits a dependency deprecation warning under Python 3.14; it does not
fail the tests.

## Remaining Retrieval Work

- Grow the labeled query set beyond the single smoke-test query, then rerun the
  `--rewrite-counts 0 2` comparison to decide whether multi-query is worth its
  cost.
- Connect retrieved lessons to the incident workflow and verify the memory
  policy is enforced end to end before any lesson is applied.