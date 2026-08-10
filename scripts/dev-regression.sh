#!/usr/bin/env bash
#
# Tier 1 dev-environment core regression smoke (reusable).
#
# Runs, against the dev environment (make up / remote docker host):
#   1. Claude happy path (execute, fresh session)
#   2. Claude resume (continue on same issue)
#   3. Codex happy path (execute, fresh session)
# and verifies each task's delivery (commit + MR), canonical archive invariants
# (event.jsonl seq/terminal/schema), real session_id, and log sanitization.
#
# Usage:
#   ./scripts/dev-regression.sh                          # auto: pick a project, create a fresh issue
#   ./scripts/dev-regression.sh --tier2                  # + failure paths (cancel/timeout/retry/switch-constraint)
#   PROJECT_ID=<n> ./scripts/dev-regression.sh           # create the smoke issue on a specific project
#   ISSUE_ID=<n> ./scripts/dev-regression.sh             # reuse an existing issue (skip auto-create)
#   CODIFY_BASE_URL=... CODIFY_USER=... CODIFY_PASS=... \
#     PROVIDER_CLAUDE_ID=.. PROVIDER_CODEX_ID=.. WORKER_PROFILE_ID=.. ./scripts/dev-regression.sh
#
# Config precedence: env vars > gitignored deploy/dev-env-info.md > defaults.
# Requires: curl, jq, python3. See docs/dev-env-core-regression.md (Tier 1/2).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_INFO="$ROOT/deploy/dev-env-info.md"   # gitignored; source of dev-env addresses/credentials

BASE_URL="${CODIFY_BASE_URL:-}"
USER="${CODIFY_USER:-admin}"
PASS="${CODIFY_PASS:-}"
[ -n "$BASE_URL" ] || BASE_URL="$(sed -nE 's/^\| Codify 前端 \| `([^`]*)`.*/\1/p' "$DEV_INFO" 2>/dev/null | head -1)"
[ -n "$BASE_URL" ] || BASE_URL="http://192.168.50.129:8880"
ISSUE_ID="${ISSUE_ID:-}"
PROJECT_ID="${PROJECT_ID:-}"
WORKER_PROFILE_ID="${WORKER_PROFILE_ID:-}"
DEFAULT_BRANCH=""            # project default branch; set as base+target so an MR is created
P_CLAUDE="${PROVIDER_CLAUDE_ID:-}"
P_CODEX="${PROVIDER_CODEX_ID:-}"
POLL_INTERVAL="${POLL_INTERVAL:-15}"     # seconds between task status polls
POLL_MAX="${POLL_MAX:-360}"              # max seconds to wait for a task terminal
PROMPT_CLAUDE="${PROMPT_CLAUDE:-Create a file hello.py with a hello_world() function and a comment.}"
PROMPT_CONTINUE="${PROMPT_CONTINUE:-Continue: add a goodbye() function to the existing file.}"
PROMPT_CODEX="${PROMPT_CODEX:-Create a file hello.rs with a main() that prints hello world.}"
PROMPT_SLOW="${PROMPT_SLOW:-Implement a small library module with a public API, write unit tests, run them, then refactor and re-run — be thorough.}"
TIER2=0
[ "${1:-}" = "--tier2" ] && TIER2=1

WORK="$(mktemp -d)"
COOKIE="$(mktemp)"
ORIG_TIMEOUT=""          # saved task_timeout override, restored via restore_timeout()
TIMEOUT_CHANGED=0        # set once task_timeout has been mutated; cleared only on verified restore
cleanup() {
  restore_timeout >/dev/null 2>&1 || true   # last-chance restore even if tier2's restore failed
  rm -f "$COOKIE"; rm -rf "$WORK"
}
trap cleanup EXIT

# Build a JSON body safely (jq escapes every interpolated value).
json_build() { jq -nc "$@"; }

