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
kubectl --context "${KUBE_CONTEXT}" apply -f "${ROOT}/deploy/incident-api.yaml"
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

echo
echo "Astronomy Shop is up."
echo "  Web store         http://localhost:${HOST_PORT}/"
echo "  Grafana           http://localhost:${HOST_PORT}/grafana/"
echo "  Jaeger            http://localhost:${HOST_PORT}/jaeger/ui/"
echo "  Feature flags     http://localhost:${HOST_PORT}/feature"
echo "  Load generator    http://localhost:${HOST_PORT}/loadgen/"
echo "  Incident console  http://localhost:${INCIDENT_PORT}/"
echo
echo "A service whose error rate stays above 5% for 1 minute opens an incident. paymentFailure and aiRunawayAgent are two ways to cause that."
echo
echo "Pods:"
kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get pods
exit 0

