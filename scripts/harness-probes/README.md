# Harness protocol probes

These probes collect evidence for `codify.worker.harness/v1`. They do not change the
production Worker path. Raw captures are sensitive and must remain in a mode-0700 temporary
directory outside the repository until they have been sanitized and reviewed.

## Fixed probe baseline

| Harness | CLI version | Source | Local binary | Digest evidence |
|---|---|---|---|---|
| Claude Code | `2.1.152` | installed operator CLI | `/opt/homebrew/bin/claude` | record `shasum -a 256 "$(command -v claude)"` in the restricted evidence log |
| Codex | `0.146.0-alpha.3.1` | Codex desktop bundle | `/Applications/ChatGPT.app/Contents/Resources/codex` | record `shasum -a 256 "$(command -v codex)"` in the restricted evidence log |

Changing either version requires a new fixture generation, not an in-place edit of expected
output. A committed fixture records the version, source, sanitized command shape, platform,
image digest (or `null` for a host-only probe), Provider kind, wire protocol, and outcome.

## Security prerequisites

- Use a disposable repository with no private remotes and a temporary Harness home.
- Load Provider credentials from Codify's encrypted secret store or another non-echoing secret
  source. A persistent internal Provider key is acceptable for success probes, but it must not
  appear in command arguments, fixture files, shell history, or terminal output. Never manufacture
  an authentication failure by damaging that credential; use a deliberately invalid probe value.
- The operator running a network/rate-limit probe owns the raw capture until it is sanitized,
  scanned, and destroyed.
- `run-probe.sh` records only environment key names. It never records environment values.
- Review sanitized output for hidden reasoning, private source text, repository URLs, user paths,
  session/tool correlation, and malformed JSON before moving it into `backend/tests/fixtures`.

## Scenario matrix

Each row is required for both Harnesses. The Harness terminal is independent from the final Task
terminal: delivery and finalization can still make a successful Harness attempt fail.

| Scenario | Controlled condition | Harness terminal | Complete-attempt Task terminal |
|---|---|---|---|
| `success` | read and create one harmless file | `harness.completed` | `run.completed` |
| `success_no_changes` | answer without changing files | `harness.completed` | `run.completed` or `run.failed(require_changes)` |
| `tool_success` | one permitted tool succeeds | `harness.completed` | `run.completed` |
| `tool_failure` | one tool returns non-zero and the agent reports it | `harness.completed` or `harness.failed` per observed CLI result | `run.failed` when the goal is not recovered |
| `new_session` | isolated Harness home | `harness.completed` | `run.completed` |
| `resume` | resume the preceding session in the same namespace | `harness.completed` | `run.completed` |
| `invalid_session` | syntactically valid nonexistent session | `harness.failed` | `run.failed` (`protocol_error` if the CLI silently changes session semantics) |
| `authentication_failure` | deliberately invalid test credential | `harness.failed` | `run.failed(authentication_error)` |
| `rate_limited` | controlled test endpoint returns 429 | `harness.failed` | `run.failed(rate_limited)` |
| `network_interruption` | controlled test endpoint becomes unavailable | `harness.failed` | `run.failed(engine_error)` |
| `timeout` | wrapper wall clock expires | `harness.failed` | `run.failed(timeout)` |
| `sigterm` | signal the process group during a tool call | `harness.failed` | `run.failed(cancelled)` |
| `sigkill` | ignore TERM, then exceed grace period | absent or `harness.failed` | synthesized `run.failed(protocol_error)` after finalization evidence |
| `cancelled` | persisted cancellation triggers termination | `harness.failed` | `run.failed(cancelled)` |
| `context_compaction` | small controlled context limit / long input | `harness.completed` | `run.completed` |
| `usage_model` | successful request with usage/model output | `harness.completed` | `run.completed`; unknown usage fields remain `null` |

Required event shapes are recorded even when several appear in one scenario: Claude `system/init`,
message deltas and completions, tool use/result, compact boundary, result/usage/session; Codex
thread/turn/item lifecycle, tool results, usage, resolved model, retry, and turn completion.

## DeepSeek validation profile

The 2026-08-01 real fixture matrix uses only `deepseek-v4-flash`:

- Claude Code uses `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`; the configured key is
  supplied as `ANTHROPIC_AUTH_TOKEN`, and every Claude model alias is pinned to
  `deepseek-v4-flash`.
- Codex uses a custom Provider with `base_url=https://api.deepseek.com/`, `wire_api=responses`, and
  an isolated official model catalog containing only `deepseek-v4-flash`. Plugins are disabled so
  an isolated probe does not warm the ChatGPT plugin catalog.
- A direct preflight confirmed both Anthropic Messages and Responses return HTTP 200 with the
  resolved model `deepseek-v4-flash` before CLI collection began.

Observed differences are fixture evidence: Claude emits `system/compact_boundary`; Codex
`exec --json` reports compaction as an advisory item in this CLI version. Claude retries
authentication, network, and 429 failures until the wrapper deadline, whereas Codex emits
retry/error records and may terminate earlier.

## Capture workflow

```bash
raw_dir=$(mktemp -d /tmp/codify-harness-raw.XXXXXX)
chmod 700 "$raw_dir"

scripts/harness-probes/run-probe.sh \
  --harness claude \
  --scenario success_no_changes \
  --output-dir "$raw_dir/claude/success_no_changes" \
  --version-command 'claude --version' \
  -- claude -p --output-format stream-json --verbose 'Reply with PROBE_OK only'
```

Use an explicit isolated `CODEX_HOME` and `codex exec --json` for Codex. Resume is a separate
command (`codex exec resume <SESSION_ID>`) and must not be treated as an ordinary option appended
to a new-run invocation.

Sanitize into a separate directory, then repeat sanitation to prove idempotence:

```bash
scripts/harness-probes/sanitize_fixture.py "$raw_dir/claude/success_no_changes/stdout.jsonl" \
  /tmp/fixture/stdout.jsonl
scripts/harness-probes/sanitize_fixture.py /tmp/fixture/stdout.jsonl /tmp/fixture/again.jsonl
cmp /tmp/fixture/stdout.jsonl /tmp/fixture/again.jsonl
scripts/harness-probes/sanitize_fixture.py --check /tmp/fixture/stdout.jsonl
```

Generate `expected-canonical.jsonl`, set `collection_state` to `sanitized-reviewed-real-probe`
(the value enforced by `test_harness_event_fixtures.py`), run the offline replay tests, record the
fixture commit SHA, then securely delete the restricted raw directory. A raw or partially reviewed
capture is never moved into Git.

## Offline self-test

```bash
bash -n scripts/harness-probes/run-probe.sh
tmp=$(mktemp -d /tmp/codify-probe-selftest.XXXXXX)
scripts/harness-probes/run-probe.sh \
  --harness fake --scenario success --output-dir "$tmp" \
  --version-command 'printf "fake 1.0\n"' --timeout 5 -- \
  bash -c 'printf "%s\n" "{\"type\":\"result\"}"'
```

The fake self-test needs no network, CLI configuration, or Provider credential.
