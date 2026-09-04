# Open-Harness V2 R4.3/R4.4 Live Host Evidence

**Date:** 2026-09-04

**Scope:** Current R4 candidate on `192.168.50.129`, mobile/desktop browser
interaction checks, four-Harness live smoke attempts, one live command-plane
run, and the resulting Host/Task runtime evidence.

This is candidate evidence, not an L5 go/no-go decision. R4.3–R4.6 remain
partially open until the complete acceptance, operational, security/release,
and independent review gates are signed.

## Candidate and validation boundary

- The Worker runtime image, Worker Kit `0.6.12`, and frozen CLI identities remain
  unchanged from the
  [R4.1/R4.2 candidate evidence](2026-09-03-open-harness-v2-r4.1-kit-boundary.md).
  The exact candidate identity in that document was superseded after the
  Codex Adapter fix below; its Kit-boundary evidence remains historical
  structural evidence.
- Commit `84ab6422` fixes an API-only omission: Issue detail serialization now
  includes `task_mode`, so valid `freeform` and `plan` tasks are not rendered as
  `Unknown`.
- Commit `8110afa0` fixes the Codex Adapter's model projection to read the
  OpenAI-compatible `OPENAI_MODEL` variable instead of the Anthropic-only
  variable. This is runtime code, so the old Profile-4 evidence was not reused:
  the Backend was rebuilt, Profile 4 was re-verified across all four Harnesses,
  and a new Bundle was bound before the post-fix live Task.
- Current post-fix identity: Profile 4 generation `72`; Worker Kit readiness
  `ready`; Runtime Bundle 163, digest
  `4aa9c7c894657aaeb1f075041d5221a250bca9ed648c12483f50e2c068ffa021`, archive
  SHA-256 `559e0de9a92ee7d76d7c006a2d74bb4b773e5438a6c6798cec43b3fc37de3539`.
  Its Adapter identities are Claude `1.0.1` /
  `8ba6df5bf27b03699eb4bdad343d2de1ff1e06f6a42a94b5287821782631a71c`, Codex
  `1.0.0` /
  `ec77bd633d7258c460133aeab70bbbdc02c0870dd138cb0c5dc310ef0468b21d`,
  OpenCode `2.0.0` /
  `a6bec9ac5df76a9de2824216628781ccaa46ad0efefd13a6ca1d677b9558887b`, and
  Pi `2.0.0` /
  `984154bf0bd473c26666877a0e13090cd2e58f0a7c37572d1df196ebf8150586`.
- The first post-deployment append attempt was rejected because the old
  Profile evidence still carried the prior Codex Adapter digest. No Task was
  bound from that attempt. This is recorded as fail-closed behavior; the
  re-verified Profile then accepted Task 368.
- Local validation for the change and current frontend candidate:

  | Check | Result |
  | --- | --- |
  | `backend/.venv/bin/python -m pytest backend/tests/unit/test_issues_api.py -q` | 39 passed |
  | `backend/.venv/bin/python -m pytest backend/tests/unit/test_harness_execution_policy.py backend/tests/unit/test_task_override_status.py -q` | 33 passed |
  | `backend/.venv/bin/python -m pytest backend/tests/mock_e2e/test_mattermost_e2e.py -q` | 96 passed |
  | `backend/.venv/bin/python -m pytest backend/tests/unit -q` | 3247 passed / 4 skipped / 96 subtests (pre-fix baseline) |
  | affected Bundle/Profile/Scheduler/notification/freeform regression set | 227 passed |
  | `backend/.venv/bin/python -m pytest backend/tests/unit/test_codex_harness_adapter.py -q` | 33 passed |
  | `make lint-backend` | passed |
  | `python3 -m py_compile deploy/worker-entrypoint/harness/adapters/codex_events.py` | passed |
  | `python3 scripts/harness-probes/v2/secret-scan.py` | passed, `findings=0` |
  | `git diff --check` | passed |
  | `frontend/npx vitest run` | 80 files / 1691 tests passed |
  | `frontend/npx vitest run src/features/tasks/useTaskLogStreams.spec.ts` | 3 tests passed; stale structured-source callback races covered |
  | `frontend/npx vitest run src/views/TaskView.spec.ts src/components/TaskFormDrawer.spec.ts` | 2 files / 234 tests passed |
  | `frontend/npm run build` | passed |

## Remote Host state

- Docker target: `192.168.50.129`, `linux/amd64`; execution mode remains
  `dual_canary`.
- `docker system df` after Task 368: Images `12.39GB` with `6.675GB`
  reclaimable; containers `5.098MB`; local volumes `1.639GB`; BuildKit cache
  `5.128GB`. The disk was not full, so no image or cache cleanup was performed.
