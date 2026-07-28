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
#   APPEND_SYSTEM_PROMPT_FILE
#                          Read extra system instructions from a file
#   CODIFY_TASK_SKILLS_DIR Task-local directory containing .claude/skills
#   RESUME_SESSION         Session ID to resume a specific conversation
#   CONTINUE_SESSION       "1" → --continue the most recent conversation
#   CLAUDE_MAX_TURNS       Max agent turns (default: unlimited)
#   CLAUDE_MODEL           Model to use (e.g. claude-sonnet-4-20250514)
#   CLAUDE_CODE_EXIT_AFTER_STOP_DELAY
#                          Claude CLI idle-exit delay in milliseconds (default: 5000)
#   CI_CLAUDE_RESULT_EXIT_GRACE_SECONDS
#                          Max wait for stream EOF after a final result (default: 30)
#   NO_COLOR               "1" → disable ANSI colors in stderr output

set -euo pipefail

# ── Artifact files (written to cwd so callers can locate them) ────────────────
ARTIFACT_DIR="${ARTIFACT_DIR:-${PWD}}"
mkdir -p "$ARTIFACT_DIR"
EVENT_JSONL="${ARTIFACT_DIR}/event.jsonl"
RUNTIME_JSON="${ARTIFACT_DIR}/runtime.json"
CONSOLE_LOG="${ARTIFACT_DIR}/console.log"
touch "$EVENT_JSONL" "$CONSOLE_LOG"
if [[ "${CI_CLAUDE_DISABLE_CONSOLE_TEE:-0}" != "1" ]]; then
  # Tee all stderr to console.log while preserving the caller's stderr.
  # Use a FIFO instead of process substitution so this works in restricted
  # environments where /dev/fd process-substitution targets cannot be opened.
  STDERR_TEE_DIR=$(mktemp -d)
  STDERR_TEE_PIPE="${STDERR_TEE_DIR}/stderr.pipe"
  mkfifo "$STDERR_TEE_PIPE"
  tee -a "$CONSOLE_LOG" < "$STDERR_TEE_PIPE" >&2 &
  exec 2> "$STDERR_TEE_PIPE"
  rm -f "$STDERR_TEE_PIPE"
  rmdir "$STDERR_TEE_DIR" 2>/dev/null || true
fi

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
APPEND_SYSTEM_FILE="${APPEND_SYSTEM_PROMPT_FILE:-}"
CONTINUE_SESSION="${CONTINUE_SESSION:-0}"
START_FRESH_SESSION="${START_FRESH_SESSION:-0}"
MAX_TURNS="${CLAUDE_MAX_TURNS:-}"
CLAUDE_MODEL="${CLAUDE_MODEL:-}"
CLAUDE_CODE_EXIT_AFTER_STOP_DELAY="${CLAUDE_CODE_EXIT_AFTER_STOP_DELAY:-5000}"
RESULT_EXIT_GRACE_SECONDS="${CI_CLAUDE_RESULT_EXIT_GRACE_SECONDS:-30}"
TASK_SKILLS_DIR="${CODIFY_TASK_SKILLS_DIR:-}"
CLAUDE_BIN="${CODIFY_CLAUDE_BIN:-/usr/local/bin/claude}"
SESSION_ID_FILE=".claude_session_id"

if ! [[ "$CLAUDE_CODE_EXIT_AFTER_STOP_DELAY" =~ ^[0-9]+$ ]] \
  || [[ "$CLAUDE_CODE_EXIT_AFTER_STOP_DELAY" == "0" ]]; then
  printf "CLAUDE_CODE_EXIT_AFTER_STOP_DELAY must be a positive integer: %s\n" \
    "$CLAUDE_CODE_EXIT_AFTER_STOP_DELAY" >&2
  exit 1
fi
if ! [[ "$RESULT_EXIT_GRACE_SECONDS" =~ ^[0-9]+$ ]] \
  || [[ "$RESULT_EXIT_GRACE_SECONDS" == "0" ]]; then
  printf "CI_CLAUDE_RESULT_EXIT_GRACE_SECONDS must be a positive integer: %s\n" \
    "$RESULT_EXIT_GRACE_SECONDS" >&2
  exit 1
