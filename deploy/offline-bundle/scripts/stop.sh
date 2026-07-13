#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/config/.env.offline"

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "Docker Compose is required." >&2
  exit 1
fi

cd "${ROOT_DIR}"
if [[ -f "${ENV_FILE}" ]]; then
  "${COMPOSE_CMD[@]}" --env-file "${ENV_FILE}" -f docker-compose.yml down
else
  "${COMPOSE_CMD[@]}" -f docker-compose.yml down
fi
