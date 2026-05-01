# CI Claude event archive design

## Problem

The current CI Claude logging chain overloads one transport with three incompatible jobs:

1. human-readable console logging
2. machine-readable event transport
3. full-payload archival

This creates repeated large-payload amplification, fragile parsing, and a design conflict: preview-only markers keep hot paths small, but worker-side full-payload archival cannot rely on preview-only markers.

## Decision

Redesign the chain around **Claude raw event mirroring** as the structured source of truth.

The runtime will produce three parallel artifacts:

1. `event.jsonl` — append-only mirror of Claude `stream-json` output
2. `runtime.json` — one-time runtime context snapshot
3. `console.log` — human-readable console log

The backend worker will stop using `CODIFY_*` markers as the primary structured input. Instead:

- `event.jsonl` drives timeline projection and payload archival
- `console.log` drives the raw-log experience
- `runtime.json` provides downloadable runtime context

`CODIFY_*` markers are removed rather than kept for compatibility.

## Goals

1. Preserve raw Claude events for auditability and debugging.
2. Keep raw console logs real-time during execution and still visible after task completion.
3. Keep timeline and structured task detail lightweight by default.
4. Make full tool input/output and text bodies available on demand while tasks are still running.
5. Provide a durable downloadable runtime archive after task completion.

## Non-goals

1. Keeping backward compatibility with the old `CODIFY_*` marker protocol.
2. Using stdout/stderr as the structured source of truth.
3. Backfilling historical tasks into the new archive model.

## Source-of-truth model

### Structured source of truth

`event.jsonl` is the authoritative machine-readable record of Claude activity.

Each line is one Claude `stream-json` event written in append-only order. The file should preserve the raw event payload as faithfully as practical rather than rewriting it into a Codify-specific event schema.

### Human-readable source of truth

`console.log` is the authoritative human-readable execution log. It is optimized for operators reading the task in real time or after completion.

### Derived data

Database rows are projections derived from `event.jsonl` and `console.log`. They are optimized for UI reads, indexing, and incremental rendering rather than archival fidelity.

## Runtime artifacts

### `event.jsonl`

Contains the mirrored Claude `stream-json` events in arrival order.

Properties:

- append-only
- newline-delimited JSON
- preserves the original Claude event shape as closely as possible
- available during task execution
- archived after task completion

Each line is the raw event object emitted by Claude's `stream-json` mode, written verbatim. `ci-claude.sh` does **not** wrap events in an additional envelope. Example line:

```json
{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"toolu_01","name":"Write"}}}
```

The outer `type: stream_event` field is part of Claude's own `stream-json` format; it is not added by Codify.

### `runtime.json`

Contains a one-time snapshot of execution context. It is written in two passes:

1. **Before Claude is invoked**: write what is known from environment variables (cwd, configured model, resume session ID, task/issue identifiers).
2. **On first `system` init event from Claude**: update the `model` field with the actual model reported by Claude, which takes precedence over the env-var value.

Recommended contents:

- Claude model and invocation mode (from `system` init event if available, else from env)
- current working directory
- session/resume identifiers
- selected runtime configuration values that matter for debugging
- task and issue identifiers needed to interpret the run

It is not a Claude event file. It is runtime metadata for the run archive.

### `console.log`

Contains the rendered console output shown to humans. It includes colors or formatting only if the rendering path already expects them safely; otherwise store plain text.

It remains available during task execution and is also archived after task completion.

## `ci-claude.sh` responsibilities

`ci-claude.sh` becomes a stream fan-out and rendering layer instead of a marker protocol producer.

It has three responsibilities:

1. invoke Claude in `stream-json` mode
2. mirror each raw event line into `event.jsonl`
3. render those events into human-readable console output and final task result output

It no longer emits `CODIFY_*` markers.

### Final result output

`ci-claude.sh` still needs a lightweight completion payload for its caller. This is separate from the event archive.

The script should continue producing:

- a final `result.json` inside the container for internal handoff
- a final JSON object on stdout for the caller

This completion payload must stay lightweight. It may include:

- `success`
- `subtype`
- `result`
- `session_id`
- `usage`

It must not carry large tool-call aggregates or full event bodies.

## Worker ingestion model

The worker runs two independent ingestion flows.

### 1. Event tailer

The event tailer reads `event.jsonl` incrementally during task execution.

Responsibilities:

- detect newly appended event lines
- parse raw Claude events
- project them into lightweight timeline entries
- extract full tool input/output and text bodies
- write extracted full bodies to `task_payloads`

The event tailer is the only component that derives structured timeline entries.

#### Tool result correlation

Claude emits tool call input and tool result as separate events linked by `tool_use_id`. The event tailer must buffer an in-progress tool use (tracking `id`, `name`, and accumulated `input_json_delta` parts) and flush it to a `tool_input` payload when `content_block_stop` arrives. Tool result events (`{"type":"tool_result","tool_use_id":"...","content":[...]}`) are correlated back to the originating tool call using `tool_use_id` and stored as a `tool_output` payload, then the corresponding `TaskLog` row is updated with the `output_payload_id`.

### 2. Console tailer

The console tailer reads `console.log` incrementally during task execution.

