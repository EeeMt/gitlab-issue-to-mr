# Worker Harness Adapter contract v1

`codify.worker.harness/v1` separates engine behavior from Codify orchestration. The public runner
does not branch on a Harness name; it acts on Adapter metadata and capabilities and emits
`codify.worker.event/v1`.

## Operations

| Operation | Required result |
|---|---|
| `metadata` | key, Adapter version/digest, supported CLI range, capabilities, Provider protocols |
| `verify_runtime` | verified binary path/version/digest and hermetic config boundary |
| `detect_capabilities` | runtime features observed from startup evidence; unknown names ignored |
| `prepare_config` | task-local config paths and credential references, never secret values in output |
| `build_command` | argv and redacted display argv for new/resume execution |
| `materialize_skills` | immutable task Skills copied outside the Git worktree to a Harness-owned path |
| `stream_events` | raw record to canonical type/payload/raw reference; no envelope construction |
| `normalize_result` | canonical result fields, usage, session, model, failure, warnings |
| `terminate` | TERM/grace/KILL of the complete process group with evidence |
| `run_text` | optional sessionless one-shot text helper; deterministic fallback if absent |

Inputs contain the frozen Task Snapshot, Runtime Bundle manifest, request, workspace identity,
Endpoint fingerprint, authentication-domain identifier, and artifact paths. Outputs cannot mutate
the Snapshot or repository.

## Capabilities

Capabilities are typed values such as `resume`, `task_skills`, `max_turns`, `usage_tokens`,
`usage_cost`, `run_text`, `codegraph`, and `sandbox_mode`. Public code decides allow, reject, or
explicit degrade from capabilities. A request for an unsupported safety boundary is rejected;
optional observability such as cost produces a warning and `null`.

Claude v1 declares resume, task Skills, max turns, token/cost usage, run_text, and CodeGraph. Codex
v1 is probed for resume, task Skills, usage, Responses Provider configuration, and sandbox/approval;
Phase 0 does not enable it in production.

Version ranges are a fast startup check. Observed startup features remain authoritative. Runtime
Bundle manifest Adapter versions and file digests are execution truth; the Worker Kit only declares
compatible contract/event ranges and CLI runtime capabilities.

The Task stores both the archive digest and the digest of the embedded manifest. Before executing
bundle code, the stable Kit launcher (and the baked-image compatibility entrypoint) verifies the
manifest digest, contract/event compatibility, frozen Adapter version, and every manifested file's
size and SHA-256. A mismatch fails before the Adapter is sourced. The Kit artifact removes the
Runtime Bundle Adapter manifest so it cannot become a second version truth.

Phase 1 deliberately uses a hard release boundary. A Task without an immutable Runtime Bundle is
historical read-only data: execution and retry fail closed, and the launcher never falls back to
the scripts embedded in the Worker Kit. Kit-local scripts may run only for the operator's
`--verify` preflight before profiles are enabled.

## Failure taxonomy

Adapters normalize failures to `configuration_error`, `authentication_error`, `rate_limited`,
`sandbox_error`, `protocol_error`, `timeout`, `cancelled`, or `engine_error`. They do not turn an
unknown record, missing terminal, unavailable sandbox, or delivery failure into success.

## Session compatibility domain

Session lookup uses at least:

```text
issue_id + harness_key + session_namespace
```

`session_namespace` is a digest of Harness key, Endpoint fingerprint, authentication domain,
workspace identity, and Adapter state major version. A session ID is opaque and is never converted
or reused across domains. Invalid resume fails deterministically unless the Adapter contract for the
frozen version explicitly records a safe new-session fallback; the v1 default is fail closed.
Claude Adapter `1.0.0` is the one documented compatibility exception: it preserves the pre-Adapter
resume-not-found retry as a fresh session, retains the failed resume evidence in the same attempt,
emits `diagnostic(code=resume_fallback)`, and returns the newly resolved opaque session ID. Other
Adapters cannot inherit that behavior implicitly.

## Security and process rules

- A task uses an isolated Harness home and explicit configuration. Operator or Host user config is
  not inherited.
- Unattended execution cannot wait for approval or silently broaden permissions when sandboxing is
  unavailable.
- Long-lived model secrets should be mediated by a proxy/Broker or task token. Legacy container
  environment delivery is a documented transition, not a safe default for untrusted repositories.
- Raw lines are sanitized before archival. Hidden reasoning is not canonicalized.
- The public runner owns process groups, timeout, cancellation, TERM grace, KILL, delivery,
  finalization, and the only Task terminal event.

## Canonical result

`codify.worker.result/v1` contains status/success, result text, Harness/Adapter/CLI identity, session,
resolved model, normalized usage, optional failure, and capability warnings. Unknown values are
`null`. A Harness result is not a Task result: public delivery and finalization still run before the
single authoritative `run.completed` or `run.failed` event.
