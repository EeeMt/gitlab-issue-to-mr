# CI Claude large-payload logging design

## Problem

`deploy/ci-claude.sh` currently sends large payloads through multiple hot paths:

1. human-readable streamed stderr
2. machine-readable `CODIFY_*` marker lines on stderr
3. structured task log metadata in the backend
4. final task summary payloads emitted again from `entrypoint.worker.sh`

For large `Write` tool inputs, large tool outputs, long assistant text, or long thinking blocks, the same content can be duplicated several times. This inflates log volume, database writes, API payload size, and frontend rendering cost.

At the same time, the system still needs:

- full traceability for large payloads
- an original log tab that preserves the raw streamed process log as completely as practical
- lightweight default log APIs and timeline views

## Goals

1. Preserve complete payloads for debugging and auditability.
2. Keep the original log tab close to the full streamed stderr/stdout experience.
3. Remove large payload duplication from structured logs and summary markers.
4. Make default task log reads lightweight.
5. Preserve existing task timeline semantics for tool start, tool result, thinking, assistant text, and system init.

## Non-goals

1. Backfilling historical tasks into the new storage model.
2. Cross-task deduplication of payloads.
3. Changing the semantic meaning of existing task statuses or timeline event types.

## Design summary

Split logging into three storage paths with different responsibilities:

| Path | Purpose | Storage | Default read pattern |
| --- | --- | --- | --- |
| Structured timeline | UI cards, timeline, task detail summaries | `TaskLog` | always |
| Full payload archive | full tool input/output, full assistant text, full thinking text | `task_payloads` | on demand |
| Raw streamed process log | original log tab, full download | `task_raw_log_chunks` | tail/paged on demand |

The core rule is:

**hot paths store previews and references; cold paths store full bodies.**

## Data model

### `task_payloads`

Stores one full payload body per logical event that needs full-fidelity retrieval.

Suggested columns:

- `id`
- `task_id`
- `payload_kind` — `tool_input`, `tool_output`, `assistant_text`, `thinking`
- `tool_use_id` nullable
- `content_type` — `text/plain`, `application/json`
- `encoding` — `identity`, `gzip`, or `zstd`
- `content` — compressed or plain bytes/text
- `sha256`
- `char_count`
- `byte_count`
- `created_at`

### `task_raw_log_chunks`

Stores the raw streamed stderr/stdout log for the original log tab.

Suggested columns:

- `id`
- `task_id`
- `sequence_no`
- `encoding`
- `content`
- `char_count`
- `byte_count`
- `created_at`

Chunks are append-only and ordered by `sequence_no`.

### `TaskLog` changes

`TaskLog` remains the structured event timeline. Its metadata should become lightweight and reference full payloads instead of embedding them.

Suggested metadata fields by event type:

- `tool_call`
  - `name`
  - `input_preview`
  - `input_payload_id`
  - `input_char_count`
  - `output_preview`
  - `output_payload_id`
  - `output_char_count`
  - `error`
  - `is_truncated`
- `assistant_text`
  - `text_preview`
  - `payload_id`
  - `char_count`
  - `is_truncated`
- `thinking`
  - `text_preview`
  - `payload_id`
  - `char_count`
  - `is_truncated`
- `system_init`
  - existing small metadata fields only; no payload indirection is needed

## End-to-end flow

### 1. `ci-claude.sh`

Keep human-readable streaming output on stderr so the original log experience remains intact.

Change the machine-readable marker lines so they only carry:

- previews
- counts
- hashes
- identifiers
- truncation flags

Do **not** include full tool input, full tool output, full assistant text, or full thinking text in `CODIFY_*` marker lines.

Specific changes:

- `CODIFY_TOOL_USE_START`
  - include `id`, `name`, `input_preview`, `input_char_count`, `input_sha256`, `input_truncated`
- `CODIFY_TOOL_RESULT`
  - include `id`, `output_preview`, `output_char_count`, `output_sha256`, `error`, `output_truncated`
- `CODIFY_ASSISTANT_TEXT`
  - include `text_preview`, `char_count`, `sha256`, `truncated`
- `CODIFY_THINKING`
  - include `text_preview`, `char_count`, `sha256`, `truncated`