# Restore task_timeout to its pre-test value; disarm the safety net only on a verified success.
restore_timeout() {
  local code
  if [ -n "$ORIG_TIMEOUT" ]; then
    api PATCH /api/config/runtime "$(json_build --argjson t "$ORIG_TIMEOUT" '{task_timeout:$t}')"
  else
    api DELETE /api/config/runtime/task_timeout
  fi
  code="$HTTP_CODE"
  if [ "$code" = "200" ]; then
    ORIG_TIMEOUT=""; TIMEOUT_CHANGED=0
    return 0
  fi
  return 1   # keep the safety net armed; the EXIT trap retries on exit
}

PASSED=0; FAILED=0; SKIPPED=0
declare -a FAILURES=()
BODY=""; HTTP_CODE=""
TASK_ID=""; SESSION_ID=""
STATUS_JSON=""

log()   { printf '  %s\n' "$*"; }
ok()    { PASSED=$((PASSED+1)); printf '  \033[32m✔\033[0m %s\n' "$*"; }
fail()  { FAILED=$((FAILED+1)); FAILURES+=("$*"); printf '  \033[31m✘\033[0m %s\n' "$*"; }
skip()  { SKIPPED=$((SKIPPED+1)); printf '  \033[33m-\033[0m %s\n' "$*"; }
die()   { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

api() { # api METHOD PATH [JSON-BODY]  -> sets BODY + HTTP_CODE
  local method="$1" path="$2" body="${3:-}" tmp
  tmp="$(mktemp)"
  if [ -n "$body" ]; then
    curl -s -b "$COOKIE" -c "$COOKIE" -X "$method" "$BASE_URL$path" \
      -H 'Content-Type: application/json' -d "$body" -w '\n%{http_code}' > "$tmp" || true
  else
    curl -s -b "$COOKIE" -c "$COOKIE" -X "$method" "$BASE_URL$path" \
      -H 'Content-Type: application/json' -w '\n%{http_code}' > "$tmp" || true
  fi
  BODY="$(sed '$d' "$tmp")"
  HTTP_CODE="$(tail -n1 "$tmp")"
  rm -f "$tmp"
}

login() {
  [ -n "$BASE_URL" ] || die "could not resolve CODIFY_BASE_URL (set it or create $DEV_INFO)"
  [ -n "$PASS" ] || PASS="$(sed -nE 's/^\| `admin` \| `([^`]*)`.*/\1/p' "$DEV_INFO" | head -1)"
  [ -n "$PASS" ] || die "CODIFY_PASS not set and not found in $DEV_INFO"
  api POST /api/auth/local/login "$(json_build --arg u "$USER" --arg p "$PASS" '{username:$u,password:$p}')"
  [ "$HTTP_CODE" = "200" ] || die "login failed (HTTP $HTTP_CODE): $BODY"
  ok "logged in as $USER @ $BASE_URL"
}

resolve_project_id() { # resolve_project_id -> prints a project id
  api GET /api/projects
  [ "$HTTP_CODE" = "200" ] || { echo "projects list failed (HTTP $HTTP_CODE): $BODY" >&2; return 1; }
  echo "$BODY" | jq -r '.[0].id // empty' | head -1
}

resolve_default_branch() { # resolve_default_branch <project_id> -> prints the project default branch
  api GET /api/projects
  [ "$HTTP_CODE" = "200" ] || { echo "projects list failed (HTTP $HTTP_CODE): $BODY" >&2; return 1; }
  echo "$BODY" | jq -r --argjson pid "$1" '.[] | select(.id==$pid) | .default_branch // empty' | head -1
}

resolve_worker_profile_id() { # resolve_worker_profile_id -> prints an enabled worker profile id
  api GET /api/worker-profiles
  [ "$HTTP_CODE" = "200" ] || { echo "worker-profiles list failed (HTTP $HTTP_CODE): $BODY" >&2; return 1; }
  echo "$BODY" | jq -r '.[] | select(.enabled==true) | .id' | head -1
}

create_issue() { # create_issue <project_id>  -> sets ISSUE_ID
  local pid="$1" title
  title="Tier 1 smoke $(date +%s)"
  # base+target set to the project default branch (mirrors CreateIssue.vue auto-set),
  # otherwise the worker runs in no-MR mode and no merge_request_url is produced.
  api POST /api/issues "$(json_build --argjson p "$pid" --argjson w "$WORKER_PROFILE_ID" --arg t "$title" \
    --arg b "$DEFAULT_BRANCH" \
    '{project_id:$p,worker_profile_id:$w,title:$t,description:"Automated Tier 1 regression smoke issue.",base_branch:$b,target_branch:$b}')"
  [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ] || die "create issue failed (HTTP $HTTP_CODE): $BODY"
  ISSUE_ID="$(echo "$BODY" | jq -r '.id')"
  [ -n "$ISSUE_ID" ] && [ "$ISSUE_ID" != "null" ] || die "no issue id in create response: $BODY"
  ok "auto-created issue #$ISSUE_ID (project $pid, target=$DEFAULT_BRANCH)"
}

preflight() {
  api GET /api/auth/bootstrap-status
  [ "$HTTP_CODE" = "200" ] || die "bootstrap-status failed (HTTP $HTTP_CODE) — is the dev env up?"
  ok "env up: $(echo "$BODY" | jq -r '.initialized // "?"' | head -c 40)"
  if [ -z "$ISSUE_ID" ]; then
    [ -n "$PROJECT_ID" ] || PROJECT_ID="$(resolve_project_id)"
    [ -n "$PROJECT_ID" ] || die "could not resolve PROJECT_ID — set PROJECT_ID or create $DEV_INFO"
    [ -n "$DEFAULT_BRANCH" ] || DEFAULT_BRANCH="$(resolve_default_branch "$PROJECT_ID")"
    [ -n "$DEFAULT_BRANCH" ] || die "could not resolve default branch for project $PROJECT_ID"
    ok "project $PROJECT_ID default branch $DEFAULT_BRANCH"
    [ -n "$WORKER_PROFILE_ID" ] || WORKER_PROFILE_ID="$(resolve_worker_profile_id)"
    [ -n "$WORKER_PROFILE_ID" ] || die "no enabled worker profile found — create one or set WORKER_PROFILE_ID"
    ok "worker profile $WORKER_PROFILE_ID"
    create_issue "$PROJECT_ID"
  else
    ok "issue #$ISSUE_ID"
  fi
  # Auto-detect providers by wire protocol unless explicitly given.
  if [ -z "$P_CLAUDE" ] || [ -z "$P_CODEX" ]; then
    api GET /api/providers
    [ "$HTTP_CODE" = "200" ] || die "providers list failed (HTTP $HTTP_CODE)"
    [ -z "$P_CLAUDE" ] && P_CLAUDE="$(echo "$BODY" | jq -r '.[] | select(.wire_protocol=="anthropic_messages") | .id' | head -1)"
    [ -z "$P_CODEX" ] && P_CODEX="$(echo "$BODY" | jq -r '.[] | select(.wire_protocol=="openai_responses") | .id' | head -1)"
  fi
  [ -n "$P_CLAUDE" ] || die "no anthropic_messages (Claude) provider found — set PROVIDER_CLAUDE_ID"
  [ -n "$P_CODEX" ] || die "no openai_responses (Codex) provider found — set PROVIDER_CODEX_ID"
  ok "providers: claude=$P_CLAUDE codex=$P_CODEX"
}

create_task() { # create_task <harness> <session_mode> <provider_id> <prompt>
  local harness="$1" mode="$2" provider="$3" prompt="$4"
  api POST /api/tasks "$(json_build --argjson i "$ISSUE_ID" --arg p "$prompt" --argjson pr "$provider" \
    --arg h "$harness" --arg m "$mode" \
    '{issue_id:$i,user_prompt:$p,priority:1,provider_id:$pr,harness_key:$h,task_mode:"execute",session_mode:$m,require_changes:true}')"
  [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ] || die "create $harness($mode) task failed (HTTP $HTTP_CODE): $BODY"
  TASK_ID="$(echo "$BODY" | jq -r '.id')"
  [ -n "$TASK_ID" ] && [ "$TASK_ID" != "null" ] || die "no task id in create response: $BODY"
  log "created $harness ($mode) task #$TASK_ID"
}

wait_terminal() { # wait_terminal <task_id>  -> sets STATUS_JSON
  local id="$1" elapsed=0 status
  while [ "$elapsed" -lt "$POLL_MAX" ]; do
    api GET "/api/tasks/$id"
    [ "$HTTP_CODE" = "200" ] || die "GET task $id failed (HTTP $HTTP_CODE)"
    status="$(echo "$BODY" | jq -r '.status')"
    case "$status" in
      completed|failed|cancelled) STATUS_JSON="$BODY"; return 0 ;;
    esac
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
    printf '    (task %s still %s, %ss elapsed)\n' "$id" "$status" "$elapsed"
  done
  die "task $id still running after ${POLL_MAX}s"
}

