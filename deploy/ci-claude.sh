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
#
# Environment variables:
#   SANDBOX_MODE           "1" → --dangerously-skip-permissions (sandbox containers only!)
#   ALLOWED_TOOLS          Comma-separated tool list, e.g. "Bash,Read,Edit,Write"
#                          Ignored when SANDBOX_MODE=1. Default: "Bash,Read,Edit,Write"
#   APPEND_SYSTEM_PROMPT   Extra system instructions appended to default prompt
#   RESUME_SESSION         Session ID to resume a specific conversation
#   CONTINUE_SESSION       "1" → --continue the most recent conversation
#   CLAUDE_MAX_TURNS       Max agent turns (default: unlimited)
#   CLAUDE_MODEL           Model to use (e.g. claude-sonnet-4-20250514)
#   NO_COLOR               "1" → disable ANSI colors in stderr output

set -euo pipefail

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
PROMPT="${1:-}"
if [[ -z "$PROMPT" ]]; then
  printf "Usage: %s <prompt>\n\n" "$0" >&2
  printf "  SANDBOX_MODE=1 %s 'Run tests and fix failures'\n" "$0" >&2
  printf "  ALLOWED_TOOLS=Bash,Read %s 'Explain the auth module'\n" "$0" >&2
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
  -p "$PROMPT"
  --output-format stream-json
  --verbose
  --include-partial-messages
  --no-session-persistence
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
info "Prompt : $PROMPT"
if [[ "$SANDBOX_MODE" == "1" ]]; then
  info "Tools  : ALL (sandbox — dangerously-skip-permissions)"
else
  info "Tools  : $ALLOWED_TOOLS"
fi
[[ -n "$CLAUDE_MODEL" ]]             && info "Model  : $CLAUDE_MODEL"
[[ -n "$MAX_TURNS" ]]                && info "MaxTurns: $MAX_TURNS"
[[ -n "$RESUME" ]]               && info "Session: resuming $RESUME"
[[ "$CONTINUE_SESSION" == "1" ]] && info "Session: continuing last conversation"

# Print full CLI args (excluding the prompt at index 1)
_e "${DIM}[ci-claude] CLI args:"
for arg in "${CLAUDE_ARGS[@]}"; do
  [[ "$arg" == "$PROMPT" ]] && continue
  _e " %s" "$arg"
done
_e "${RESET}\n\n"

