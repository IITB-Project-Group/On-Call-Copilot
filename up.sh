#!/usr/bin/env bash
# Bring up the OpenTelemetry Astronomy Shop on a local kind cluster.
#
# Creates the kind cluster "otel-demo" if it does not exist, installs the
# OpenTelemetry Demo Helm chart, and publishes the shop on http://localhost:8080.
# Safe to run again: an existing cluster and release are left in place.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="otel-demo"
NAMESPACE="otel-demo"
RELEASE="otel-demo"
HOST_PORT="8080"
NODE_PORT="30080"
INCIDENT_PORT="8000"
TELEMETRY_MCP_PORT="8012"
RUNBOOKS_MCP_PORT="8013"
WAIT_SECONDS="1200"
HELM_REPO="https://open-telemetry.github.io/opentelemetry-helm-charts"
KUBE_CONTEXT="kind-${CLUSTER_NAME}"
IMAGE_NAME="oncall-incident-api:local"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need kind
need helm
need kubectl
need docker

if ! docker info >/dev/null 2>&1; then
  echo "The container runtime is not reachable. Start Rancher Desktop (or the Podman machine) and retry." >&2
  exit 1
fi

# Rancher Desktop's docker CLI talks to rootless Podman, but `docker info` leaves
# CPUShares false. kind then refuses to start and asks for systemd Delegate=yes,
# even when the Podman VM already has that property. The Podman provider reads
# cgroup controllers from `podman info`, which includes cpu, memory, and pids.
RUNTIME="docker"
cpu_shares="$(docker info --format '{{json .CPUShares}}' 2>/dev/null || echo true)"
# Podman 6 cannot list kind clusters: its Labels field is a slice, and kind's
# Podman provider indexes it as a map. Create a new cluster with that provider,
# because the Docker CLI reports CPUShares=false and kind refuses to create.
# List and load through the Docker CLI, which talks to the same Podman engine.
CREATE_PROVIDER=()
if [[ "${cpu_shares}" == "false" ]] && command -v podman >/dev/null 2>&1; then
  RUNTIME="podman"
  CREATE_PROVIDER=(env KIND_EXPERIMENTAL_PROVIDER=podman)
  echo "New kind clusters will use the Podman provider. Existing clusters are listed through the docker CLI."
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

cat >"${workdir}/kind-config.yaml" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: ${CLUSTER_NAME}
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: ${NODE_PORT}
        hostPort: ${HOST_PORT}
        protocol: TCP
EOF

cp "${ROOT}/deploy/shop-values.yaml" "${workdir}/values.yaml"

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  echo "Kind cluster ${CLUSTER_NAME} already exists."
  published="$("${RUNTIME}" port "${CLUSTER_NAME}-control-plane" "${NODE_PORT}/tcp" 2>/dev/null || true)"
  if [[ "${published}" != *":${HOST_PORT}"* ]]; then
    echo "That cluster does not publish host port ${HOST_PORT}." >&2
    echo "Remove it, then run this script again:" >&2
    echo "  kind delete cluster --name ${CLUSTER_NAME}" >&2
    exit 1
  fi
else
  if lsof -nP -iTCP:"${HOST_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port ${HOST_PORT} is already in use. Free it before creating the cluster." >&2
    exit 1
  fi
  echo "Creating kind cluster ${CLUSTER_NAME}."
  "${CREATE_PROVIDER[@]}" kind create cluster --name "${CLUSTER_NAME}" --config "${workdir}/kind-config.yaml"
fi

if ! helm repo list -o json 2>/dev/null | grep -q '"name":"open-telemetry"'; then
  helm repo add open-telemetry "${HELM_REPO}"
fi
helm repo update open-telemetry

install_shop() {
  echo "Installing the Astronomy Shop. The first run pulls images and can take several minutes."
  helm install "${RELEASE}" open-telemetry/opentelemetry-demo \
    --kube-context "${KUBE_CONTEXT}" \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    --values "${workdir}/values.yaml" \
    --timeout 20m
}

if helm --kube-context "${KUBE_CONTEXT}" status "${RELEASE}" --namespace "${NAMESPACE}" >/dev/null 2>&1; then
  if kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get statefulset -o name 2>/dev/null | grep -q alertmanager; then
    echo "Helm release ${RELEASE} is already installed in namespace ${NAMESPACE}."
  else
    echo "Alertmanager is missing. Reinstalling the shop so the checkout alert can fire."
    helm uninstall "${RELEASE}" --kube-context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" --wait --timeout 10m
    install_shop
  fi
