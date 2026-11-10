#!/bin/sh
# Build the Chroma corpus only when a key is present, then serve the API.
# A failed build leaves runbook search on BM25. The index lives on /data, so a
# later start of the same volume does not embed the corpus again.
set -u

if [ -n "${OPENROUTER_API_KEY:-}" ]; then
  export EMBEDDING_API_KEY="${EMBEDDING_API_KEY:-$OPENROUTER_API_KEY}"
  export EMBEDDING_MODEL="${EMBEDDING_MODEL:-baai/bge-m3}"
  export EMBEDDING_PROVIDER="${EMBEDDING_PROVIDER:-openrouter}"
  if python -m knowledge.retrieval.build_index \
    --knowledge-dir /app/knowledge \
    --persist-directory "${COPILOT_CHROMA_DIR:-/data/chroma}"
  then
    echo "Chroma index is ready."
  else
    echo "Chroma index was not built. Runbook search stays on BM25."
  fi
else
  echo "No OpenRouter key. Runbook search stays on BM25."
fi

exec uvicorn incident_api.app:app --host 0.0.0.0 --port 8000
