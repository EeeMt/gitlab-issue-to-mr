#!/usr/bin/env bash
# Round-trip migration 063 only against an explicitly isolated local test database.
set -euo pipefail

TEST_DATABASE_URL="${CODIFY_MIGRATION_TEST_DATABASE_URL:-}"
if [[ -z "${TEST_DATABASE_URL}" ]]; then
    echo "CODIFY_MIGRATION_TEST_DATABASE_URL is required" >&2
    exit 2
fi
if [[ ! "${TEST_DATABASE_URL}" =~ ^postgresql\+asyncpg://[^/@]+(:[^/@]*)?@(127\.0\.0\.1|localhost):[0-9]+/[^?]*(test|_test)(\?.*)?$ ]]; then
    echo "Migration test URL must target an explicit localhost database ending in test/_test" >&2
    exit 2
fi
if [[ -n "${DATABASE_URL:-}" && "${DATABASE_URL}" != "${TEST_DATABASE_URL}" ]]; then
    echo "Refusing to override a different DATABASE_URL" >&2
    exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}/backend"
export DATABASE_URL="${TEST_DATABASE_URL}"
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade 062_task_skills
.venv/bin/alembic upgrade head
.venv/bin/alembic current
