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
COPY knowledge/__init__.py ./knowledge/__init__.py
COPY knowledge/runbooks ./knowledge/runbooks
COPY knowledge/postmortems ./knowledge/postmortems
COPY knowledge/playbook ./knowledge/playbook
COPY knowledge/retrieval ./knowledge/retrieval
COPY incident_api/incident_api ./incident_api
COPY incident_api/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV INCIDENT_DB=/data/incidents.sqlite3
ENV PYTHONPATH=/app:/app/safety
EXPOSE 8000
CMD ["/entrypoint.sh"]
