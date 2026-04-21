#!/usr/bin/env bash
# Run mock integration tests in a single Docker Compose stack.
#
# Usage:
#   run-mock-stack.sh [options] [test_files...]
#
# Options:
#   -p PROJECT    Compose project name       (default: mock_integration)
#   -n NETWORK    Docker network name         (default: codify-mock-test)
#   -w PREFIX     Worker container prefix      (default: codify)
#   -P PORT_MOCK  Host port for mock-services  (default: 19000)
#   -B PORT_BACK  Host port for backend        (default: 18000)
#   -l LABEL      Label for log output         (default: "")
#   -c FILE       Compose file path            (required)
#   -s DIR        Source root for test files    (required)
#   -d            Teardown stack on exit
#
# If no test_files are given, runs all tests in tests/mock_integration/.

set -euo pipefail

# Defaults
PROJECT="mock_integration"
NETWORK="codify-mock-test"
PREFIX="codify"
PORT_MOCK="19000"
PORT_BACK="18000"
LABEL=""
COMPOSE_FILE=""
SOURCE_ROOT=""
TEARDOWN=false

while getopts "p:n:w:P:B:l:c:s:d" opt; do
  case $opt in
    p) PROJECT="$OPTARG" ;;
    n) NETWORK="$OPTARG" ;;
    w) PREFIX="$OPTARG" ;;
    P) PORT_MOCK="$OPTARG" ;;
    B) PORT_BACK="$OPTARG" ;;
    l) LABEL="$OPTARG" ;;
    c) COMPOSE_FILE="$OPTARG" ;;
    s) SOURCE_ROOT="$OPTARG" ;;
    d) TEARDOWN=true ;;
    *) echo "Unknown option: -$opt" >&2; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

# Remaining args are test files (relative to tests/mock_integration/)
TEST_FILES=("$@")

if [[ -z "$COMPOSE_FILE" || -z "$SOURCE_ROOT" ]]; then
  echo "Error: -c COMPOSE_FILE and -s SOURCE_ROOT are required" >&2
  exit 1
fi

CONTAINER="${PROJECT}-backend-1"

compose() {
  COMPOSE_PROJECT_NAME="$PROJECT" \
  MOCK_NETWORK="$NETWORK" \
  WORKER_PREFIX="$PREFIX" \
  MOCK_PORT_MOCK="$PORT_MOCK" \
  MOCK_PORT_BACKEND="$PORT_BACK" \
    docker-compose -f "$COMPOSE_FILE" "$@"
}

teardown() {
  if $TEARDOWN; then
    compose down -v 2>/dev/null || true
  fi
}
trap teardown EXIT

# --- Start stack ---
if [[ -n "$LABEL" ]]; then
  printf "\n\033[1;36m━━━ Mock Stack %s: starting ━━━\033[0m\n" "$LABEL"
fi

compose up -d --wait postgres mock-services backend scheduler

# Test deps are pre-installed in codify-backend-test image.
# Sync latest test files from host (needed for remote Docker contexts).
docker cp "$SOURCE_ROOT/backend/tests" "$CONTAINER:/tmp/tests"
docker exec "$CONTAINER" bash -c \
  "mkdir -p /app/tests && cp /tmp/tests/__init__.py /app/tests/ 2>/dev/null; \
   rm -rf /app/tests/mock_integration && cp -r /tmp/tests/mock_integration /app/tests/mock_integration"

# --- Build pytest args ---
if [[ ${#TEST_FILES[@]} -gt 0 ]]; then
  PYTEST_ARGS=()
  for f in "${TEST_FILES[@]}"; do
    PYTEST_ARGS+=("tests/mock_integration/$f")
  done
else
  PYTEST_ARGS=("tests/mock_integration/")
fi

# --- Run tests ---
docker exec \
  -e MOCK_TEST_BACKEND_URL=http://localhost:8000 \
  -e MOCK_TEST_MOCK_URL=http://mock-services:9000 \
  -e DOCKER_HOST_IP=mock-services \
  "$CONTAINER" \
  python -m pytest "${PYTEST_ARGS[@]}" -v --tb=short -k "not TestCrashRecovery"
