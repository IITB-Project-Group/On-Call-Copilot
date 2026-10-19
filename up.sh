#!/usr/bin/env bash
# Bring up the OpenTelemetry Astronomy Shop on a local kind cluster.
#
# Creates the kind cluster "otel-demo" if it does not exist, installs the
# OpenTelemetry Demo Helm chart, and publishes the shop on http://localhost:8080.
# Safe to run again: an existing cluster and release are left in place.

set -euo pipefail

CLUSTER_NAME="otel-demo"
NAMESPACE="otel-demo"
RELEASE="otel-demo"
HOST_PORT="8080"
NODE_PORT="30080"
WAIT_SECONDS="1200"
HELM_REPO="https://open-telemetry.github.io/opentelemetry-helm-charts"
KUBE_CONTEXT="kind-${CLUSTER_NAME}"

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
if [[ "${cpu_shares}" == "false" ]] && command -v podman >/dev/null 2>&1; then
  export KIND_EXPERIMENTAL_PROVIDER="podman"
  RUNTIME="podman"
  echo "Using kind's Podman provider. The docker CLI reports rootless Podman without CPU share limits."
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

cat >"${workdir}/values.yaml" <<EOF
components:
  frontend-proxy:
    service:
      type: NodePort
      nodePort: ${NODE_PORT}
EOF

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
  kind create cluster --name "${CLUSTER_NAME}" --config "${workdir}/kind-config.yaml"
fi

if ! helm repo list -o json 2>/dev/null | grep -q '"name":"open-telemetry"'; then
  helm repo add open-telemetry "${HELM_REPO}"
fi
helm repo update open-telemetry

if helm --kube-context "${KUBE_CONTEXT}" status "${RELEASE}" --namespace "${NAMESPACE}" >/dev/null 2>&1; then
  echo "Helm release ${RELEASE} is already installed in namespace ${NAMESPACE}."
else
  echo "Installing the Astronomy Shop. The first run pulls images and can take several minutes."
  helm install "${RELEASE}" open-telemetry/opentelemetry-demo \
    --kube-context "${KUBE_CONTEXT}" \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    --values "${workdir}/values.yaml" \
    --timeout 20m
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
    echo
    echo "Astronomy Shop is up."
    echo "  Web store       http://localhost:${HOST_PORT}/"
    echo "  Grafana         http://localhost:${HOST_PORT}/grafana/"
    echo "  Jaeger          http://localhost:${HOST_PORT}/jaeger/ui/"
    echo "  Feature flags   http://localhost:${HOST_PORT}/feature"
    echo "  Load generator  http://localhost:${HOST_PORT}/loadgen/"
    echo
    echo "Pods:"
    kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get pods
    exit 0
  fi
  sleep 15
done

echo "Timed out after $((WAIT_SECONDS / 60)) minutes. Current pods:" >&2
kubectl --context "${KUBE_CONTEXT}" --namespace "${NAMESPACE}" get pods >&2 || true
exit 1
