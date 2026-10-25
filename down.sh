#!/usr/bin/env bash
# Stop the incident console port-forward and delete the otel-demo kind cluster.
#
# The port-forward is started by up.sh in its own session, so deleting the
# cluster does not free localhost:8000.

set -euo pipefail

CLUSTER_NAME="otel-demo"
INCIDENT_PORT="8000"
PID_FILE="/tmp/oncall-incident-api-port-forward.pid"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need kind

stop_port_forward() {
  local pid="$1"
  local command_line

  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    return 0
  fi
  command_line="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  if [[ "${command_line}" != *port-forward* ]]; then
    echo "Process ${pid} is not a kubectl port-forward. Leaving it running."
    return 0
  fi
  # The listener's parent is a session leader. Killing the group stops the restart loop too.
  kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      echo "Stopped the incident port-forward (${pid})."
      return 0
    fi
    sleep 0.2
  done
  kill -9 -- "-${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
  echo "Stopped the incident port-forward (${pid})."
}

if [[ -f "${PID_FILE}" ]]; then
  stop_port_forward "$(tr -d '[:space:]' < "${PID_FILE}")"
  rm -f "${PID_FILE}"
fi

if command -v lsof >/dev/null 2>&1; then
  while read -r pid; do
    stop_port_forward "${pid}"
  done < <(lsof -nP -iTCP:"${INCIDENT_PORT}" -sTCP:LISTEN -t 2>/dev/null || true)
fi

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  kind delete cluster --name "${CLUSTER_NAME}"
else
  echo "Kind cluster ${CLUSTER_NAME} is not running."
fi