else
  install_shop
fi

echo "Waiting for pods in namespace ${NAMESPACE}."
deadline=$((SECONDS + WAIT_SECONDS))
while (( SECONDS < deadline )); do
  if ! kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get pods --no-headers >/dev/null 2>&1; then
    sleep 5
    continue
  fi

  pending="$(
    kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get pods --no-headers 2>/dev/null |
      awk '$3 != "Running" && $3 != "Completed" { count++ } END { print count + 0 }'
  )"
  total="$(
    kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get pods --no-headers 2>/dev/null |
      awk 'END { print NR + 0 }'
  )"

  echo "  ${pending} of ${total} pods are not ready yet."
  if (( total > 0 && pending == 0 )); then
    break
  fi
  sleep 15
done

if (( SECONDS >= deadline )); then
  echo "Timed out after $((WAIT_SECONDS / 60)) minutes. Current pods:" >&2
  kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get pods >&2 || true
  exit 1
fi

echo "Building the incident API image."
docker build --load -f "${ROOT}/incident_api/Dockerfile" -t "${IMAGE_NAME}" "${ROOT}"
kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}"
# Models are deploy/copilot-models.yaml. The key is the shell variable, or deploy/openrouter-secret.yaml.
echo "Applying the copilot-models ConfigMap."
kubectl --context "${KUBE_CONTEXT}" apply -f "${ROOT}/deploy/copilot-models.yaml"
secret_updated=0
secret_file="${ROOT}/deploy/openrouter-secret.yaml"
if [[ -z "${OPENROUTER_API_KEY:-}" && -f "${secret_file}" ]]; then
  OPENROUTER_API_KEY="$(
    awk '
      $1 == "api-key:" {
        val = $0
        sub(/^[[:space:]]*api-key:[[:space:]]*/, "", val)
        gsub(/^["'\'']|["'\'']$/, "", val)
        print val
        exit
      }
    ' "${secret_file}"
  )"
  if [[ -z "${OPENROUTER_API_KEY}" || "${OPENROUTER_API_KEY}" == "REPLACE_ME" ]]; then
    unset OPENROUTER_API_KEY
    echo "deploy/openrouter-secret.yaml has no api-key. The API uses the fixed workflow."
  fi
fi
if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
  echo "Storing the OpenRouter key in secret openrouter."
  kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" create secret generic openrouter \
    --from-literal=api-key="${OPENROUTER_API_KEY}" \
    --dry-run=client -o yaml |
    kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" apply -f -
  secret_updated=1
else
  echo "No OpenRouter key. Copy deploy/openrouter-secret.example.yaml to deploy/openrouter-secret.yaml, or export OPENROUTER_API_KEY. The API uses the fixed workflow."
fi
unset OPENROUTER_API_KEY
kubectl --context "${KUBE_CONTEXT}" apply -f "${ROOT}/deploy/incident-api.yaml"
kubectl --context "${KUBE_CONTEXT}" apply -f "${ROOT}/deploy/grafana-dashboard-copilot.yaml"
if (( secret_updated == 1 )); then
  kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" rollout restart deployment/incident-api
fi
kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" rollout status deployment/incident-api --timeout=180s

# OpenSearch maps attributes.http as text after the first string value, then
# rejects later logs that use attributes.http.request.method. Those rejected
# batches include the payment failure lines, so Grafana stops updating.
# Store attributes without indexing them. Resource fields stay searchable.
kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" exec -i deploy/incident-api -- python - <<'PY'
import json
import urllib.error
import urllib.request

base = "http://opensearch:9200"
template = {
    "index_patterns": ["otel-logs-*"],
    "priority": 200,
    "template": {
        "mappings": {
            "properties": {"attributes": {"type": "object", "enabled": False}}
        }
    },
}

def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()

status, body = call("PUT", "/_index_template/otel-logs-attributes", template)
print(f"log template {status} {body[:200]}")
status, body = call("GET", "/otel-logs-*/_mapping/field/attributes.http")
if '"type":"text"' in body.replace(" ", ""):
    status, body = call("DELETE", "/otel-logs-*")
    print(f"recreated log index {status} {body[:200]}")
PY

if lsof -nP -iTCP:"${INCIDENT_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port ${INCIDENT_PORT} is already in use."
else
  # kubectl port-forward exits when the pod connection resets, which a shop
  # failure can trigger. The local listener stays up and dials a new forward.
  pf_pid="$(
    KUBE_CONTEXT="${KUBE_CONTEXT}" NAMESPACE="${NAMESPACE}" INCIDENT_PORT="${INCIDENT_PORT}" \
      ROOT="${ROOT}" python3 - <<'PY'