- The Backend was rebuilt/restarted for commit `8110afa0` and returned healthy
  with image ID `sha256:d65c19ee4dff3398fba6917b2fe60b037b5835437df3bec6ea6f2c2eb4d17089`.
  The scheduler and long-lived GitLab services remained running.
- Profile 4's administrator Verify completed all four enabled Harness checks;
  the new Profile generation is `72`, and the readiness row is `ready`.

## Current operational snapshot

The read-only snapshot taken after Task 368 converged showed zero active Tasks
(`pending`, `queued`, or `running`) and zero `issue_execution_locks`. Tasks
357–366 and 368 each had exactly one canonical terminal event, contiguous
sequence numbers starting at 1, and zero matches for the repository's
GitLab/Provider token-shaped patterns in both canonical event JSON and raw-log
chunks. Raw-log storage was finalized for all eleven tasks: 3/2444 bytes,
4/2740 bytes, 5/2331 bytes, 3/3857 bytes, 4/2041 bytes, 4/3773 bytes,
4/2021 bytes, 3/3845 bytes, 6/6373 bytes, 5/2690 bytes, and 4/2683 bytes
respectively.

Task 358's one live `steer` command was `delivered` with one delivery attempt;
the other ten live smoke tasks had no control command. The remote database had
no Mattermost notification profile or delivery record, so live alert delivery
was not exercised and is not treated as passing evidence.

A fresh read-only integrity query scoped to the frozen Runtime Bundle 163 found
the three current-candidate attempts (Tasks 368–370): all three have exactly
one terminal event, 29 receipts total, and contiguous sequences beginning at
1, with no duplicate terminal event IDs. The full database also retains twelve
older attempt rows without `terminal_event_id`; only Tasks 166 and 181 have
non-terminal receipts, and both predate Bundle 163. These historical rows were
not rewritten or backfilled, so this check is a current-candidate pass rather
than a claim that every historical V2 row is complete.

## Real Task and command-plane evidence

Both tasks used Profile 4, the current V2 mounted-Kit composition, Pi, and a
fresh session. The prompts were read-only diagnostics and produced no code
changes.

| Task | Provider / result | Runtime evidence |
| ---: | --- | --- |
| 357 | Provider 5 `opencode-mimo` / `failed` | Pi `0.84.2`, 12s, 0 model tokens, canonical seq 1–9 ending `run.failed`, archive 5649 bytes; the real upstream response was HTTP 404 HTML and was not retried |
| 358 | Provider 7 `openrouter-free` / `completed` | Pi `0.84.2`, 1m51s, 118 input / 197 output tokens, canonical seq 1–78, archive 10189 bytes, 0 additions/deletions |

For Task 358, canonical receipts had 78 rows with `first_seq=1`,
`last_seq=78`, and 78 distinct sequence numbers. The stream included
`control.command.delivered`, `usage.final`, `delivery.completed`, and the final
`run.completed` event. The UI-sent steer command was delivered in one attempt:
created at `16:11:43.465 UTC`, native ACK/delivery at `16:11:44.699 UTC`
(approximately 1.234s).

The pre-fix live set below used the preceding Bundle identity. No failed task
was retried; the separate Provider selections distinguish Provider availability
from Harness behavior and remain valid for those boundaries, but #366 does not
prove the Codex model projection fixed by `8110afa0`.