# ── Temp files for accumulating structured data ───────────────────────────────
# Needed because process_stream runs in a pipe subshell and can't set outer vars.
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

    local type
    type=$(printf '%s' "$line" | jq -r '.type // empty' 2>/dev/null) || continue
    [[ -z "$type" ]] && continue

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
                printf 'CODIFY_THINKING:%s\n' "$(jq -c -n --arg text "$cur_thinking_buf" '{text: $text}')" >&2
                cur_thinking_buf=""
                ;;
              tool_use)
                _e "${RESET}\n${YELLOW}└──────────────────────────────────────────────${RESET}\n"
                # Persist tool call stub for the final batch JSON (entrypoint.sh reads this)
                local safe_input
                safe_input=$(printf '%s' "${cur_tool_input:-{\}}" | jq -c '.' 2>/dev/null || echo '{}')
                jq -nc \
                  --arg name "$cur_tool_name" \
                  --argjson input "$safe_input" \
                  '{name: $name, input: $input, output: null, error: false}' \
                  >> "$TOOL_CALLS_FILE"
                # Emit structured tool-use event to stderr for worker.py Python parsing
                printf 'CODIFY_TOOL_USE_START:%s\n' \
                  "$(jq -c -n --arg id "$cur_tool_id" --arg name "$cur_tool_name" --argjson input "$safe_input" \
                     '{id: $id, name: $name, input: $input}')" >&2
                cur_tool_input=""
                cur_tool_id=""
                ;;
              text)
                _e "\n"
                printf 'CODIFY_ASSISTANT_TEXT:%s\n' "$(jq -c -n --arg text "$cur_text_buf" '{text: $text}')" >&2
                cur_text_buf=""
                ;;
            esac
            prev_block=""
            ;;
        esac
        ;;

      # ── Tool execution results (delivered in user messages after each assistant turn)
      # NOTE: This handler fires only when the API emits user-turn events in stream-json.
      # Tested with MiniMax-M2.5 (minimaxi.com Anthropic API): user-turn events are NOT
      # emitted, so CODIFY_TOOL_RESULT is never sent and tool outputs remain null.
      # If a future API/model supports it, this handler will work as intended.
      user)
        local count
        count=$(printf '%s' "$line" | jq '[.content[]? | select(.type == "tool_result")] | length' 2>/dev/null || echo 0)
        local i
        for (( i=0; i<count; i++ )); do
          local tool_use_id output is_error stored_out
          # Use filtered-array indexing to avoid off-by-one if content has mixed types
          tool_use_id=$(printf '%s' "$line" | jq -r --argjson i "$i" \
            '[.content[]? | select(.type == "tool_result")][$i].tool_use_id // ""' 2>/dev/null)
          output=$(printf '%s' "$line" | jq -r --argjson i "$i" \
            '[.content[]? | select(.type == "tool_result")][$i] |
            if (.content | type) == "array" then (.content | map(.text // "") | join(""))
            elif (.content | type) == "string" then .content
            else (.output // "") end' 2>/dev/null)
          is_error=$(printf '%s' "$line" | jq -r --argjson i "$i" \
            '[.content[]? | select(.type == "tool_result")][$i].is_error // false' 2>/dev/null)

          if [[ "$is_error" == "true" ]]; then
            _e "${RED}  ╰─ ❌ Error:  ${DIM}%.400s${RESET}\n" "$output"
          else
            _e "${CYAN}  ╰─ ✅ Output: ${DIM}%.400s${RESET}\n" "$output"
          fi

          # Emit tool result to stderr for worker.py to correlate with CODIFY_TOOL_USE_START
          stored_out="${output:0:2000}"
          [[ ${#output} -gt 2000 ]] && stored_out+="…(truncated)"
          printf 'CODIFY_TOOL_RESULT:%s\n' \
            "$(jq -c -n --arg id "$tool_use_id" --arg out "$stored_out" --argjson err "$is_error" \
               '{id: $id, output: $out, error: $err}')" >&2

          # Also update TOOL_CALLS_FILE stub (for backward-compat batch in entrypoint.sh)
          if [[ -s "$TOOL_CALLS_FILE" ]]; then
            local stub_line updated
            stub_line=$(grep -nm 1 '"output":null' "$TOOL_CALLS_FILE" | cut -d: -f1)
            if [[ -n "$stub_line" ]]; then
              updated=$(sed -n "${stub_line}p" "$TOOL_CALLS_FILE" | jq -c \
                --arg out "$stored_out" \
                --argjson err "$is_error" \
                '.output = $out | .error = $err')
              {
                head -n $(( stub_line - 1 )) "$TOOL_CALLS_FILE" 2>/dev/null || true
                printf '%s\n' "$updated"
                tail -n +$(( stub_line + 1 )) "$TOOL_CALLS_FILE" 2>/dev/null || true
              } > "$TOOL_CALLS_FILE.tmp"
              mv "$TOOL_CALLS_FILE.tmp" "$TOOL_CALLS_FILE"
            fi
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
          printf 'CODIFY_SYSTEM_INIT:%s\n' "$(jq -c -n --arg model "$model" --arg cwd "$cwd" '{model: $model, cwd: $cwd}')" >&2
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

# ── Run claude and stream-process its output ──────────────────────────────────
/usr/local/bin/claude "${CLAUDE_ARGS[@]}" 2>&1 | process_stream

# ── Build and emit structured JSON to stdout ──────────────────────────────────
if [[ ! -s "$RESULT_FILE" ]]; then
  jq -n '{success:false, subtype:"no_result", result:"", session_id:"", usage:{}, tool_calls:[]}'
  exit 1
fi

RESULT_SUBTYPE=$(jq -r '.subtype // "unknown"' "$RESULT_FILE")
RESULT_TEXT=$(jq -r '.result // ""' "$RESULT_FILE")
SESSION_ID=$(jq -r '.session_id // ""' "$RESULT_FILE")
USAGE_JSON=$(jq -c '.usage // {}' "$RESULT_FILE")

TOOL_CALLS_JSON="[]"
if [[ -s "$TOOL_CALLS_FILE" ]]; then
  TOOL_CALLS_JSON=$(jq -sc '.' "$TOOL_CALLS_FILE")
fi

jq -n \
  --argjson success "$([[ "$RESULT_SUBTYPE" == "success" ]] && echo 'true' || echo 'false')" \
  --arg subtype "$RESULT_SUBTYPE" \
  --arg result "$RESULT_TEXT" \
  --arg session_id "$SESSION_ID" \
  --argjson usage "$USAGE_JSON" \
  --argjson tool_calls "$TOOL_CALLS_JSON" \
  '{
    success:    $success,
    subtype:    $subtype,
    result:     $result,
    session_id: $session_id,
    usage:      $usage,
    tool_calls: $tool_calls
  }'

[[ "$RESULT_SUBTYPE" == "success" ]] && exit 0 || exit 1