verify_task() { # verify_task <label>
  local label="$1" status sha err mr
  status="$(echo "$STATUS_JSON" | jq -r '.status')"
  sha="$(echo "$STATUS_JSON" | jq -r '.commit_sha // ""')"
  err="$(echo "$STATUS_JSON" | jq -r '.error_message // ""')"
  mr="$(echo "$STATUS_JSON" | jq -r '.issue.merge_request_url // ""')"
  [ "$status" = "completed" ] && ok "$label: status=completed" || fail "$label: status=$status (error: $err)"
  [ -n "$sha" ] && ok "$label: commit_sha=$sha" || fail "$label: no commit_sha"
  [ -n "$mr" ]  && ok "$label: MR $mr"          || fail "$label: no merge_request_url"
  case "$err" in *glpat-*|*sk-ant-*) fail "$label: token leaked in error_message";; esac
}

verify_archive() { # verify_archive <task_id> <label>  -> sets SESSION_ID
  local id="$1" label="$2" sid
  local d="$WORK/t$id"
  mkdir -p "$d"
  curl -s -b "$COOKIE" "$BASE_URL/api/tasks/$id/archive/download" -o "$d/archive.tar.gz" -w '%{http_code}' > "$d/archive.code"
  [ "$(cat "$d/archive.code")" = "200" ] || { fail "$label: archive download failed (HTTP $(cat "$d/archive.code"))"; return; }
  tar xzf "$d/archive.tar.gz" -C "$d" 2>/dev/null || { fail "$label: cannot extract archive"; return; }
  [ -f "$d/event.jsonl" ] || { fail "$label: archive missing event.jsonl"; return; }

  if python3 - "$d/event.jsonl" <<'PY'; then
import json, sys
lines = [l for l in open(sys.argv[1]) if l.strip()]
if not lines: sys.exit(1)
seqs = [json.loads(l)["seq"] for l in lines]
assert seqs == list(range(1, len(lines) + 1)), "seq not continuous"
types = [json.loads(l)["type"] for l in lines]
assert types.count("run.completed") + types.count("run.failed") == 1, "not single terminal"
assert types[-1] in ("run.completed", "run.failed"), "terminal not last"
assert "worker.finalization" in types, "missing finalization"
PY
    ok "$label: event.jsonl invariants"
  else
    fail "$label: event.jsonl invariants failed"
  fi

  [ -f "$d/harness-result.json" ] || { fail "$label: archive missing harness-result.json"; return; }
  sid="$(jq -r '.session_id // ""' "$d/harness-result.json")"
  case "$sid" in ""|"<UUID:"*) fail "$label: session_id not real ($sid)";; *) SESSION_ID="$sid"; ok "$label: real session_id $sid";; esac

  local hk av cv
  hk="$(jq -r '.harness_key // ""' "$d/harness-result.json")"
  av="$(jq -r '.adapter_version // ""' "$d/harness-result.json")"
  cv="$(jq -r '.cli_version // ""' "$d/harness-result.json")"
  if [ -n "$hk" ] && [ -n "$av" ] && [ -n "$cv" ]; then
    ok "$label: harness-result fields (harness=$hk adapter=$av cli=$cv)"
  else
    fail "$label: harness-result missing fields (harness_key='$hk' adapter_version='$av' cli_version='$cv')"
  fi

  if grep -qE 'glpat-[A-Za-z0-9]|sk-ant-[A-Za-z0-9]' "$d/event.jsonl" 2>/dev/null; then
    fail "$label: token leak in event.jsonl"
  else
    ok "$label: no token leak in event.jsonl"
  fi
}