| Task | Harness / Provider | Result and canonical evidence |
| ---: | --- | --- |
| 359 | OpenCode / Provider 7 `openrouter-free` | `completed`; CLI `1.18.19`, Adapter `2.0.0`, canonical seq 1–34 with 34 distinct receipts, archive 8783 bytes, raw-log 5 chunks / 2331 bytes |
| 360 | Claude / Provider 3 `opencode-minimax` | `failed`; CLI `2.1.153`, Adapter `1.0.1`, canonical seq 1–7 with terminal `run.failed(failure.kind=rate_limited)`, archive 4095 bytes, raw-log 3 chunks / 3857 bytes; upstream reported HTTP 429 monthly usage limit |
| 361 | Codex / Provider 9 `openrouter-glm52-responses` | `failed`; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–8 with terminal `run.failed(failure.kind=rate_limited)`, archive 2915 bytes, raw-log 4 chunks / 2041 bytes; upstream exhausted retries with HTTP 429 |
| 362 | Claude / Provider 8 `openrouter-glm52-anthropic` | `failed`; CLI `2.1.153`, Adapter `1.0.1`, canonical seq 1–7 with terminal `run.failed(failure.kind=engine_error)`, archive 4032 bytes, raw-log 4 chunks / 3773 bytes; the selected model was unavailable to the Provider |
| 363 | Codex / Provider 4 `opencode-luna` | `failed`; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–7 with terminal `run.failed(failure.kind=rate_limited)`, archive 2743 bytes, raw-log 4 chunks / 2021 bytes; upstream exhausted retries with HTTP 429 |
| 364 | Claude / Provider 6 `opencode-pi` | `failed`; CLI `2.1.153`, Adapter `1.0.1`, canonical seq 1–7 with terminal `run.failed(failure.kind=rate_limited)`, archive 4084 bytes, raw-log 3 chunks / 3845 bytes; upstream reported HTTP 429 monthly usage limit |
| 365 | Claude / Provider 11 `openrouter-minimax-anthropic` | `completed`; CLI `2.1.153`, Adapter `1.0.1`, canonical seq 1–15, archive 5815 bytes, raw-log 6 chunks / 6373 bytes, usage 2608 input / 272 output, 0 changes |
| 366 | Codex / Provider 12 `openrouter-minimax-responses` | `completed`; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–14, archive 3908 bytes, raw-log 5 chunks / 2690 bytes, usage 20986 input / 123 output, 0 changes |
| 368 | Codex / Provider 12 `openrouter-minimax-responses` | `completed` on current Bundle 163; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–14 with 14 distinct receipts, terminal `run.completed`, archive 4020 bytes, raw-log 4 chunks / 2683 bytes, usage 21017 input / 177 output, 0 changes; `model.resolved` and Task/UI execution model both `minimax/minimax-m3:free` |
| 369 | Codex / Provider 12 `openrouter-minimax-responses` | `failed` on current Bundle 163; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–8 with terminal `run.failed(failure.kind=rate_limited)`, archive 3085 bytes, raw-log 4 chunks / 2486 bytes; the controlled backend-restart probe reached the upstream retry limit with HTTP 429 before the requested delay |
| 370 | Codex / Provider 4 `opencode-luna` | `failed` on current Bundle 163; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–7 with terminal `run.failed(failure.kind=rate_limited)`, archive 2935 bytes, raw-log 4 chunks / 2503 bytes; the second controlled backend-restart probe reached the upstream retry limit with HTTP 429 before the requested delay |

Together with Tasks 357/358, the live set now covers Pi, OpenCode, Claude, and
Codex across multiple compatible Provider selections. The
Claude/Codex non-success outcomes are bounded upstream Provider availability
failures, not success claims; they remain useful evidence that the failure
classifier and single terminal path reject rate-limited or unavailable-model
execution.

Tasks 369 and 370 were two isolated probes in which only the remote
`codify-backend` container was restarted while the task page remained open. The
frontend stayed on Issue #99, but both persisted terminal payloads identify the
failure as upstream `rate_limited`; neither reached the requested long-running
read-only command. They therefore do not prove worker continuation or SSE
disconnect/reconnect continuity and are retained as negative, inconclusive
evidence only. A further real-Provider attempt was not submitted because the
selected external Provider destination requires explicit authorization for
repository-context transfer.

## Browser interaction evidence

The deployed frontend was checked in Chrome against `http://192.168.50.129:8880`
at a physical `390x844` viewport (the extension reported a CSS viewport of
`433x938` at `devicePixelRatio≈0.9`).

- Issue 98 rendered its long title, long read-only prompt, status actions, and
  task history without document horizontal overflow.
- The Create Issue page allowed project search/selection, branch selection, the
  “use starting branch” shortcut, and description-editor focus. The project
  search is outside the `project_id` validation field, and the bottom action
  area was reachable and visible after scrolling without horizontal overflow.
  No Issue was submitted from this page.
- On the same Create Issue form, the default Harness selector successfully
  switched `Claude → Codex → OpenCode → Pi` and was restored to Pi. This was a
  form-level selection check; no additional Issue was submitted for that check.
- The Create Task drawer automatically opened the execution environment on
  entering the create form. The current issue correctly kept its Pi Harness
  fixed while showing the four-Harness verification status rows.
- Task 358 entered `running`, showed live event progress and an enabled
  steering panel. Sending a read-only `pwd` steer command changed the visible
  command record from queued to delivered. Reloading the Task detail page while
  it was running preserved the event history and command record; the page then
  transitioned to the completed state with usage and terminal evidence.
- After the backend deployment, the Issue current-execution card showed
  `模式 · 自由模式` for Task 358 instead of `模式 · Unknown`.
- Task detail pages for #359–#361 rendered the OpenCode completion and the
  Claude/Codex `失败原因 · rate_limited` outcomes, with the run-archive and
  raw-log controls visible. No retry action was clicked for the known upstream
  429 failures.
- Task detail pages for #362–#364 rendered the selected Harness and terminal
  failure state. No retry action was clicked for these separate Provider
  probes.
- Task detail pages for #365/#366 rendered completed Claude/Codex outcomes,
  the selected alternate Provider and fresh-session context, zero-change
  result, usage, and the run-archive control. No retry action was clicked.
