# Open-Harness V2 Profile 4 generation 78 four-Harness smoke

**Date:** 2026-09-05

**Host:** `192.168.50.129` development environment

**Scope:** Normal administrator Verify of the current Profile 4, followed by
four read-only real-provider Tasks using the frozen legal Harness×protocol
matrix. This is supplemental current-candidate evidence; it is not an R4
go/no-go decision and is not added to the frozen Task-ID 380–394 integrity
cohort.

## Candidate identity and readiness window

The authenticated Dashboard was used to run the normal Profile 4 runtime
verification. The Verify completed successfully and changed the Profile
identity generation from `77` to `78` without changing the Kit or selected
Worker image:

| Item | Result |
| --- | --- |
| Profile | `4`, `v2-canary-0.6.11-four-harness`, Kit `0.6.14`, `linux/amd64` |
| Profile identity | generation `78`; `verified_at=2026-09-05 12:02:48.114828` (target DB time) |
| Worker image | `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b` |
| Mounted Kit | `/opt/codify/worker-kits/0.6.14-linux-amd64-d461d040694b` |
| Kit manifest | `d461d040694b20b88944a88de47b5ad78188f91d74d528421cdef44b68274035` |
| Readiness | fingerprint `b987eed28cfee21dd5dc5ad050c3ab1670ec4a9ce5881e3e8767c62da294203f`, `ready`, `check_generation=2` |
| Readiness window | checked `2026-09-05 12:03:31.418387`, `ready_until=2026-09-05 12:18:31.417926` |

The `ready` result above is valid only within that recorded TTL window. Once
`ready_until` passes, the frozen contract derives the row as `unknown`; this
evidence does not claim that readiness remains current after expiry. No
migration 078, `v2_only` cutover, or mobile-device acceptance was executed.

## Four-Harness real-provider matrix

All four Tasks were created through the authenticated Issue #99 flow with the
same read-only prompt, `plan`/analysis mode, fresh session, Profile 4, Kit
`0.6.14`, and zero repository changes. Every Task ended with
`run.completed` and `control_state=closed`.

| Task | Harness / Provider / protocol | Bundle / selected CLI | Result and persistence | Archive / delivery |
| ---: | --- | --- | --- | --- |
| 425 | Pi / Provider 12 `openrouter-minimax-responses` / `minimax/minimax-m3:free` / `openai_responses` | Bundle 181, `f970c87e0175c2b78c7ba494c18d6e1fb9fdabf68b68c9eeb953ecd6bdfdb8e7`; Adapter `2.1.0`, CLI `0.84.2` | `139/1581` input/output tokens, `total_changes=0`; 813 receipts, unique IDs, seq 1–813; raw logs 4 chunks / 3039 bytes | 67435 bytes, SHA-256 `082443dbcf2964e0e31c9d2fdb725054c81cebc5106870ed6453a97ecf1d8087`; Mattermost delivery `18`, `task_completed/success`; summary validation `ok=false` because the model emitted invalid Mermaid after two repair attempts |
| 426 | OpenCode / Provider 12 `openrouter-minimax-responses` / `minimax/minimax-m3:free` / `openai_responses` | Bundle 182, `f2382aedd3f7d022dc63a6c2c9be3b3831a1b6d54990d446a738c858e334c892`; Adapter `2.0.0`, CLI `1.18.19` | `161/1629` input/output tokens, `total_changes=0`; 118 receipts, unique IDs, seq 1–118; raw logs 5 chunks / 2716 bytes | 31265 bytes, SHA-256 `1d35919b421543e853602bdeeb60c53392b15801b4afeb454f41790d41fb515d`; Mattermost delivery `19`, `task_completed/success`; no independent `delivery_summary` payload was written |
| 427 | Claude / Provider 6 `opencode-pi` / `deepseek-v4-flash` / `anthropic_messages` | Bundle 183, `67d383486c63bcbefc6a68c7060bcfde114de820954b9b23d24e97b81dba64a5`; Adapter `1.0.1`, CLI `2.1.153` | `5043/9046` input/output tokens, `total_changes=0`; 49 receipts, unique IDs, seq 1–49; raw logs 17 chunks / 48237 bytes | 43601 bytes, SHA-256 `ba5b3a07901dc678c3929f974e86d021e692468df7b3975d258ec8737b65e3ce`; Mattermost delivery `20`, `task_completed/success`; summary validation `ok=true`, 2 diagrams, 0 repairs |
| 428 | Codex / Provider 12 `openrouter-minimax-responses` / `minimax/minimax-m3:free` / `openai_responses` | Bundle 184, `d41b5bf957cb274dda82c402ae9b76b70a320de2ec910b1ce16dc4cc51bc992f`; Adapter `1.0.0`, CLI `0.146.0` | `34174/1538` input/output tokens, `total_changes=0`; 20 receipts, unique IDs, seq 1–20; raw logs 5 chunks / 2716 bytes | 14305 bytes, SHA-256 `79569ce2d9e713c2e921edd76dea8c37b9254196497c59253f559a9cea084f80`; Mattermost delivery `21`, `task_completed/success`; summary validation `ok=true`, 2 diagrams, 0 repairs |

