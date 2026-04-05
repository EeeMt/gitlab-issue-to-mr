#!/usr/bin/env bash
# Runs all test suites and prints an aggregated summary at the end.
# Usage: scripts/run-tests.sh [--all]   (--all includes gitlab-e2e + playwright e2e)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"
ALL_SUITES=false

for arg in "$@"; do
  [[ "$arg" == "--all" ]] && ALL_SUITES=true
done

# ── colours ────────────────────────────────────────────────────────────────────
GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"; BOLD="\033[1m"; RESET="\033[0m"
CHECK="✅"; CROSS="❌"; SKIP_SYM="⏭ "

# ── helpers ────────────────────────────────────────────────────────────────────
declare -a SUITE_NAMES=()
declare -a SUITE_SUMMARIES=()
declare -a SUITE_STATUSES=()   # ok | fail | skip

add_result() {
  local name="$1" summary="$2" status="$3"
  SUITE_NAMES+=("$name")
  SUITE_SUMMARIES+=("$summary")
  SUITE_STATUSES+=("$status")
}

run_suite() {
  local name="$1"; shift
  echo ""
  echo -e "${BOLD}━━━ $name ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  local tmpout; tmpout=$(mktemp)
  local status="ok"
  # run, tee to terminal, capture to file; tolerate failures
  set +e
  bash -c "$*" 2>&1 | tee "$tmpout"
  local rc=${PIPESTATUS[0]}
  set -e
  # extract last non-empty line as summary
  local summary
  # try pytest format first: "N passed, N failed ..."
  summary=$(grep -E "^[0-9]+ (passed|failed|error)" "$tmpout" | tail -1 || true)
  # fallback: vitest format "Tests  N passed (N)"
  if [[ -z "$summary" ]]; then
    summary=$(grep -E "^\s+Tests\s+[0-9]+" "$tmpout" | tail -1 | sed 's/^ *//' || true)
  fi
  [[ -z "$summary" ]] && summary=$(tail -1 "$tmpout" | sed 's/\x1b\[[0-9;]*m//g')
  [[ $rc -ne 0 ]] && status="fail"
  rm -f "$tmpout"
  add_result "$name" "$summary" "$status"
}

run_suite_skip() {
  local name="$1" reason="$2"
  add_result "$name" "skipped — $reason" "skip"
}

# ── extract only GitLab credentials from .env.test (not DATABASE_URL etc.) ─────
ENV_TEST="$PROJECT_ROOT/deploy/.env.test"
GITLAB_URL_FROM_ENV=""
GITLAB_BOT_TOKEN_FROM_ENV=""
GITLAB_WEBHOOK_SECRET_FROM_ENV=""
if [[ -f "$ENV_TEST" ]]; then
  GITLAB_URL_FROM_ENV=$(grep -E "^GITLAB_URL=" "$ENV_TEST" | cut -d= -f2- || true)
  GITLAB_BOT_TOKEN_FROM_ENV=$(grep -E "^GITLAB_BOT_TOKEN=" "$ENV_TEST" | cut -d= -f2- || true)
  GITLAB_WEBHOOK_SECRET_FROM_ENV=$(grep -E "^GITLAB_WEBHOOK_SECRET=" "$ENV_TEST" | cut -d= -f2- || true)
fi

# ── run suites ─────────────────────────────────────────────────────────────────
run_suite "Backend unit" \
  "cd '$PROJECT_ROOT/backend' && '$VENV_PYTHON' -m pytest tests/unit/ -q --tb=short"

run_suite "Frontend unit" \
  "cd '$PROJECT_ROOT/frontend' && npx vitest run --reporter=verbose 2>&1 | tail -20"

run_suite "Mock E2E" \
  "cd '$PROJECT_ROOT/backend' && '$VENV_PYTHON' -m pytest tests/mock_e2e/ -q --tb=short"

if $ALL_SUITES; then
  # Export GitLab creds so docker-compose can pass them into the e2e container
  export GITLAB_URL="$GITLAB_URL_FROM_ENV"
  export GITLAB_BOT_TOKEN="$GITLAB_BOT_TOKEN_FROM_ENV"
  export GITLAB_WEBHOOK_SECRET="$GITLAB_WEBHOOK_SECRET_FROM_ENV"

  # Start the shared E2E environment (backend + postgres + nginx + scheduler in Docker network)
  echo ""
  echo -e "${BOLD}━━━ Starting E2E environment ━━━━━━━━━━━━━━━━━━━━━${RESET}"
  (cd "$PROJECT_ROOT/deploy" && docker-compose -f docker-compose.e2e.yml up -d --build --wait postgres backend nginx scheduler)

  _E2E_RUN="cd '$PROJECT_ROOT/deploy' && docker-compose -f docker-compose.e2e.yml run --rm e2e"

  run_suite "GitLab E2E" \
    "$_E2E_RUN pytest tests/gitlab_e2e/ -q --tb=short"

  echo ""
  echo -e "${BOLD}━━━ Playwright E2E ━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  tmpout=$(mktemp)
  set +e
  (
    cd "$PROJECT_ROOT/deploy"
    docker-compose -f docker-compose.e2e.yml run --rm e2e \
      pytest tests/e2e/tests/ -m "not serial" -q --tb=short 2>&1
    docker-compose -f docker-compose.e2e.yml run --rm e2e \
      pytest tests/e2e/tests/ -m serial -q --tb=short \
      --override-ini="addopts=-q --tb=short --strict-markers --disable-warnings" 2>&1
  ) | tee "$tmpout"
  e2e_rc=${PIPESTATUS[0]}
  set -e
  e2e_summary=$(grep -E "^[0-9]+ (passed|failed)" "$tmpout" | tail -1 || echo "(see output above)")
  e2e_status="ok"; [[ $e2e_rc -ne 0 ]] && e2e_status="fail"
  rm -f "$tmpout"
  add_result "Playwright E2E" "$e2e_summary" "$e2e_status"

  echo ""
  echo -e "${BOLD}━━━ Stopping E2E environment ━━━━━━━━━━━━━━━━━━━━━${RESET}"
  (cd "$PROJECT_ROOT/deploy" && docker-compose -f docker-compose.e2e.yml down)
fi

# ── print summary ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}                 Test Suite Summary                ${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"

overall_ok=true
for i in "${!SUITE_NAMES[@]}"; do
  name="${SUITE_NAMES[$i]}"
  summary="${SUITE_SUMMARIES[$i]}"
  status="${SUITE_STATUSES[$i]}"
  case "$status" in
    ok)   icon="$CHECK"; color="$GREEN" ;;
    fail) icon="$CROSS"; color="$RED"; overall_ok=false ;;
    skip) icon="$SKIP_SYM"; color="$YELLOW" ;;
  esac
  printf "  ${color}%-18s${RESET}  %s  %s\n" "$name" "$icon" "$summary"
done

echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"
if $overall_ok; then
  echo -e "  ${GREEN}${BOLD}ALL SUITES PASSED${RESET}"
else
  echo -e "  ${RED}${BOLD}SOME SUITES FAILED — see output above${RESET}"
fi
echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"
echo ""

$overall_ok || exit 1