Responsibilities:

- capture raw console output for the raw-log tab
- write raw chunks to `task_raw_log_chunks`

The console tailer does not attempt to infer structured event semantics.

## Database projection model

### `TaskLog`

`TaskLog` remains the lightweight timeline projection.

It stores:

- event type
- preview fields for display
- event timestamps
- payload row references for `tool_input`, `tool_output`, `assistant_text`, and `thinking`
- truncation and size metadata

It does not store full tool input/output or full text bodies inline.

### `TaskPayload`

`TaskPayload` stores full large bodies extracted from raw Claude events.

Typical payload kinds:

- `tool_input`
- `tool_output`
- `assistant_text`
- `thinking`

This is not the archival source of truth for the entire run. It is a query-optimized extraction layer so the UI can load one body directly without scanning the full `event.jsonl` archive.

### `TaskRawLogChunk`

`TaskRawLogChunk` stores raw console-log chunks for the raw-log tab fallback and post-completion browsing.

The raw-log tab reads recent chunks first, then paginates older content on demand.

## UI behavior

### Timeline / structured task detail

The timeline reads from `TaskLog`.

Default behavior:

- show previews only
- show truncation indicators
- show size metadata where helpful
- allow on-demand expansion of the full body via `TaskPayload`

### Raw log tab

The raw log tab reads from the console-log projection.

Behavior:

- during execution: real-time updates from the running task
- after completion: continue reading stored raw log chunks
- default load: most recent segment only
- allow “load more” for older chunks
- allow downloading the complete `console.log` archive

### Download archive

After task completion, the system stores a compressed runtime archive containing at least:

- `event.jsonl`
- `runtime.json`
- `console.log`

This archive is downloadable even after the task has finished.

## Idempotency and resume behavior

### Event ingest

The event tailer must be resumable and idempotent.

Required approach:

- persist a per-task event cursor (`TaskIngestCursor`) tracking byte offset and sequence number
- enforce a DB-level unique constraint on `(task_id, event_seq)` in `TaskLog` so that replaying the same event line cannot insert a duplicate timeline projection
- when the constraint fires on replay, skip rather than error

If Claude output already includes stable identifiers such as `tool_use_id`, use them in the projection model. For raw event mirroring, preserve the original order exactly.

### Console ingest

The console tailer must persist a cursor or sequence position so that restarts do not duplicate raw chunks or skip content.

### Worker restarts

On worker restart, the ingestion flows resume from the last persisted cursor for:

- `event.jsonl`
- `console.log`

This allows recovery without reparsing the entire run from scratch during normal operation.

## Archive lifecycle

### During execution

Files remain live and append-only inside the task workspace:

- `event.jsonl`
- `runtime.json`
- `console.log`

### At completion

Create a compressed archive from those files and persist it for later download.

Recommended output:

- one archive bundle per task run
- metadata describing archive path, size, and creation time

### Post-completion retention

The UI does not need to read the archive bundle directly for normal use. It continues to use:

- `TaskLog` for timeline
- `TaskPayload` for full-body expansion
- `TaskRawLogChunk` for raw log browsing

The archive is the durable original-material package for download and deep debugging.

## Failure handling

### Event file problems

If `event.jsonl` cannot be written or tailed correctly:

- mark structured event capture as degraded
- continue console logging when the console path remains healthy
- do not pretend timeline completeness if raw event capture failed

### Console log problems

If `console.log` cannot be persisted:

- keep timeline ingestion running when the event tailer remains healthy
- mark raw-log retention as partial or failed

### Archive creation problems

If the post-run archive cannot be created:

- keep DB projections available
- surface archive status explicitly
- do not report downloadable archive availability unless the archive exists

## Migration strategy

Use a forward-only migration.

1. introduce event-archive files and worker tailers
2. switch timeline projection to consume `event.jsonl`
3. remove `CODIFY_*` marker generation and parsing
4. keep raw console logging independent
5. add post-completion archive packaging and download support
6. implement failure-mode tracking: degraded event capture flag, archive status surfacing in API response

Historical tasks stay on the old read path. New tasks use the new archive pipeline.

## Testing strategy

### Script tests

Verify `ci-claude.sh`:

- mirrors raw Claude events into `event.jsonl`
- renders human-readable output to the console
- still emits the lightweight final result JSON
- no longer emits `CODIFY_*` markers

### Worker tests

Verify:

- raw Claude events are projected correctly into `TaskLog`
- full bodies are extracted into `TaskPayload`
- console output is chunked into `TaskRawLogChunk`
- restart/resume behavior is idempotent

### Integration tests

Verify:

- timeline updates while the task is running
- raw log tab updates while the task is running
- after completion, raw log tab still works from stored chunks
- archive bundle contains `event.jsonl`, `runtime.json`, and `console.log`
- downloading the archive works after completion

## Why this design

This design removes the root confusion in the current system:

- console logs are for humans
- Claude raw events are for machines
- database rows are for fast UI reads

Once those responsibilities are separated, the previous preview-versus-full-body conflict disappears. Previews live in the UI projection layer, while full fidelity remains available in the raw event archive and the payload extraction layer.