import os

pid = os.fork()
if pid > 0:
    print(pid)
    raise SystemExit(0)
os.setsid()
log = os.open(
    "/tmp/oncall-incident-api-port-forward.log",
    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
    0o644,
)
os.dup2(log, 1)
os.dup2(log, 2)
os.close(log)
script = os.path.join(os.environ["ROOT"], "deploy", "incident-port-forward.py")
os.execvp("python3", ["python3", script])
PY
  )"
  echo "${pf_pid}" >/tmp/oncall-incident-api-port-forward.pid
fi

console_ready=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS -m 2 "http://127.0.0.1:${INCIDENT_PORT}/healthz" >/dev/null 2>&1; then
    console_ready=1
    break
  fi
  sleep 1
done
if (( console_ready == 0 )); then
  echo "Incident console did not answer on http://127.0.0.1:${INCIDENT_PORT}/healthz." >&2
  tail -20 /tmp/oncall-incident-api-port-forward.log >&2 || true
  exit 1
fi

prom_svc="$(
  kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get svc -o name |
    sed 's|service/||' |
    awk '$0 == "prometheus" || $0 == "prometheus-server" || $0 ~ /-prometheus-server$/ { print; exit }'
)"
if [[ -z "${prom_svc}" ]]; then
  echo "No Prometheus server service in namespace ${NAMESPACE}." >&2
  kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get svc >&2 || true
  exit 1
fi
prom_port="$(
  kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get "svc/${prom_svc}" \
    -o jsonpath='{.spec.ports[0].port}'
)"
live_env=(
  "COPILOT_AGENT=${COPILOT_AGENT:-c2}"
  "PROMETHEUS_URL=http://${prom_svc}:${prom_port}"
  "OPENSEARCH_URL=http://opensearch:9200"
  "JAEGER_URL=http://frontend-proxy:8080"
  "JAEGER_BASE_PATH=/jaeger/ui"
)
kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" set env deploy/incident-api "${live_env[@]}"
kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" rollout status deployment/incident-api --timeout=180s
for service in opensearch flagd; do
  if ! kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get "svc/${service}" >/dev/null 2>&1; then
    echo "Service ${service} is missing from namespace ${NAMESPACE}." >&2
    exit 1
  fi
done

tool_ports=(9090 9200 4000 8016)
listening=0
for port in "${tool_ports[@]}"; do
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    listening=$((listening + 1))
  fi
