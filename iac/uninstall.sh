#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="hermes-ui"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: please run as root: sudo ./uninstall.sh" >&2
  exit 1
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
  systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
fi

rm -f "${SERVICE_DEST}"

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl reset-failed "${SERVICE_NAME}" 2>/dev/null || true
fi

echo "Removed ${SERVICE_NAME} systemd service. Project files were not deleted."
