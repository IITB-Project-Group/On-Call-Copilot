FROM python:3.12-slim

WORKDIR /app
COPY incident_api/requirements.txt incident_api/requirements-agents.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-agents.txt
COPY schemas ./schemas
COPY api ./api
COPY ui ./ui
COPY tools ./tools
COPY safety ./safety
COPY agents ./agents
COPY graph ./graph
COPY knowledge/runbooks ./knowledge/runbooks
COPY knowledge/playbook ./knowledge/playbook
COPY incident_api/incident_api ./incident_api

ENV INCIDENT_DB=/data/incidents.sqlite3
ENV PYTHONPATH=/app:/app/safety
EXPOSE 8000
CMD ["uvicorn", "incident_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
