#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/config/.env.offline"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy config/.env.offline.example first." >&2
  exit 1
fi

BACKEND_URL="$(grep '^BACKEND_URL=' "${ENV_FILE}" | head -1 | cut -d= -f2-)"
FRONTEND_URL="$(grep '^FRONTEND_URL=' "${ENV_FILE}" | head -1 | cut -d= -f2-)"

if [[ -z "${BACKEND_URL}" || -z "${FRONTEND_URL}" ]]; then
  echo "BACKEND_URL / FRONTEND_URL must be set in ${ENV_FILE}" >&2
  exit 1
fi

echo "Backend:  $(curl -s -o /dev/null -w '%{http_code}' "${BACKEND_URL}/health")"
echo "Frontend: $(curl -s -o /dev/null -w '%{http_code}' "${FRONTEND_URL}/")"
