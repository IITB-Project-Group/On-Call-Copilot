FROM python:3.12-slim

WORKDIR /app
COPY incident_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY schemas ./schemas
COPY api ./api
COPY ui ./ui
COPY incident_api/incident_api ./incident_api

ENV INCIDENT_DB=/data/incidents.sqlite3
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "incident_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