The Task 425 Mermaid problem is a delivery-summary content-validation defect,
not a Worker execution failure: the Task, receipt stream, archive, finalization,
and notification all succeeded. Task 426 likewise completed and notified
successfully, but did not produce an independent delivery-summary validation
payload. These two boundaries are recorded explicitly rather than being
reported as an all-green summary-validation result.

## Canonical archive, protocol, and secret checks

For each runtime archive, the canonical `event.jsonl` was parsed remotely:

| Task | Records / parse errors | Event IDs | Sequence | Terminal records |
| ---: | ---: | ---: | --- | --- |
| 425 | 813 / 0 | 813 unique | 1–813 contiguous | one each of `harness.completed`, `worker.finalization`, `run.completed` |
| 426 | 118 / 0 | 118 unique | 1–118 contiguous | one each of `harness.completed`, `worker.finalization`, `run.completed` |
| 427 | 49 / 0 | 49 unique | 1–49 contiguous | one each of `harness.completed`, `worker.finalization`, `run.completed` |
| 428 | 20 / 0 | 20 unique | 1–20 contiguous | one each of `harness.completed`, `worker.finalization`, `run.completed` |

Targeted scans of all four archives returned zero matches for
`glpat-*`, `sk-ant-*`, `ANTHROPIC_API_KEY=`, and `OPENAI_API_KEY=`. Raw-log
protocol/redaction checks matched the legal matrix: Tasks 425, 426, and 428
contained `openai_responses` and no `anthropic_messages`; Task 427 contained
`anthropic_messages` and no `openai_responses`; all four contained `[TOKEN]`
redaction and no `glpat` match.

## Served UI and Host convergence

The authenticated served desktop pages `/tasks/425`, `/tasks/426`,
`/tasks/427`, and `/tasks/428` each displayed the completed state, analysis
mode, fresh session, Profile 4/Worker context, selected Harness, `+0/-0`,
event stream/raw-log controls, and execution statistics. The pages showed Pi,
OpenCode, Claude, and Codex respectively; the raw-log views exposed the
corresponding legal protocol and token-redaction boundary.

At the post-run Host check, Backend, Scheduler, nginx, Mattermost
`10.9.1`, Mattermost Postgres, GitLab, Redis, and Codify Postgres were healthy;
there were no pending/queued/running Tasks and no Issue execution locks. The
database remained at `077_v2_worker_kit_identity`, with
`HARNESS_EXECUTION_MODE=dual_canary`, `AUTO_MIGRATE=false`, and
`FRONTEND_URL=http://192.168.50.129:8880`. The root filesystem had about
`2.0GB` available (`97%` used), Docker reported no BuildKit cache and about
`4.08GB` reclaimable images. The disk-full cleanup trigger was not reached, so
no new cleanup was performed; protected services, volumes, and the active
unknown `quirky_allen` Worker were retained.

This evidence strengthens current-generation L3/L4 and served desktop L5
coverage. It does not close R4.3, R4.4, R4.5, or R4.6; it does not authorize
R5/L6, migration 078, or `v2_only`; and it does not claim real mobile
keyboard/IME/notch/gesture-area acceptance, which remains deferred by the
user.