- Task #368 rendered the post-fix Codex completion with the selected Provider,
  fresh-session context, zero-change result, `执行模型: minimax/minimax-m3:free`,
  usage, and the run-archive control. The model was visible both during the
  live run and after completion.
- Tasks #369 and #370 were controlled backend-only restart probes while the
  Issue page remained open. The page stayed mounted, but both tasks ended in
  bounded upstream `rate_limited` failures before the requested delay; this is
  not a successful disconnect/reconnect result.

After the restart probes, the frontend structured-log lifecycle was tightened
at the source level: `useTaskLogStreams` now checks EventSource identity in both
the `error` handler and the structured `done` callback before closing the
current stream or reporting completion. The same identity check now also
rejects stale `batch` and `update` callbacks from the old source before they
enter the shared pending queue or merge into current task logs. Three focused
regression tests cover the stale-error, stale-done, and stale-batch/update
races, and the full frontend suite passed 80 files / 1691 tests; `npm run build` also passed with only the existing
large-chunk warning. This is source/test evidence only: it does not turn the
inconclusive #369/#370 probes into a valid real network disconnect/reconnect
acceptance result, and it did not change the frozen Bundle/Provider identity.

After the current frontend source was committed as `c76482a1`, the target Host
was redeployed through the `remote` Docker context with an nginx-only
rebuild/recreate. `docker compose ps` showed
`codify-nginx` started, while `codify-backend` remained healthy and
`codify-scheduler`/Postgres were not recreated; the public frontend endpoint
returned HTTP 200. This verifies the static frontend deployment path, not a
live authenticated SSE reconnect. The host filesystem was at 94% usage with
4.2GB available; it was not full, so no Codify image or cache cleanup was
performed.

## R4.3/R4.4 boundary after this run

### R4.3 — partial evidence, not signed

The run covers long-text layout, mobile task/create navigation, editor focus,
bottom-action reachability, form-level and existing-Issue Harness selection, a
real running/completed transition, command ACK wording, reload continuity, and
the post-fix Codex execution-model display.
It does not yet sign the full gate because:

- Chrome's desktop extension viewport cannot prove behavior with a real mobile
  soft keyboard, IME resize, or notched-device safe-area inset. The Task drawer
  footer retains the `env(safe-area-inset-bottom)` rule, but this run observed a
  zero computed inset in the emulated viewport.
- Reload continuity is a browser-level reconnect spot-check, not a controlled
  network disconnect/reconnect test.
- The two backend-restart probes (#369/#370) are also inconclusive: their
  persisted `run.failed` payloads are upstream `rate_limited`, and no probe
  reached the delayed command needed to establish event-stream continuity.
- The structured-log client now rejects stale `error`/`done`/`batch`/`update`
  callbacks from a previous EventSource after reconnect; the focused race
  tests and the full frontend suite pass. This closes a source-level lifecycle
  race, but not the required real Host network disconnect/reconnect proof.
- The V1 read-only source boundary was also rechecked without changing the
  Host mode: the backend `v2_only`/legacy-contract selection passed 9 tests,
  and the TaskView legacy read-only group passed 4 tests. These checks cover
  pending/failed/running rendering and API rejection semantics, but the Host
  was not switched to `v2_only` and therefore still lacks L5 runtime evidence.
- The live Task #358 remained Pi-locked. On existing Issue #99, the drawer
  kept the current OpenCode Harness and displayed the continuation lock hint;
  enabling “use new session” allowed a temporary switch to Claude and the
  form was restored to OpenCode without submitting a task. `v2_only` V1
  read-only presentation was not exercised on the Host; the source suite does
  cover pending/failed/running V1 read-only rendering, including a 390px case.
  The Host remains `dual_canary`.

### R4.4 — partial evidence, not signed

Tasks 357–366 and 368–370 plus the prior five-task warm-start cohort provide all
four Harness selections with real success samples for each Harness and bounded
upstream failure classification,
command latency, usage, canonical terminal, archive, raw-log finalization,
delivery samples, and the current queue/lock/secret-scan snapshot. The local
Mattermost mock E2E suite also passed 96 tests, covering profile CRUD, config
validation, connection-test outcomes, event filtering, and delivery result
recording without contacting a real notification service. A complete
Harness/Profile/Host operational review of alert behavior and a formal
zero-P0/P1 sign-off are still required; no notification profile was configured
on this development Host for a live alert delivery test.

The current Bundle 163 receipt recheck above supports the zero-duplicate-terminal
and zero-sequence-gap claim for the frozen candidate only. The pre-Bundle-163
historical rows remain an evidence boundary and are not silently counted as a
current-candidate pass.

R4.5 security/release sign-off and R4.6 independent hard-cut go/no-go remain
open. No R5 maintenance window or `v2_only` cutover was performed.
