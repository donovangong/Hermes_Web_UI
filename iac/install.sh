#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="hermes-ui"
PROJECT_DIR="/root/hermes_UI"
IAC_DIR="${PROJECT_DIR}/iac"
SERVICE_SRC="${IAC_DIR}/${SERVICE_NAME}.service"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}.service"
PORT="${HERMES_UI_PORT:-8765}"
HOST="${HERMES_UI_HOST:-0.0.0.0}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: please run as root: sudo ${IAC_DIR}/install.sh" >&2
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/app.py" ]]; then
  echo "ERROR: missing ${PROJECT_DIR}/app.py" >&2
  exit 1
fi

if [[ ! -f "${SERVICE_SRC}" ]]; then
  echo "ERROR: missing ${SERVICE_SRC}" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is not installed or not in PATH" >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "ERROR: systemctl is not available on this VM" >&2
  exit 1
fi

python3 -m py_compile "${PROJECT_DIR}/app.py"

# Stop any ad-hoc process that may already occupy the port.
if command -v ss >/dev/null 2>&1; then
  mapfile -t PIDS < <(ss -ltnp "sport = :${PORT}" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)
  for pid in "${PIDS[@]:-}"; do
    if [[ -n "${pid}" ]] && ps -p "${pid}" -o args= | grep -q "${PROJECT_DIR}/app.py\|python app.py"; then
      echo "Stopping existing Hermes UI process on port ${PORT}: pid ${pid}"
      kill "${pid}" || true
    fi
  done
fi

install -m 0644 "${SERVICE_SRC}" "${SERVICE_DEST}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

sleep 1

if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
  echo "ERROR: ${SERVICE_NAME} failed to start" >&2
  systemctl status "${SERVICE_NAME}" --no-pager || true
  journalctl -u "${SERVICE_NAME}" -n 80 --no-pager || true
  exit 1
fi

echo "Service is active: ${SERVICE_NAME}"

if command -v ss >/dev/null 2>&1; then
  echo "Port check:"
  ss -ltnp | grep ":${PORT}" || true
fi

if command -v curl >/dev/null 2>&1; then
  echo "Health check:"
  curl -fsS "http://127.0.0.1:${PORT}/api/health" || {
    echo "ERROR: local health check failed" >&2
    exit 1
  }
  echo
fi

VM_IPS="$(hostname -I 2>/dev/null | xargs || true)"
echo
echo "Hermes Web UI installed."
echo "Local URL: http://127.0.0.1:${PORT}"
if [[ -n "${VM_IPS}" ]]; then
  echo "VM IP candidates: ${VM_IPS}"
  for ip in ${VM_IPS}; do
    echo "Host browser URL: http://${ip}:${PORT}"
  done
else
  echo "Could not detect VM IP. Run: hostname -I"
fi

echo
echo "Useful commands:"
echo "  systemctl status ${SERVICE_NAME} --no-pager"
echo "  journalctl -u ${SERVICE_NAME} -f"
echo "  systemctl restart ${SERVICE_NAME}"
