# Harness event fixtures

Committed fixtures use `codify.harness.fixture/v1` and this directory shape:

```text
<harness>/<scenario>/
  metadata.json
  stdout.jsonl
  stderr.log
  process.json
  expected-canonical.jsonl
```

Every scenario is a self-contained, sanitized capture. `metadata.json` contains `harness`,
`scenario`, exact CLI and Adapter candidate versions, installation source, binary digest, image
digest (nullable only for a host probe), sanitized command arguments, Provider kind/wire protocol,
platform, start/end time, expected Harness result, expected Task result, and review state.

`expected-canonical.jsonl` is a complete attempt: it starts with `run.started`, includes exactly
one `harness.completed` or `harness.failed`, includes `worker.finalization`, and ends with exactly
one `run.completed` or `run.failed`. Harness and delivery records are non-terminal. Unknown raw
records become `diagnostic`; raw Claude/Codex field names may not leak into the canonical envelope.

Before committing, all five files must pass the repository fixture test, the sanitizer negative
scan, and manual review. API keys, tokens, cookies, private URLs, operator paths, hidden reasoning,
real private repository text, or raw captures marked `raw-restricted-do-not-commit` are forbidden.

The committed matrix contains all 16 required scenarios for both Claude Code `2.1.152` and Codex
CLI `0.146.0-alpha.3.1`. It was captured on Darwin/arm64 against DeepSeek using only
`deepseek-v4-flash`; controlled authentication, 429, network, timeout, and signal scenarios used
invalid credentials or a loopback probe server. Every entry is marked
`collection_state=sanitized-reviewed-real-probe`.

The sanitizer removes credentials, operator paths, correlation identifiers, reasoning signatures,
and hidden reasoning content while preserving stable event and tool relationships. In the observed
Codex stream, context compaction is exposed through a CLI advisory item rather than a dedicated
lifecycle event; the expected canonical fixture records that evidence as `context.compacted`.

Run the strict Phase 0 release audit with:

```bash
CODIFY_REQUIRE_REAL_HARNESS_FIXTURES=1 \
  backend/.venv/bin/python -m pytest \
  backend/tests/unit/test_harness_event_fixtures.py -v
```

The test requires the exact 16-scenario directory set for both Harnesses and fails if any fixture
is missing, synthetic, unsafe, non-idempotent, or cannot replay as one complete attempt.