done
if (( listening == ${#tool_ports[@]} )); then
  echo "Tool endpoints are already listening on localhost."
elif (( listening > 0 )); then
  echo "Free ports 9090, 9200, 4000, and 8016, then run this script again." >&2
  exit 1
else
  shop_pid="$(
    KUBE_CONTEXT="${KUBE_CONTEXT}" NAMESPACE="${NAMESPACE}" ROOT="${ROOT}" \
      SHOP_FORWARDS="${prom_svc}=9090:${prom_port},opensearch=9200:9200,flagd=4000:4000,flagd=8016:8016" \
      python3 - <<'PY'
import os

pid = os.fork()
if pid > 0:
    print(pid)
    raise SystemExit(0)
os.setsid()
log = os.open(
    "/tmp/oncall-shop-port-forward.log",
    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
    0o644,
)
os.dup2(log, 1)
os.dup2(log, 2)
os.close(log)
os.execvp(
    "python3",
    ["python3", os.path.join(os.environ["ROOT"], "deploy", "shop-port-forward.py")],
)
PY
  )"
  echo "${shop_pid}" >/tmp/oncall-shop-port-forward.pid
fi

tools_ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if curl -fsS -m 2 "http://127.0.0.1:9090/-/ready" >/dev/null 2>&1 \
    && curl -fsS -m 2 "http://127.0.0.1:9200/" >/dev/null 2>&1 \
    && curl -fsS -m 2 "http://127.0.0.1:4000/api/read" >/dev/null 2>&1; then
    tools_ready=1
    break
  fi
  sleep 1
done
if (( tools_ready == 0 )); then
  echo "Prometheus, OpenSearch, or flagd did not answer on localhost." >&2
  tail -20 /tmp/oncall-shop-port-forward.log >&2 || true
  exit 1
fi

python="${ROOT}/.venv/bin/python"
if [[ ! -x "${python}" ]]; then
  echo "The project virtualenv is missing, so the copilot MCP servers were not started." >&2
  echo "Create it and install the project, then run this script again." >&2
  exit 1
fi
if ! "${python}" -c 'import fastmcp' >/dev/null 2>&1; then
  echo "fastmcp is not installed in ${python}, so the copilot MCP servers were not started." >&2
  echo "Install the project into that virtualenv, then run this script again." >&2
  exit 1
fi

start_mcp() {
  local module="$1"
  local port="$2"
  local port_env="$3"
  local pid_file="$4"
  local log_file="$5"
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Copilot MCP ${module} is already listening on localhost:${port}."
    return 0
  fi
  local pid
  pid="$(
    ROOT="${ROOT}" MODULE="${module}" PORT="${port}" PORT_ENV="${port_env}" \
      LOG_FILE="${log_file}" PYTHON="${python}" \
      python3 - <<'PY'
import os

pid = os.fork()
if pid > 0:
    print(pid)
    raise SystemExit(0)
os.setsid()
log = os.open(os.environ["LOG_FILE"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
os.dup2(log, 1)
os.dup2(log, 2)
os.close(log)
root = os.environ["ROOT"]
os.environ["PYTHONPATH"] = os.pathsep.join((root, os.path.join(root, "safety")))
os.environ["MCP_TRANSPORT"] = "http"
os.environ["MCP_HOST"] = "127.0.0.1"
os.environ[os.environ["PORT_ENV"]] = os.environ["PORT"]
os.environ.setdefault("JAEGER_BASE_PATH", "/jaeger/ui")
python = os.environ["PYTHON"]
module = os.environ["MODULE"]
os.execv(python, [python, "-m", module])
PY
  )"
  echo "${pid}" >"${pid_file}"
}

mcp_ready() {
  "${python}" - "$1" <<'PY'
import json
import sys
import urllib.error
import urllib.request

port = sys.argv[1]
body = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "up.sh", "version": "0"},
        },
    }
).encode()
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/mcp",
    data=body,
    method="POST",
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    },
)
try:
    with urllib.request.urlopen(request, timeout=2) as response:
        raise SystemExit(0 if response.status == 200 else 1)
except (urllib.error.URLError, TimeoutError):
    raise SystemExit(1)
PY
}

start_mcp tools.telemetry.server "${TELEMETRY_MCP_PORT}" TELEMETRY_MCP_PORT \
  /tmp/oncall-telemetry-mcp.pid /tmp/oncall-telemetry-mcp.log
start_mcp tools.runbooks.server "${RUNBOOKS_MCP_PORT}" RUNBOOKS_MCP_PORT \
  /tmp/oncall-runbooks-mcp.pid /tmp/oncall-runbooks-mcp.log

mcp_servers_ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if mcp_ready "${TELEMETRY_MCP_PORT}" && mcp_ready "${RUNBOOKS_MCP_PORT}"; then
    mcp_servers_ready=1
    break
  fi
  sleep 1
done
if (( mcp_servers_ready == 0 )); then
  echo "The copilot MCP servers did not answer on localhost." >&2
  tail -20 /tmp/oncall-telemetry-mcp.log >&2 || true
  tail -20 /tmp/oncall-runbooks-mcp.log >&2 || true
  exit 1
fi

echo
echo "Astronomy Shop is up."
echo "  Web store         http://localhost:${HOST_PORT}/"
echo "  Grafana           http://localhost:${HOST_PORT}/grafana/"
echo "  Jaeger            http://localhost:${HOST_PORT}/jaeger/ui/"
echo "  Feature flags     http://localhost:${HOST_PORT}/feature"
echo "  Load generator    http://localhost:${HOST_PORT}/loadgen/"
echo "  Incident console  http://localhost:${INCIDENT_PORT}/"
echo "  Prometheus        http://localhost:9090/"
echo "  OpenSearch        http://localhost:9200/"
echo "  Flagd             http://localhost:4000/api/read"
echo "  Telemetry MCP     http://127.0.0.1:${TELEMETRY_MCP_PORT}/mcp"
echo "  Runbooks MCP      http://127.0.0.1:${RUNBOOKS_MCP_PORT}/mcp"
echo
echo "A service whose error rate stays above 5% over 5 minutes opens an incident. paymentFailure and aiRunawayAgent are two ways to cause that."
echo "The incident API runs the agent graph (COPILOT_AGENT=${COPILOT_AGENT:-c2}; without secret openrouter it uses the fixed workflow)."
echo "The copilot MCP servers read Prometheus, Jaeger, OpenSearch, and flagd on these localhost ports."
echo
echo "Pods:"
kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get pods
exit 0