run_scenario() { # run_scenario <harness> <label> <provider> <session_mode> <prompt>
  create_task "$1" "$4" "$3" "$5"
  wait_terminal "$TASK_ID"
  verify_task "$2"
  verify_archive "$TASK_ID" "$2"
}

tier2_switch_constraint() {
  log "== T2-1: harness switch constraint (continue with mismatched harness -> 422) =="
  # After Tier 1 the issue lineage is codex (codex fresh ran last); a claude continue must be rejected.
  api POST /api/tasks "$(json_build --argjson i "$ISSUE_ID" --arg p "$PROMPT_CONTINUE" --argjson pr "$P_CLAUDE" \
    '{issue_id:$i,user_prompt:$p,priority:1,provider_id:$pr,harness_key:"claude",task_mode:"execute",session_mode:"continue",require_changes:true}')"
  case "$HTTP_CODE" in
    422|400) ok "switch constraint: rejected mismatched-harness continue (HTTP $HTTP_CODE)";;
    *)       fail "switch constraint: expected 4xx, got HTTP $HTTP_CODE: $BODY";;
  esac
}

tier2_cancel() {
  log "== T2-2: cancel while RUNNING =="
  create_task claude fresh "$P_CLAUDE" "$PROMPT_SLOW"
  local id="$TASK_ID" elapsed=0 status
  while [ "$elapsed" -lt 180 ]; do
    api GET "/api/tasks/$id"
    status="$(echo "$BODY" | jq -r '.status')"
    case "$status" in
      running)
        api POST "/api/tasks/$id/cancel"
        [ "$HTTP_CODE" = "200" ] && ok "cancel: cancel request accepted" || fail "cancel: cancel request HTTP $HTTP_CODE: $BODY"
        wait_terminal "$id"
        local st
        st="$(echo "$STATUS_JSON" | jq -r '.status')"
        [ "$st" = "cancelled" ] && ok "cancel: status=cancelled" || fail "cancel: expected cancelled, got $st"
        local cdir="$WORK/cancel"; mkdir -p "$cdir"
        curl -s -b "$COOKIE" "$BASE_URL/api/tasks/$id/archive/download" -o "$cdir/a.tar.gz" -w '%{http_code}' > "$cdir/code"
        case "$(cat "$cdir/code")" in
          200) ok "cancel: archive preserved";;
          404) skip "cancel: no archive (task cancelled before worker archived it)";;
          *)   fail "cancel: archive download HTTP $(cat "$cdir/code")";;
        esac
        return
        ;;
      completed|failed)
        skip "cancel: task reached $status before cancel (too fast to test)"
        return
        ;;
      pending|queued) : ;;  # still waiting for a slot — keep polling
    esac
    sleep 5; elapsed=$((elapsed + 5))
  done
  fail "cancel: task never reached RUNNING in ${elapsed}s"
}

