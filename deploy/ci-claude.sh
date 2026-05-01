#!/usr/bin/env bash
# ci-claude.sh — Claude Code headless runner for CI/CD
#
# Output contract:
#   stdout  →  Final JSON result (machine-readable, always emitted on completion)
#   stderr  →  Real-time streaming log (human-readable, with colors)
#   exit 0  →  Task succeeded    exit 1  →  Task failed
#
# Usage:
#   result=$(SANDBOX_MODE=1 ./ci-claude.sh "Fix auth.py")
#   echo "$result" | jq .result    # extract the text answer
#   result=$(PROMPT_FILE=/tmp/prompt.txt SANDBOX_MODE=1 ./ci-claude.sh)
#
# Environment variables:
#   SANDBOX_MODE           "1" → --dangerously-skip-permissions (sandbox containers only!)
#   ALLOWED_TOOLS          Comma-separated tool list, e.g. "Bash,Read,Edit,Write"
#                          Ignored when SANDBOX_MODE=1. Default: "Bash,Read,Edit,Write"
#   PROMPT_FILE            Read prompt from a file instead of argv (safer for large prompts)
#   APPEND_SYSTEM_PROMPT   Extra system instructions appended to default prompt
#   RESUME_SESSION         Session ID to resume a specific conversation
#   CONTINUE_SESSION       "1" → --continue the most recent conversation
#   CLAUDE_MAX_TURNS       Max agent turns (default: unlimited)
#   CLAUDE_MODEL           Model to use (e.g. claude-sonnet-4-20250514)
#   NO_COLOR               "1" → disable ANSI colors in stderr output

set -euo pipefail

# ── Artifact files (written to cwd so callers can locate them) ────────────────
ARTIFACT_DIR="${PWD}"
EVENT_JSONL="${ARTIFACT_DIR}/event.jsonl"
RUNTIME_JSON="${ARTIFACT_DIR}/runtime.json"
CONSOLE_LOG="${ARTIFACT_DIR}/console.log"
touch "$EVENT_JSONL" "$CONSOLE_LOG"
# Tee all stderr to console.log; >&2 inside the substitution refers to the
# original stderr (before exec redirects fd 2), so output still appears on
# the caller's terminal/log stream.
exec 2> >(tee -a "$CONSOLE_LOG" >&2)

# ── Colors on stderr ──────────────────────────────────────────────────────────
if [[ -t 2 && "${NO_COLOR:-}" != "1" ]]; then
  RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m'
  BLUE='\033[0;34m' CYAN='\033[0;36m'
  DIM='\033[2m' RESET='\033[0m' BOLD='\033[1m'
else
  RED='' GREEN='' YELLOW='' BLUE='' CYAN='' DIM='' RESET='' BOLD=''
fi

# All visual helpers write to stderr
_e()   { printf "$@" >&2; }
log()  { _e "${DIM}[ci-claude] %s${RESET}\n" "$*"; }
info() { _e "${BLUE}ℹ  %s${RESET}\n" "$*"; }
ok()   { _e "${GREEN}✅ %s${RESET}\n" "$*"; }
fail() { _e "${RED}❌ %s${RESET}\n" "$*"; }

# ── Args ──────────────────────────────────────────────────────────────────────
PROMPT_FILE="${PROMPT_FILE:-}"
PROMPT=""
if [[ -n "$PROMPT_FILE" ]]; then
  if [[ ! -f "$PROMPT_FILE" ]]; then
    printf "PROMPT_FILE not found: %s\n" "$PROMPT_FILE" >&2
    exit 1
  fi
  PROMPT=$(cat "$PROMPT_FILE")