Retain the final JSON result on stdout, but do not re-expand large structured tool payloads into new large marker lines later in the entrypoint.

### 2. `worker.py`

When the backend sees structured marker events:

1. build a preview for timeline display
2. store the full body into `task_payloads`
3. store only preview metadata plus `payload_id` into `TaskLog`

For raw streamed chunks:

- stop treating the raw stream as ordinary structured `TaskLog.message` content for long-term storage
- append raw log chunks to `task_raw_log_chunks`
- keep the chunking append-only and sequential

This preserves the original log tab without forcing the default timeline path to carry the full raw log volume.

### 3. `entrypoint.worker.sh`

Stop emitting a large `CODIFY_TOOL_CALLS` aggregate marker built from the final JSON payload.

Keep only:

- usage stats
- session id
- lightweight final summary text

The final summary is already truncated and can remain a hot-path artifact. Full payload retrieval should come from `task_payloads`, not from rebuilding a giant aggregate line.

## Preview, truncation, and compression policy

### Preview sizes

Recommended defaults:

- tool input preview: 4 KB
- tool output preview: 4 KB
- assistant text preview: 2 KB
- thinking preview: 2 KB

Every preview should include:

- `char_count`
- `byte_count`
- `sha256`
- `is_truncated`

### Compression

Recommended defaults:

- `< 8 KB`: store as `identity`
- `>= 8 KB`: store compressed

Compression metadata must be stored explicitly so the API can decode on demand.

## API changes

### Existing logs API

`GET /api/tasks/{task_id}/logs`

Continue returning the structured timeline, but only with previews and payload references.

### New payload API

`GET /api/tasks/{task_id}/payloads/{payload_id}`

Returns the decoded full payload body and metadata.

### New raw log API

`GET /api/tasks/{task_id}/raw-logs`

Supports:

- tail reads
- chunk pagination
- full download endpoint

The UI should not request the entire raw log by default.

## UI behavior

### Timeline / structured task detail

- show previews by default
- show size/truncation indicators
- offer “expand full content” for payload-backed events

### Original log tab

- read from raw log chunks, not from oversized structured metadata
- default to the latest chunk window
- support incremental fetch for older chunks
- support download of the complete raw log

## Failure handling

The system must not claim that full content is available if payload storage failed.

If payload storage fails:

- store the preview if available
- mark the event as payload storage failed
- surface this explicitly in structured metadata

If raw log chunk storage fails:

- mark raw log persistence as partial or failed
- do not silently claim full raw-log retention

This preserves honesty about retention guarantees.

## Migration strategy

Use a forward-only rollout:

1. add new tables
2. add model and API support
3. switch backend writes to preview + payload + raw chunk storage
4. slim `ci-claude.sh` markers
5. stop aggregate large tool-call summary emission in `entrypoint.worker.sh`
6. update the frontend original log tab to read chunked raw logs

Do not backfill historical tasks.

Historical tasks remain readable through the existing path. New tasks use the new storage model.

## Testing strategy

### Unit tests

- `ci-claude.sh`
  - markers no longer carry full large payloads
  - previews, counts, hashes, and truncation flags are emitted correctly
  - human-readable stderr still streams
- `worker.py`
  - marker parsing creates preview-only `TaskLog` metadata
  - full payloads are written to `task_payloads`
  - raw stream chunks are written to `task_raw_log_chunks`
  - failure states are represented honestly

### Integration tests

Use fake Claude outputs with MB-scale payloads to verify:

- default logs remain lightweight
- payload API returns full bodies
- raw log tab can retrieve complete raw stream chunks
- no large aggregate `CODIFY_TOOL_CALLS` line is emitted

## Trade-offs

### Benefits

- preserves complete payloads
- keeps the original log tab useful
- removes duplicate hot-path amplification
- makes default structured log reads cheap again

### Costs

- new tables and APIs
- more moving parts in the worker ingestion path
- additional frontend work for on-demand payload expansion and raw-log pagination

## Recommendation

Implement this design in phases, but keep the architectural boundary strict from the start:

- previews in `TaskLog`
- full bodies in `task_payloads`
- raw stream in `task_raw_log_chunks`

That boundary is what prevents the same large payload from being copied across every layer of the system.