tier2_timeout_retry() {
  log "== T2-3: timeout (task_timeout=60) then retry (bundle freeze) =="
  api GET /api/config/runtime
  [ "$HTTP_CODE" = "200" ] || die "GET /config/runtime failed (HTTP $HTTP_CODE)"
  ORIG_TIMEOUT="$(echo "$BODY" | jq -r '.task_timeout // ""')"
  TIMEOUT_CHANGED=1
  api PATCH /api/config/runtime '{"task_timeout":60}'
  if [ "$HTTP_CODE" != "200" ]; then
    fail "timeout: PATCH task_timeout=60 failed (HTTP $HTTP_CODE): $BODY"
    restore_timeout || true
    return
  fi
  ok "timeout: set task_timeout=60"

  create_task codex fresh "$P_CODEX" "$PROMPT_SLOW"
  local id="$TASK_ID"
  wait_terminal "$id"
  local st err
  st="$(echo "$STATUS_JSON" | jq -r '.status')"
  err="$(echo "$STATUS_JSON" | jq -r '.error_message // ""')"
  if [ "$st" = "failed" ] && printf '%s' "$err" | grep -qi "timed out"; then
    ok "timeout: task failed with timeout"
  elif [ "$st" = "failed" ]; then
    fail "timeout: failed but not timeout (err: $err)"
  else
    fail "timeout: expected failed(timeout), got status=$st"
  fi

  # Restore timeout before retry so the retried task is not subject to the 60s cap.
  # On failure the EXIT trap retries; do not proceed to retry under a 60s cap.
  if restore_timeout; then
    ok "timeout: restored task_timeout"
  else
    fail "timeout: restore failed (HTTP $HTTP_CODE) — EXIT trap will retry; skipping retry"
    return
  fi

  local orig_digest rid rst rdigest
  orig_digest="$(echo "$STATUS_JSON" | jq -r '.harness_snapshot.runtime_bundle_digest // ""')"
  api POST "/api/tasks/$id/retry"
  [ "$HTTP_CODE" = "200" ] || { fail "retry: retry request failed (HTTP $HTTP_CODE): $BODY"; return; }
  rid="$(echo "$BODY" | jq -r '.id')"
  wait_terminal "$rid"
  rst="$(echo "$STATUS_JSON" | jq -r '.status')"
  [ "$rst" = "completed" ] && ok "retry: retried task completed" || fail "retry: retried task status=$rst"
  rdigest="$(echo "$STATUS_JSON" | jq -r '.harness_snapshot.runtime_bundle_digest // ""')"
  if [ -n "$orig_digest" ] && [ "$orig_digest" = "$rdigest" ]; then
    ok "retry: bundle digest frozen ($orig_digest)"
  else
    fail "retry: bundle digest mismatch (orig=$orig_digest retry=$rdigest)"
  fi
}