fi
export CLAUDE_CODE_EXIT_AFTER_STOP_DELAY

if [[ -n "$APPEND_SYSTEM_FILE" && ! -f "$APPEND_SYSTEM_FILE" ]]; then
  printf "APPEND_SYSTEM_PROMPT_FILE not found: %s\n" "$APPEND_SYSTEM_FILE" >&2
  exit 1
fi
if [[ -n "$TASK_SKILLS_DIR" ]]; then
  if [[ "$TASK_SKILLS_DIR" != /* || ! -d "$TASK_SKILLS_DIR/.claude/skills" ]]; then
    printf "CODIFY_TASK_SKILLS_DIR must be an absolute directory containing .claude/skills: %s\n" \
      "$TASK_SKILLS_DIR" >&2
    exit 1
  fi
  if ! CLAUDE_VERSION_OUTPUT=$("$CLAUDE_BIN" --version 2>&1); then
    printf "Could not determine Claude Code version required for task skills: %s\n" \
      "$CLAUDE_VERSION_OUTPUT" >&2
    exit 1
  fi
  if [[ ! "$CLAUDE_VERSION_OUTPUT" =~ ([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
    printf "Could not parse Claude Code version required for task skills: %s\n" \
      "$CLAUDE_VERSION_OUTPUT" >&2
    exit 1
  fi
  CLAUDE_VERSION_MAJOR=$((10#${BASH_REMATCH[1]}))
  CLAUDE_VERSION_MINOR=$((10#${BASH_REMATCH[2]}))
  CLAUDE_VERSION_PATCH=$((10#${BASH_REMATCH[3]}))
  if (( CLAUDE_VERSION_MAJOR < 2 \
      || (CLAUDE_VERSION_MAJOR == 2 && CLAUDE_VERSION_MINOR < 1) \
      || (CLAUDE_VERSION_MAJOR == 2 && CLAUDE_VERSION_MINOR == 1 \
          && CLAUDE_VERSION_PATCH < 33) )); then
    printf "Task skills require Claude Code 2.1.33 or newer; detected: %s\n" \
      "$CLAUDE_VERSION_OUTPUT" >&2
    exit 1
  fi
fi

RESUME="${RESUME_SESSION:-}"
if [[ "$START_FRESH_SESSION" == "1" ]]; then
  # Fresh mode is the non-interactive equivalent of /clear: keep persisted transcripts and
  # project state, but never resume conversation context from any source.
  RESUME=""
  CONTINUE_SESSION="0"
elif [[ -z "$RESUME" && -f "$SESSION_ID_FILE" && "$CONTINUE_SESSION" != "1" ]]; then
  RESUME=$(cat "$SESSION_ID_FILE" 2>/dev/null || true)
fi

# ── Build claude args ─────────────────────────────────────────────────────────
CLAUDE_ARGS=(
  -p
  --output-format stream-json
  --verbose
)

if [[ "$SANDBOX_MODE" == "1" ]]; then
  CLAUDE_ARGS+=(--dangerously-skip-permissions)
else
  CLAUDE_ARGS+=(--allowedTools "$ALLOWED_TOOLS")
fi

if [[ -n "$APPEND_SYSTEM_FILE" ]]; then
  CLAUDE_ARGS+=(--append-system-prompt-file "$APPEND_SYSTEM_FILE")
elif [[ -n "$APPEND_SYSTEM" ]]; then
  CLAUDE_ARGS+=(--append-system-prompt "$APPEND_SYSTEM")
fi
[[ -n "$MAX_TURNS" ]]                && CLAUDE_ARGS+=(--max-turns "$MAX_TURNS")
[[ -n "$CLAUDE_MODEL" ]]             && CLAUDE_ARGS+=(--model "$CLAUDE_MODEL")
[[ -n "$TASK_SKILLS_DIR" ]]           && CLAUDE_ARGS+=(--add-dir "$TASK_SKILLS_DIR")
[[ "$CONTINUE_SESSION" == "1" ]]     && CLAUDE_ARGS+=(--continue)
[[ -n "$RESUME" && "$CONTINUE_SESSION" != "1" ]] && CLAUDE_ARGS+=(--resume "$RESUME")

print_claude_args() {
  local redact_next=0
  local arg

  _e "${DIM}[ci-claude] CLI args:"
  for arg in "$@"; do
    if [[ "$redact_next" == "1" ]]; then
      _e " %s" "[REDACTED]"
      redact_next=0
      continue
    fi

    case "$arg" in
      --append-system-prompt)
        _e " %s" "$arg"
        redact_next=1
        ;;
      --append-system-prompt=*)
        _e " %s" "--append-system-prompt=[REDACTED]"
        ;;
      *)
        _e " %s" "$arg"
        ;;
    esac
  done
  _e "${RESET}\n\n"
}

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
[[ -n "$TASK_SKILLS_DIR" ]]          && info "Skills : $TASK_SKILLS_DIR"
[[ -n "$RESUME" ]]               && info "Session: resuming $RESUME"
[[ "$CONTINUE_SESSION" == "1" ]] && info "Session: continuing last conversation"

# Print full CLI args (prompt is piped via stdin/file, not argv)
print_claude_args "${CLAUDE_ARGS[@]}"
log "Exit guard: CLI idle=${CLAUDE_CODE_EXIT_AFTER_STOP_DELAY}ms, final-result stream=${RESULT_EXIT_GRACE_SECONDS}s"

# ── Temp files for accumulating structured data ───────────────────────────────
# Files keep the processor independent from the CLI subprocess lifecycle.

# Write initial runtime.json; model field is updated when system init event arrives.
jq -n \
  --arg model "${CLAUDE_MODEL:-}" \
  --arg cwd "${PWD}" \
  --arg resume "${RESUME:-}" \
  '{model: $model, cwd: $cwd, resume_session: $resume}' > "$RUNTIME_JSON"

WORK_DIR=$(mktemp -d)
ACTIVE_CLAUDE_PID=""
ACTIVE_CLAUDE_PGID=""
ACTIVE_STREAM_PID=""
ACTIVE_WATCHDOG_PID=""

process_is_running() {
  local process_pid="$1"
  local state=""

  kill -0 "$process_pid" 2>/dev/null || return 1
  if [[ -r "/proc/${process_pid}/status" ]]; then
    state=$(awk '/^State:/{print $2; exit}' "/proc/${process_pid}/status" 2>/dev/null || true)
    [[ "$state" == "Z" ]] && return 1
  fi
  return 0
}

process_group_is_running() {
  local process_group_id="$1"

  [[ "$process_group_id" =~ ^[1-9][0-9]*$ ]] || return 1
  kill -0 -- "-${process_group_id}" 2>/dev/null
}

cleanup() {
  if [[ -n "$ACTIVE_WATCHDOG_PID" ]] && process_is_running "$ACTIVE_WATCHDOG_PID"; then
    kill -TERM "$ACTIVE_WATCHDOG_PID" 2>/dev/null || true
  fi
  if [[ -n "$ACTIVE_STREAM_PID" ]] && process_is_running "$ACTIVE_STREAM_PID"; then
    kill -TERM "$ACTIVE_STREAM_PID" 2>/dev/null || true
  fi
  if [[ -n "$ACTIVE_CLAUDE_PGID" ]] \
    && process_group_is_running "$ACTIVE_CLAUDE_PGID"; then
    kill -TERM -- "-${ACTIVE_CLAUDE_PGID}" 2>/dev/null || true
    kill -KILL -- "-${ACTIVE_CLAUDE_PGID}" 2>/dev/null || true
  elif [[ -n "$ACTIVE_CLAUDE_PID" ]] && process_is_running "$ACTIVE_CLAUDE_PID"; then
    kill -TERM "$ACTIVE_CLAUDE_PID" 2>/dev/null || true
    kill -KILL "$ACTIVE_CLAUDE_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

TOOL_CALLS_FILE="$WORK_DIR/tool_calls.jsonl"   # one JSON object per line
RESULT_FILE="$WORK_DIR/result.json"
RESULT_SIGNAL_FIFO="$WORK_DIR/final-result.signal"
touch "$TOOL_CALLS_FILE" "$RESULT_FILE"
mkfifo "$RESULT_SIGNAL_FIFO"

# ── Stream processor ──────────────────────────────────────────────────────────
process_stream() {
  local claude_pid="$1"
  local prev_block=""
  local cur_tool_name=""
  local cur_tool_id=""
  local cur_tool_input=""
  local cur_thinking_buf=""
  local cur_text_buf=""
  local final_result_seen=0
  local event_count=0
  local line

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    event_count=$((event_count + 1))

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

      # ── Complete assistant messages (non-delta stream-json records) ───────
      assistant)
        local assistant_count
        assistant_count=$(printf '%s' "$line" | jq '.message.content | length' 2>/dev/null || echo 0)
        local assistant_i
        for (( assistant_i=0; assistant_i<assistant_count; assistant_i++ )); do
          local block_type
          block_type=$(printf '%s' "$line" | jq -r --argjson i "$assistant_i" \
            '.message.content[$i].type // empty' 2>/dev/null)

          case "$block_type" in
            thinking)
              local thinking_text
              thinking_text=$(printf '%s' "$line" | jq -rj --argjson i "$assistant_i" \
                '.message.content[$i].thinking // empty' 2>/dev/null)
              if [[ -n "$thinking_text" ]]; then
                _e "\n${DIM}${CYAN}╔═ 🧠 Thinking ════════════════════════════════${RESET}\n"
                _e "${DIM}%s${RESET}\n" "$thinking_text"
                _e "${DIM}${CYAN}╚══════════════════════════════════════════════${RESET}\n"
              fi
              ;;
            text)
              local text
              text=$(printf '%s' "$line" | jq -rj --argjson i "$assistant_i" \
                '.message.content[$i].text // empty' 2>/dev/null)
              if [[ -n "$text" ]]; then
                _e "\n${GREEN}${BOLD}── Response ───────────────────────────────────${RESET}\n"
                _e '%s\n' "$text"
              fi
              ;;
            tool_use)
              local tool_id tool_name tool_input_json
              tool_id=$(printf '%s' "$line" | jq -r --argjson i "$assistant_i" \
                '.message.content[$i].id // empty' 2>/dev/null)
              tool_name=$(printf '%s' "$line" | jq -r --argjson i "$assistant_i" \
                '.message.content[$i].name // empty' 2>/dev/null)
              tool_input_json=$(printf '%s' "$line" | jq -c --argjson i "$assistant_i" \
                '.message.content[$i].input // {}' 2>/dev/null || echo '{}')
              local display_input_json
              display_input_json="${tool_input_json:0:500}"
              [[ ${#tool_input_json} -gt 500 ]] && display_input_json+="…(truncated)"
              _e "\n${YELLOW}┌─ ⚡ Tool: ${BOLD}${tool_name}${RESET}\n"
              _e "${YELLOW}│  Input: ${DIM}%s${RESET}\n" "$display_input_json"
              _e "${YELLOW}└──────────────────────────────────────────────${RESET}\n"
              jq -nc \
                --arg id "$tool_id" \
                --arg name "$tool_name" \
                --argjson input "$tool_input_json" \
                '{id: $id, name: $name, input: $input, output: null, error: false}' \
                >> "$TOOL_CALLS_FILE"
              ;;
          esac
        done
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

          local display_out
          display_out="${output:0:500}"
          [[ ${#output} -gt 500 ]] && display_out+="…(truncated, ${#output} chars total)"
          if [[ "$is_error" == "true" ]]; then
            _e "${RED}  ╰─ ❌ Error:${RESET}\n${DIM}%s${RESET}\n" "$display_out"
          else
            _e "${CYAN}  ╰─ ✅ Output:${RESET}\n${DIM}%s${RESET}\n" "$display_out"
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
        if [[ "$final_result_seen" == "0" ]]; then
          final_result_seen=1
          printf '%s\n' "$event_count" > "$RESULT_SIGNAL_FIFO"
          log "Final result received; waiting up to ${RESULT_EXIT_GRACE_SECONDS}s for Claude CLI stream shutdown (pid=$claude_pid, events=$event_count)"
        fi
        ;;

      *)
        ;;
    esac
  done
}

log_claude_process_snapshot() {
  local claude_pid="$1"
  local claude_pgid="$2"
  local state="unavailable"
  local parent_pid="unavailable"
  local threads="unavailable"
  local children="none"
  local group_members="unavailable"
  local status_file member_fields member_pid member_ppid member_state member_pgid

  if [[ -r "/proc/${claude_pid}/status" ]]; then
    state=$(awk '/^State:/{print $2 $3}' "/proc/${claude_pid}/status" 2>/dev/null || true)
    parent_pid=$(awk '/^PPid:/{print $2}' "/proc/${claude_pid}/status" 2>/dev/null || true)
    threads=$(awk '/^Threads:/{print $2}' "/proc/${claude_pid}/status" 2>/dev/null || true)
    if [[ -r "/proc/${claude_pid}/task/${claude_pid}/children" ]]; then
      children=$(< "/proc/${claude_pid}/task/${claude_pid}/children")
      children="${children:-none}"
    fi
  elif process_is_running "$claude_pid"; then
    state="running"
  else
    state="exited"
  fi

  if [[ -d /proc ]]; then
    group_members=""
    for status_file in /proc/[0-9]*/status; do
      [[ -r "$status_file" ]] || continue
      member_fields=$(awk '
        /^Pid:/ { pid = $2 }
        /^PPid:/ { ppid = $2 }
        /^State:/ { state = $2 }
        /^NSpgid:/ { nspgid = $2 }
        /^Pgid:/ { pgid = $2 }
        END {
          if (nspgid != "") pgid = nspgid
          printf "%s %s %s %s", pid, ppid, state, pgid
        }
      ' "$status_file" 2>/dev/null || true)
      read -r member_pid member_ppid member_state member_pgid <<< "$member_fields"
      [[ "$member_pgid" == "$claude_pgid" ]] || continue
      [[ -n "$group_members" ]] && group_members+=","
      group_members+="${member_pid:-unknown}(ppid=${member_ppid:-unknown},state=${member_state:-unknown})"
    done
    group_members="${group_members:-none}"
  fi

  log "Claude CLI process snapshot: pid=$claude_pid pgid=$claude_pgid state=${state:-unknown} ppid=${parent_pid:-unknown} threads=${threads:-unknown} children=$children group_members=$group_members"
}

terminate_claude_process_group() {
  local claude_pid="$1"
  local claude_pgid="$2"
  local attempt

  if ! process_group_is_running "$claude_pgid"; then
    log "Claude CLI process group already exited (pid=$claude_pid, pgid=$claude_pgid)"
    return
  fi

  log "Sending SIGTERM to Claude CLI process group (pid=$claude_pid, pgid=$claude_pgid) after final-result shutdown timeout"
  kill -TERM -- "-${claude_pgid}" 2>/dev/null || true
  for attempt in 1 2; do
    sleep 1
    if ! process_group_is_running "$claude_pgid"; then
      return
    fi
  done

  log "Claude CLI process group did not stop after SIGTERM; sending SIGKILL (pid=$claude_pid, pgid=$claude_pgid)"
  kill -KILL -- "-${claude_pgid}" 2>/dev/null || true
}

watch_final_result_shutdown() {
  local claude_pid="$1"
  local claude_pgid="$2"
  local stream_pid="$3"
  local result_event_count="unknown"
  local event_count="unknown"
  local last_event_type="none"
  local grace_check

  IFS= read -r result_event_count < "$RESULT_SIGNAL_FIFO" || return

  for (( grace_check=0; grace_check<RESULT_EXIT_GRACE_SECONDS * 10; grace_check++ )); do
    if ! process_is_running "$stream_pid" && ! process_group_is_running "$claude_pgid"; then
      return
    fi
    sleep 0.1
  done

  event_count=$(wc -l < "$EVENT_JSONL" | tr -d '[:space:]')
  event_count="${event_count:-$result_event_count}"
  if [[ -s "$EVENT_JSONL" ]]; then
    last_event_type=$(tail -n 1 "$EVENT_JSONL" | jq -r '.type // "unknown"' 2>/dev/null || printf 'invalid_json')
  fi
  log "Claude CLI stream did not close within ${RESULT_EXIT_GRACE_SECONDS}s after final result (pid=$claude_pid, pgid=$claude_pgid, events=${event_count:-unknown}, last_type=${last_event_type:-unknown})"
  log_claude_process_snapshot "$claude_pid" "$claude_pgid"
  terminate_claude_process_group "$claude_pid" "$claude_pgid"

  if process_is_running "$stream_pid"; then
    log "Stopping Claude CLI stream processor after final-result shutdown timeout (pid=$stream_pid)"
    kill -TERM "$stream_pid" 2>/dev/null || true
  fi
}

run_claude_stream() {
  local stream_fifo="$WORK_DIR/claude-stream.fifo"
  local prompt_input="$WORK_DIR/prompt.txt"
  local claude_pid claude_pgid stream_pid watchdog_pid stream_status cli_status

  rm -f "$stream_fifo" "$prompt_input"
  mkfifo "$stream_fifo"
  printf '%s' "$PROMPT" > "$prompt_input"
  chmod 600 "$prompt_input"

  set +e
  # Job control gives this background command its own process group without a
  # platform-specific setsid dependency. Descendants inherit the group.
  set -m
  "$CLAUDE_BIN" "$@" \
    < "$prompt_input" > "$stream_fifo" 2>&1 &
  claude_pid=$!
  set +m
  claude_pgid="$claude_pid"
  ACTIVE_CLAUDE_PID="$claude_pid"
  ACTIVE_CLAUDE_PGID="$claude_pgid"
  if ! process_group_is_running "$claude_pgid"; then
    log "Claude CLI did not start in the expected process group (pid=$claude_pid, expected_pgid=$claude_pgid)"
    kill -TERM "$claude_pid" 2>/dev/null || true
    wait "$claude_pid" 2>/dev/null || true
    ACTIVE_CLAUDE_PID=""
    ACTIVE_CLAUDE_PGID=""
    rm -f "$stream_fifo" "$prompt_input"
    set -e
    return 1
  fi
  log "Claude CLI process started (pid=$claude_pid, pgid=$claude_pgid)"

  process_stream "$claude_pid" < "$stream_fifo" &
  stream_pid=$!
  ACTIVE_STREAM_PID="$stream_pid"
  watch_final_result_shutdown "$claude_pid" "$claude_pgid" "$stream_pid" &
  watchdog_pid=$!
  ACTIVE_WATCHDOG_PID="$watchdog_pid"

  wait "$stream_pid"
  stream_status=$?
  ACTIVE_STREAM_PID=""
  if [[ "$stream_status" -ne 0 && "$stream_status" -ne 143 ]]; then
    log "Claude CLI stream processor stopped unexpectedly (status=$stream_status, pid=$claude_pid)"
  fi

  wait "$claude_pid"
  cli_status=$?
  if [[ -s "$RESULT_FILE" ]] && process_group_is_running "$claude_pgid"; then
    # The direct CLI and stream can finish while a detached-output descendant
    # remains in the group. Let the watchdog finish the group cleanup.
    wait "$watchdog_pid" 2>/dev/null || true
  else
    if process_is_running "$watchdog_pid"; then
      kill -TERM "$watchdog_pid" 2>/dev/null || true
    fi
    wait "$watchdog_pid" 2>/dev/null || true
  fi
  ACTIVE_CLAUDE_PID=""
  ACTIVE_CLAUDE_PGID=""
  ACTIVE_WATCHDOG_PID=""
  log "Claude CLI process reaped (pid=$claude_pid, pgid=$claude_pgid, exit_code=$cli_status, stream_status=$stream_status)"
  rm -f "$stream_fifo" "$prompt_input"
  set -e
  return "$cli_status"
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
  : > "$EVENT_JSONL"
  jq '.resume_session = ""' "$RUNTIME_JSON" > "${RUNTIME_JSON}.tmp" && mv "${RUNTIME_JSON}.tmp" "$RUNTIME_JSON"
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

# Drain console.log tee process before exit
exec 2>&-
wait
[[ "$RESULT_SUBTYPE" == "success" ]] && exit 0 || exit 1