elif [[ $# -gt 0 ]]; then
  PROMPT="$1"
elif [[ ! -t 0 ]]; then
  PROMPT=$(cat)
fi
if [[ -z "$PROMPT" ]]; then
  printf "Usage: %s <prompt>\n\n" "$0" >&2
  printf "  SANDBOX_MODE=1 %s 'Run tests and fix failures'\n" "$0" >&2
  printf "  ALLOWED_TOOLS=Bash,Read %s 'Explain the auth module'\n" "$0" >&2
  printf "  PROMPT_FILE=/tmp/prompt.txt SANDBOX_MODE=1 %s\n" "$0" >&2
  printf "  cat /tmp/prompt.txt | SANDBOX_MODE=1 %s\n" "$0" >&2
  exit 1
fi

SANDBOX_MODE="${SANDBOX_MODE:-0}"
ALLOWED_TOOLS="${ALLOWED_TOOLS:-Bash,Read,Edit,Write}"
APPEND_SYSTEM="${APPEND_SYSTEM_PROMPT:-}"
CONTINUE_SESSION="${CONTINUE_SESSION:-0}"
MAX_TURNS="${CLAUDE_MAX_TURNS:-}"
CLAUDE_MODEL="${CLAUDE_MODEL:-}"
SESSION_ID_FILE=".claude_session_id"

RESUME="${RESUME_SESSION:-}"
if [[ -z "$RESUME" && -f "$SESSION_ID_FILE" && "$CONTINUE_SESSION" != "1" ]]; then
  RESUME=$(cat "$SESSION_ID_FILE" 2>/dev/null || true)
fi

# ── Build claude args ─────────────────────────────────────────────────────────
CLAUDE_ARGS=(
  -p
  --output-format stream-json
  --verbose
  --include-partial-messages
)

if [[ "$SANDBOX_MODE" == "1" ]]; then
  CLAUDE_ARGS+=(--dangerously-skip-permissions)
else
  CLAUDE_ARGS+=(--allowedTools "$ALLOWED_TOOLS")
fi

[[ -n "$APPEND_SYSTEM" ]]            && CLAUDE_ARGS+=(--append-system-prompt "$APPEND_SYSTEM")
[[ -n "$MAX_TURNS" ]]                && CLAUDE_ARGS+=(--max-turns "$MAX_TURNS")
[[ -n "$CLAUDE_MODEL" ]]             && CLAUDE_ARGS+=(--model "$CLAUDE_MODEL")
[[ "$CONTINUE_SESSION" == "1" ]]     && CLAUDE_ARGS+=(--continue)
[[ -n "$RESUME" && "$CONTINUE_SESSION" != "1" ]] && CLAUDE_ARGS+=(--resume "$RESUME")

# ── Header ────────────────────────────────────────────────────────────────────
_e "${BLUE}${BOLD}╔═══════════════════════════════════════╗${RESET}\n"
_e "${BLUE}${BOLD}║       🤖  Claude Code CI Runner       ║${RESET}\n"
_e "${BLUE}${BOLD}╚═══════════════════════════════════════╝${RESET}\n"
PROMPT_PREVIEW="$PROMPT"
if [[ ${#PROMPT_PREVIEW} -gt 400 ]]; then
  PROMPT_PREVIEW="${PROMPT_PREVIEW:0:400}…(truncated, ${#PROMPT} chars)"
fi
info "Prompt : $PROMPT_PREVIEW"
if [[ "$SANDBOX_MODE" == "1" ]]; then
  info "Tools  : ALL (sandbox — dangerously-skip-permissions)"
else
  info "Tools  : $ALLOWED_TOOLS"
fi
[[ -n "$CLAUDE_MODEL" ]]             && info "Model  : $CLAUDE_MODEL"
[[ -n "$MAX_TURNS" ]]                && info "MaxTurns: $MAX_TURNS"
[[ -n "$RESUME" ]]               && info "Session: resuming $RESUME"
[[ "$CONTINUE_SESSION" == "1" ]] && info "Session: continuing last conversation"

# Print full CLI args (prompt is piped via stdin/file, not argv)
_e "${DIM}[ci-claude] CLI args:"
for arg in "${CLAUDE_ARGS[@]}"; do
  _e " %s" "$arg"
done
_e "${RESET}\n\n"

# ── Temp files for accumulating structured data ───────────────────────────────
# Needed because process_stream runs in a pipe subshell and can't set outer vars.

# Write initial runtime.json; model field is updated when system init event arrives.
jq -n \
  --arg model "${CLAUDE_MODEL:-}" \
  --arg cwd "${PWD}" \
  --arg resume "${RESUME:-}" \
  '{model: $model, cwd: $cwd, resume_session: $resume}' > "$RUNTIME_JSON"

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

TOOL_CALLS_FILE="$WORK_DIR/tool_calls.jsonl"   # one JSON object per line
RESULT_FILE="$WORK_DIR/result.json"
touch "$TOOL_CALLS_FILE" "$RESULT_FILE"

# ── Stream processor ──────────────────────────────────────────────────────────
process_stream() {
  local prev_block=""
  local cur_tool_name=""
  local cur_tool_id=""
  local cur_tool_input=""
  local cur_thinking_buf=""
  local cur_text_buf=""

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue

    # Mirror every raw stream-json line verbatim to event.jsonl
    printf '%s\n' "$line" >> "$EVENT_JSONL"

    local type
    type=$(printf '%s' "$line" | jq -r '.type // empty' 2>/dev/null) || {
      # Non-JSON line (e.g. plain-text error from CLI) — pass through to stderr
      _e "%s\n" "$line"
      continue
    }
    if [[ -z "$type" ]]; then
      # JSON but no .type field — pass through to stderr
      _e "%s\n" "$line"
      continue
    fi

    case "$type" in

      # ── Streaming events from the Anthropic API ─────────────────────────────
      stream_event)
        local event_type
        event_type=$(printf '%s' "$line" | jq -r '.event.type // empty' 2>/dev/null) || continue

        case "$event_type" in

          content_block_start)
            local block_type
            block_type=$(printf '%s' "$line" | jq -r '.event.content_block.type // empty' 2>/dev/null)
            prev_block="$block_type"
            case "$block_type" in
              thinking)
                cur_thinking_buf=""
                _e "\n${DIM}${CYAN}╔═ 🧠 Thinking ════════════════════════════════${RESET}\n"
                ;;
              tool_use)
                cur_tool_name=$(printf '%s' "$line" | jq -r '.event.content_block.name // empty' 2>/dev/null)
                cur_tool_id=$(printf '%s' "$line" | jq -r '.event.content_block.id // empty' 2>/dev/null)
                cur_tool_input=""
                _e "\n${YELLOW}┌─ ⚡ Tool: ${BOLD}${cur_tool_name}${RESET}\n"
                _e "${YELLOW}│  Input: ${DIM}"
                ;;
              text)
                cur_text_buf=""
                _e "\n${GREEN}${BOLD}── Response ───────────────────────────────────${RESET}\n"
                ;;
            esac
            ;;

          content_block_delta)
            local delta_type
            delta_type=$(printf '%s' "$line" | jq -r '.event.delta.type // empty' 2>/dev/null)
            case "$delta_type" in
              text_delta)
                local text
                text=$(printf '%s' "$line" | jq -rj '.event.delta.text // empty' 2>/dev/null)
                cur_text_buf+="$text"
                _e '%s' "$text"
                ;;
              thinking_delta)
                local thinking
                thinking=$(printf '%s' "$line" | jq -rj '.event.delta.thinking // empty' 2>/dev/null)
                cur_thinking_buf+="$thinking"
                _e "${DIM}%s${RESET}" "$thinking"
                ;;
              input_json_delta)
                local partial
                partial=$(printf '%s' "$line" | jq -rj '.event.delta.partial_json // empty' 2>/dev/null)
                cur_tool_input+="$partial"
                _e "${DIM}%s${RESET}" "$partial"
                ;;
            esac
            ;;

          content_block_stop)
            case "$prev_block" in
              thinking)
                _e "\n${DIM}${CYAN}╚══════════════════════════════════════════════${RESET}\n"
                cur_thinking_buf=""
                ;;
              tool_use)
                _e "${RESET}\n${YELLOW}└──────────────────────────────────────────────${RESET}\n"
                # Persist tool call stub for the final batch JSON (entrypoint.sh reads this)
                local safe_input
                safe_input=$(printf '%s' "${cur_tool_input:-{\}}" | jq -c '.' 2>/dev/null || echo '{}')
                jq -nc \
                  --arg id "$cur_tool_id" \
                  --arg name "$cur_tool_name" \
                  --argjson input "$safe_input" \
                  '{id: $id, name: $name, input: $input, output: null, error: false}' \
                  >> "$TOOL_CALLS_FILE"
                cur_tool_input=""
                cur_tool_id=""
                ;;
              text)
                _e "\n"
                cur_text_buf=""
                ;;
            esac
            prev_block=""
            ;;
        esac
        ;;

      # ── Tool execution results (delivered in top-level user messages)
      # stream-json emits these as {"type":"user","message":{"content":[...]}}.
      user)
        local count
        count=$(printf '%s' "$line" | jq '[.message.content[]? | select(.type == "tool_result")] | length' 2>/dev/null || echo 0)
        local i
        for (( i=0; i<count; i++ )); do
          local tool_use_id output is_error stored_out
          # Use filtered-array indexing to avoid off-by-one if content has mixed types
          tool_use_id=$(printf '%s' "$line" | jq -r --argjson i "$i" \
            '[.message.content[]? | select(.type == "tool_result")][$i].tool_use_id // ""' 2>/dev/null)
          output=$(printf '%s' "$line" | jq -r --argjson i "$i" \
            '[.message.content[]? | select(.type == "tool_result")][$i] |
            if (.content | type) == "array" then (.content | map(.text // "") | join(""))
            elif (.content | type) == "string" then .content
            else (.output // "") end' 2>/dev/null)
          is_error=$(printf '%s' "$line" | jq -r --argjson i "$i" \
            '[.message.content[]? | select(.type == "tool_result")][$i].is_error // false' 2>/dev/null)

          if [[ "$is_error" == "true" ]]; then
            _e "${RED}  ╰─ ❌ Error:  ${DIM}%.400s${RESET}\n" "$output"
          else
            _e "${CYAN}  ╰─ ✅ Output: ${DIM}%.400s${RESET}\n" "$output"
          fi

          # Update TOOL_CALLS_FILE stub (for backward-compat batch in entrypoint.sh)
          stored_out="${output:0:2000}"
          [[ ${#output} -gt 2000 ]] && stored_out+="…(truncated)"
          if [[ -n "$tool_use_id" && -s "$TOOL_CALLS_FILE" ]]; then
            jq -c \
              --arg id "$tool_use_id" \
              --arg out "$stored_out" \
              --argjson err "$is_error" \
              'if .id == $id then .output = $out | .error = $err else . end' \
              "$TOOL_CALLS_FILE" > "$TOOL_CALLS_FILE.tmp"
            mv "$TOOL_CALLS_FILE.tmp" "$TOOL_CALLS_FILE"
          fi
        done
        ;;

      # ── System init ─────────────────────────────────────────────────────────
      system)
        local subtype
        subtype=$(printf '%s' "$line" | jq -r '.subtype // empty' 2>/dev/null)
        if [[ "$subtype" == "init" ]]; then
          local model cwd
          model=$(printf '%s' "$line" | jq -r '.model // empty' 2>/dev/null)
          cwd=$(printf '%s' "$line" | jq -r '.cwd // empty' 2>/dev/null)
          [[ -n "$model" ]] && log "Model : $model"
          [[ -n "$cwd" ]]   && log "CWD   : $cwd"
          # Update runtime.json with the actual model reported by the API
          [[ -n "$model" ]] && \
            jq --arg model "$model" '.model = $model' "$RUNTIME_JSON" > "${RUNTIME_JSON}.tmp" && \
            mv "${RUNTIME_JSON}.tmp" "$RUNTIME_JSON"
        fi
        ;;

      # ── Final result → save for post-processing ─────────────────────────────
      result)
        printf '%s\n' "$line" > "$RESULT_FILE"

        local subtype session_id cost
        subtype=$(printf '%s' "$line" | jq -r '.subtype // empty' 2>/dev/null)
        session_id=$(printf '%s' "$line" | jq -r '.session_id // empty' 2>/dev/null)
        cost=$(printf '%s' "$line" | jq -r '
          if .usage then "input=\(.usage.input_tokens) output=\(.usage.output_tokens)"
          else "" end' 2>/dev/null)

        _e "\n${BOLD}══════════════════════════════════════════════${RESET}\n"
        if [[ "$subtype" == "success" ]]; then
          ok "Task completed successfully"
          [[ -n "$cost" ]] && log "Tokens : $cost"
          if [[ -n "$session_id" ]]; then
            log "Session: $session_id"
          fi
        else
          fail "Task failed: $subtype"
        fi
        ;;

      *)
        ;;
    esac
  done
}

run_claude_stream() {
  set +e
  printf '%s' "$PROMPT" | /usr/local/bin/claude "$@" 2>&1 | process_stream
  local pipe_status=("${PIPESTATUS[@]}")
  set -e
  return "${pipe_status[1]}"
}

# ── Run claude and stream-process its output ──────────────────────────────────
if ! run_claude_stream "${CLAUDE_ARGS[@]}"; then
  :
fi

# ── Fallback: if --resume was used and produced no result, retry without it ───
if [[ -n "$RESUME" && ! -s "$RESULT_FILE" ]]; then
  fail "Session resume failed (session $RESUME not found in container). Retrying without --resume..."
  # Remove --resume from CLAUDE_ARGS
  NEW_ARGS=()
  skip_next=false
  for arg in "${CLAUDE_ARGS[@]}"; do
    if $skip_next; then skip_next=false; continue; fi
    if [[ "$arg" == "--resume" ]]; then skip_next=true; continue; fi
    NEW_ARGS+=("$arg")
  done
  # Reset temp files
  : > "$TOOL_CALLS_FILE"
  : > "$RESULT_FILE"
  if ! run_claude_stream "${NEW_ARGS[@]}"; then
    :
  fi
fi

# ── Build and emit structured JSON to stdout ──────────────────────────────────
if [[ ! -s "$RESULT_FILE" ]]; then
  jq -n '{success:false, subtype:"no_result", result:"", session_id:"", usage:{}, tool_calls:[]}'
  exit 1
fi

RESULT_SUBTYPE=$(jq -r '.subtype // "unknown"' "$RESULT_FILE")

# Use --slurpfile to read large fields (result text, tool_calls) directly from
# files instead of passing them via --arg/--argjson, which hits OS ARG_MAX limit.
# --slurpfile reads a stream of JSON texts from the file; an empty
# TOOL_CALLS_FILE yields [] naturally. RESULT_FILE always contains one object.
jq -n \
  --argjson success "$([[ "$RESULT_SUBTYPE" == "success" ]] && echo 'true' || echo 'false')" \
  --slurpfile result_data "$RESULT_FILE" \
  --slurpfile tool_calls_data "$TOOL_CALLS_FILE" \
  '{
    success:    $success,
    subtype:    ($result_data[0].subtype // "unknown"),
    result:     ($result_data[0].result // ""),
    session_id: ($result_data[0].session_id // ""),
    usage:      ($result_data[0].usage // {}),
    tool_calls: ($tool_calls_data | map(del(.id)))
  }'

[[ "$RESULT_SUBTYPE" == "success" ]] && exit 0 || exit 1