main() {
  login
  preflight

  log "== Claude happy path (execute, fresh) =="
  run_scenario claude "claude" "$P_CLAUDE" fresh "$PROMPT_CLAUDE"
  FRESH_SESSION="$SESSION_ID"

  log "== Claude resume (continue, same issue) =="
  run_scenario claude "claude-continue" "$P_CLAUDE" continue "$PROMPT_CONTINUE"
  if [ -f "$WORK/t$TASK_ID/event.jsonl" ]; then
    if [ -n "${FRESH_SESSION:-}" ] && grep -Fq "$FRESH_SESSION" "$WORK/t$TASK_ID/event.jsonl"; then
      ok "claude-continue: reused fresh session $FRESH_SESSION"
    elif grep -q '"input_session"' "$WORK/t$TASK_ID/event.jsonl"; then
      ok "claude-continue: input_session present in event.jsonl"
    else
      fail "claude-continue: no session resume evidence in event.jsonl"
    fi
  else
    skip "claude-continue: no event.jsonl in archive (skip resume evidence)"
  fi

  log "== Codex happy path (execute, fresh) =="
  run_scenario codex "codex" "$P_CODEX" fresh "$PROMPT_CODEX"

  if [ "$TIER2" = "1" ]; then
    tier2_switch_constraint
    tier2_cancel
    tier2_timeout_retry
  fi

  local label="Tier 1 smoke"; [ "$TIER2" = "1" ] && label="Tier 1+2 smoke"
  printf '\n\033[1m=== %s summary ===\033[0m  %s passed, %s failed, %s skipped\n' "$label" "$PASSED" "$FAILED" "$SKIPPED"
  if [ "${#FAILURES[@]}" -gt 0 ]; then
    printf '  failed:\n'
    for f in "${FAILURES[@]}"; do printf '    - %s\n' "$f"; done
    exit 1
  fi
  printf '  \033[32mALL %s CHECKS PASSED\033[0m\n' "$label"
}

main "$@"
