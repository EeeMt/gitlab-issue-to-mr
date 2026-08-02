# Worker Canonical Event v1

`codify.worker.event/v1` is the only business event protocol consumed by the Backend and Frontend.
Harness raw output is sanitized and archived separately at `harness-events/<harness>.jsonl`.

## Envelope

Every record contains `schema`, globally unique `event_id`, immutable `attempt_id`, integer `seq`
starting at 1, RFC3339 `occurred_at`, stable `type`, positive `task_id`, Harness metadata
(`key`, `adapter_version`, `cli_version`), an object `payload`, and optional `raw_ref` containing a
`harness-events/` stream plus a 1-based line number.

The executable definition is `backend/app/core/harness_protocol.py`. It rejects hidden reasoning
keys; only an explicit `reasoning_summary.*` payload may be displayed.

## Stable types and order

The stable types are:

```text
run.started model.resolved
message.delta message.completed
reasoning_summary.delta reasoning_summary.completed
tool.started tool.completed context.compacted provider.retry
usage.updated usage.final
harness.completed harness.failed
delivery.started delivery.completed delivery.failed
worker.finalization
run.completed run.failed
diagnostic
```

Normal order is Harness translation, public delivery, `worker.finalization`, then the single Task
terminal. `harness.*` and `delivery.*` never determine Task status. The Task terminal must be the
last canonical record.

## Replay invariants

- `(attempt_id, seq)` is the idempotency key and sequences are contiguous from 1.
- `event_id` is unique. Attempt, task, Harness key, Adapter version, and CLI version cannot change
  within a replay.
- Exactly one `run.started`, Harness terminal, finalization, and Task terminal are required.
- A delivery record cannot precede the Harness terminal; finalization cannot precede it; after
  finalization, exactly the Task terminal must appear immediately and no other record is allowed.
- Missing init/Harness terminal/Task terminal, a gap, a duplicate terminal, or any record after the
  Task terminal is `protocol_error`.
- An unknown non-`run.*` type becomes `diagnostic` with its `raw_ref`; an unknown `run.*` type is
  rejected because success must never be guessed.

## Usage and result semantics

Portable token fields are `input_tokens`, `cached_input_tokens`, `output_tokens`, and
`reasoning_tokens`. Cost and currency are optional. Unavailable values are JSON `null`, never zero;
engine-specific auditable values remain in `engine_fields`.

The companion `codify.worker.result/v1` status is one of `completed`, `failed`, `cancelled`, or
`protocol_error`. A non-success result carries one failure kind from the Harness contract. Exit
code zero and `harness.completed` are evidence only; the final `run.*` record is authoritative.

Compatible readers ignore unknown object fields and unknown capability names. A schema change that
alters required fields, ordering, terminal meaning, or usage null semantics requires a new major
event schema.
