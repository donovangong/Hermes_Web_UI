#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="hermes-ui"
PORT="${HERMES_UI_PORT:-8765}"

echo "Service status:"
if command -v systemctl >/dev/null 2>&1; then
  systemctl status "${SERVICE_NAME}" --no-pager || true
  echo
  echo "Enabled: $(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || true)"
  echo "Active:  $(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"
else
  echo "systemctl not found"
fi

echo
echo "Port ${PORT} listener:"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp | grep ":${PORT}" || echo "No listener found on ${PORT}"
else
  echo "ss not found"
fi

echo
echo "Health check:"
if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:${PORT}/api/health" || echo "Health check failed"
  echo
else
  echo "curl not found"
fi

echo
echo "VM IP candidates:"
VM_IPS="$(hostname -I 2>/dev/null | xargs || true)"
if [[ -n "${VM_IPS}" ]]; then
  echo "${VM_IPS}"
  echo
  echo "Try from host browser:"
  for ip in ${VM_IPS}; do
    echo "  http://${ip}:${PORT}"
  done
else
  echo "No IP detected"
fi
