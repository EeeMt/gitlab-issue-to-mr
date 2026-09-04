# Open-Harness V2 R4.3/R4.4 Live Host Evidence

**Date:** 2026-09-04

**Scope:** Current R4 candidate on `192.168.50.129`, mobile/desktop browser
interaction checks, four-Harness live smoke attempts, one live command-plane
run, one stable-state cancellation, one controlled nginx-only
disconnect/reconnect, and the resulting Host/Task runtime evidence.

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
- Commit `8110afa0` fixed the Codex Adapter's model projection to read the
  OpenAI-compatible `OPENAI_MODEL` variable instead of the Anthropic-only
  variable. Commit `810f9fcb` fixes the Pi Adapter's startup-session projection:
  when Pi emits an unsolicited `get_state` before the owner's `new_session`
  acknowledgement, `model.resolved` is deferred until the negotiated active
  session is known. Direct/no-handshake streams remain supported. Both changes
  are runtime code, so the prior Profile-4 evidence was not reused: the Backend
  was rebuilt, Profile 4 was re-verified across all four Harnesses, and new
  content-addressed Bundles were bound before the current live Tasks.
- Current post-fix identity: Profile 4 generation `73`; Worker Kit `0.6.12`
  readiness `ready`; Worker Image ID
  `sha256:b07ac48b129c35876c044079f8e9cd7aa7558dbb0ade2e50e856d4ab980f5e71`,
  repo reference
  `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`.
  The selected-Harness Bundle variants are:

  | Bundle | Selected Harness | Bundle digest | Archive SHA-256 |
  | ---: | --- | --- | --- |
  | 166 | Pi | `c9e2365944e6abc6d3b2776ca8021c29b2beadc7fd4d4463fca348cc67e01acb` | `145112a5a53b7c31cf3b0ae45cbdbb375604e70941663decf879bb4775f67ce8` |
  | 167 | Claude | `2bb41470c068be1d3a15bbd4c066ad9ceac20b8d61f3cea9f37e9bb81e883f69` | `fc5dbaa35b724f1b6589b56c17727cf8831290683557c864d9240e03758410ed` |
  | 168 | OpenCode | `c1da73de15ad9eb8bd50875edf28fc820c46c548ef78739027c95009ea7c3edf` | `11645205edb5ea058a419457e9b4c96def1119c2d06fc7495480c04a02cf8006` |
  | 169 | Codex | `1ed47a89c3f1936ba8a59c8b6560ca8d0318e15da03db7217f67b5af106e0410` | `8441ba42badd6a109896eb7a3a9c21d79989e90c2455c5fa2f3010b1523159d4` |

  All four Bundles are 552,960 bytes. Their selected Adapter identities are
  Pi `2.0.0` / `c317284b37970e87b0ac41d4bb364f18dc7a501615aacd5375f7afddbe543080`,
  Claude `1.0.1` /
  `8ba6df5bf27b03699eb4bdad343d2de1ff1e06f6a42a94b5287821782631a71c`,
  OpenCode `2.0.0` /
  `a6bec9ac5df76a9de2824216628781ccaa46ad0efefd13a6ca1d677b9558887b`, and
  Codex `1.0.0` /
  `ec77bd633d7258c460133aeab70bbbdc02c0870dd138cb0c5dc310ef0468b21d`.
  The selected CLI identities remain Pi `0.84.2` /
  `9a2d20fab3caacbe3517d91e59d495ccc49fd4b51a1a72dcec6e8c1f4b7d6ab2`,
  Claude `2.1.153` /
  `214f603f31942162dac9a65f18d43b3ac646ae215240fad481c4aad6c60f2e38`,
  OpenCode `1.18.19` /
  `fd4cfd76ca65a706d0138886dd23094dd07e35460080024b1467baaf32dcee2e`, and
  Codex `0.146.0` /
  `2e863156ed35ecc5253b1e2f907a9143077b9f7cb51942070c61996471ff6e04`.
- Bundle 165 was the Pi-specific pre-`810f9fcb` diagnostic. Task 373 completed
  on it, but its `model.resolved` session differed from both
  `harness.completed` and the Task output session; it is retained as
  superseded defect evidence and is excluded from the current candidate.
- Runtime Bundle identity is selected-Harness scoped. As with the earlier
  Bundle 163/164 pair, the generation-73 variants have identical controlled
  files, Worker Image identity, Worker Kit identity, and all four Adapter
  identities; only selected-Harness evidence and the content-addressed source
  digest differ. This is an expected scoped identity variant, not runtime
  Image/Kit/Adapter drift.
- The first post-`8110afa0` append attempt was rejected because the old Profile
  evidence still carried the prior Codex Adapter digest. No Task was bound from
  that attempt. This is recorded as fail-closed behavior; the re-verified
  generation-72 Profile then accepted Task 368. The later Pi fix generated the
  current generation-73 Profile and Bundles recorded above.
- Local validation for the change and current frontend candidate:

  | Check | Result |
  | --- | --- |
  | `backend/.venv/bin/python -m pytest backend/tests/unit/test_issues_api.py -q` | 39 passed |
  | `backend/.venv/bin/python -m pytest backend/tests/unit/test_harness_execution_policy.py backend/tests/unit/test_task_override_status.py -q` | 33 passed |
  | `backend/.venv/bin/python -m pytest backend/tests/mock_e2e/test_mattermost_e2e.py -q` | 96 passed |
  | `backend/.venv/bin/python -m pytest backend/tests/unit -q` | 3247 passed / 4 skipped / 96 subtests (pre-fix baseline) |
  | affected Bundle/Profile/Scheduler/notification/freeform regression set | 227 passed |
  | `backend/.venv/bin/python -m pytest backend/tests/unit/test_codex_harness_adapter.py -q` | 33 passed |
  | `backend/.venv/bin/python -m pytest backend/tests/unit/test_pi_harness_adapter.py -q` | 54 passed; covers active-session projection after startup `get_state` |
  | `backend/.venv/bin/python -m ruff check deploy/worker-entrypoint/harness/adapters/pi_events.py backend/tests/unit/test_pi_harness_adapter.py` | passed |
  | `make lint-backend` | passed |
  | `python3 -m py_compile deploy/worker-entrypoint/harness/adapters/codex_events.py` | passed |
  | `python3 scripts/harness-probes/v2/secret-scan.py` | passed, `findings=0` |
  | `git diff --check` | passed |
  | `frontend/npx vitest run` | 80 files / 1692 tests passed |
  | `frontend/npx vitest run src/features/tasks/useTaskLogStreams.spec.ts` | 3 tests passed; stale structured-source callback races covered |
  | `frontend/npx vitest run src/views/TaskView.spec.ts src/components/TaskFormDrawer.spec.ts` | 2 files / 234 tests passed |
  | `frontend/npm run build` | passed; includes the safe-area viewport metadata |

## Remote Host state

- Docker target: `192.168.50.129`, `linux/amd64`; execution mode remains
  `dual_canary`.
- After the generation-73 live Tasks, the Docker snapshot reports Images
  `12.41GB` with `6.706GB` reclaimable (81 total / 8 active), containers
  `7.123MB`, local volumes `1.641GB`, and BuildKit cache `6.526GB`. The
  filesystem is `61GB` total / `57GB` used / `4.1GB` available (`94%`), with
  `19%` inode use. It is not full, so no image, volume, or BuildKit cleanup
  was performed.
- The target Backend image was re-inspected at `2026-09-04T15:35:05Z` and
  returned healthy with image ID
  `sha256:9584b350d54afbbeae42847c0e52554570eb1a7535b60c4614823d2d09da31d1`.
  The image has no Git revision OCI label. Its `/app` backend files match the
  `9bbcf43` source, while `runtime-source` contains the active-session Pi
  projection patch used by Task 374 but not represented by one committed tree
  (the Runtime source `pi_events.py` SHA-256 is
  `2bec6d963f50d6d1eb58e88f7bd6c850320169d93fc94a567a6e9494a822b56b`).
  Therefore Task 374 is valid behavior evidence and Bundles 166–169 remain
  immutable by digest, but this Host image is a mixed, non-reproducible
  composition and must not be treated as a clean release build. The
  scheduler, nginx, Postgres, and long-lived GitLab services remained
  healthy/running; Scheduler health also reports `dual_canary`.
- Profile 4's administrator Verify completed all four enabled Harness checks;
  the current Profile generation is `73`, and the readiness row is `ready`.

- The frontend-only commit `a6be3f8b` opts the served app into
  `viewport-fit=cover`, applies the top safe-area inset to the mobile shell and
  drawer header, and reserves the bottom inset in the navigation drawer body.
  It does not change the frozen Bundle, Provider, Harness, or event contract.
- During Task 371, only `codify-nginx` was restarted at
  `2026-09-04T13:23:35.570939Z`. `codify-backend` remained running from
  `2026-09-03T17:53:43.412872Z`; `codify-scheduler` and Postgres were not
  restarted. The Worker continued through the frontend-entrypoint
  interruption and completed the task.

## Current operational snapshot

The read-only snapshot taken after Task 378 converged showed zero active Tasks
(`pending`, `queued`, or `running`) and zero `issue_execution_locks`; the
database contained 347 Tasks. Tasks 374–378 each had exactly one canonical
terminal event, contiguous sequence numbers starting at 1, and finalized
raw-log storage. Their raw-log totals were 5/2701 bytes, 7/6117 bytes,
5/2711 bytes, 4/2420 bytes, and 4/2426 bytes respectively. The five current
generation-73 attempts contain 111 receipts and 111 distinct event IDs; the
task and Harness terminal counts are both five. Token-shaped secret scanning
for the complete current cohort remains zero as recorded below.

Task 358's one live `steer` command was `delivered` with one delivery attempt;
the other recorded smoke tasks had no control command. The remote database had
no Mattermost notification profile or delivery record, so live alert delivery
was not exercised and is not treated as passing evidence.

A fresh read-only integrity query scoped to the generation-73 Runtime Bundles
166–169 found the five current-candidate attempts (Tasks 374–378): all five
have exactly one terminal event, 111 receipts total, and contiguous sequences
beginning at 1, with no duplicate terminal event IDs. The full database still
retains twelve older attempt rows without `terminal_event_id`; only Tasks 166
and 181 have non-terminal receipts, and both predate Bundle 163. These
historical rows were not rewritten or backfilled, so this check is a
current-candidate pass rather than a claim that every historical V2 row is
complete.

A second read-only query over the recorded live cohort (Tasks 357–366 and
368–370, thirteen tasks/attempts) found zero task-status/terminal-type
mismatches, zero attempts with multiple terminal receipts, zero sequence gaps,
and zero secret-like matches in canonical event JSON or raw-log chunks.

After Task 371 converged, the expanded fourteen-task cohort (Tasks 357–366 and
368–371) still had zero task-status/terminal-type mismatches, zero attempts with
multiple terminal receipts, zero sequence gaps, and zero secret-like matches in
canonical event JSON or raw-log chunks. All fourteen tasks had finalized raw
logs; the target Host had zero active Tasks and zero Issue execution locks.

Task 372 then expanded the live cohort with a stable-state OpenCode
cancellation. The operator cancelled only after the Worker had persisted the
first `pwd` completion and `tool.started(Bash: sleep 180)`. Its 15 contiguous
receipts ended with `harness.failed(failure.kind=cancelled)`,
`worker.finalization(exit_code=143)`, and the unique Task terminal
`run.failed(status=cancelled, failure.kind=cancelled, exit_code=143)`;
`cancel_requested_at` was persisted, raw logs were finalized, the 6,867-byte
runtime archive was retained, and the Worker container was removed. Under the
frozen status/terminal mapping, this is a cancellation match rather than a
terminal mismatch; the database `error_message` (`MessageAbortedError: Aborted`)
does not override the canonical cancellation payload.

## Real Task and command-plane evidence

The current additions used Profile 4, the generation-73 V2 mounted-Kit
composition, the selected Harness/Provider combinations shown below, and a
fresh session. All prompts were read-only diagnostics and produced no code
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
| 368 | Codex / Provider 12 `openrouter-minimax-responses` | `completed` on preceding generation-72 Bundle 163; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–14 with 14 distinct receipts, terminal `run.completed`, archive 4020 bytes, raw-log 4 chunks / 2683 bytes, usage 21017 input / 177 output, 0 changes; `model.resolved` and Task/UI execution model both `minimax/minimax-m3:free` |
| 369 | Codex / Provider 12 `openrouter-minimax-responses` | `failed` on preceding generation-72 Bundle 163; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–8 with terminal `run.failed(failure.kind=rate_limited)`, archive 3085 bytes, raw-log 4 chunks / 2486 bytes; the controlled backend-restart probe reached the upstream retry limit with HTTP 429 before the requested delay |
| 370 | Codex / Provider 4 `opencode-luna` | `failed` on preceding generation-72 Bundle 163; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–7 with terminal `run.failed(failure.kind=rate_limited)`, archive 2935 bytes, raw-log 4 chunks / 2503 bytes; the second controlled backend-restart probe reached the upstream retry limit with HTTP 429 before the requested delay |
| 371 | OpenCode / Provider 7 `openrouter-free` | `completed` on preceding generation-72 OpenCode-specific Bundle 164; CLI `1.18.19`, Adapter `2.0.0`, fresh session, three read-only Bash commands (`pwd`, `git status --short`, `sleep 180`) all exited `0`, canonical seq 1–26 with 26 distinct receipts and terminal `run.completed`, archive 8719 bytes, raw-log 5 chunks / 2782 bytes, usage 51 input / 7 output, 0 changes |
| 372 | OpenCode / Provider 7 `openrouter-free` | `cancelled` on preceding generation-72 OpenCode-specific Bundle 164; CLI `1.18.19`, Adapter `2.0.0`, fresh session, operator cancelled after `tool.started(Bash: sleep 180)`, canonical seq 1–15 with the chain `harness.failed(cancelled)` → `worker.finalization(exit_code=143)` → unique `run.failed(status=cancelled, failure.kind=cancelled)`, archive 6867 bytes, raw-log 4 chunks / 2532 bytes, 0 usage / 0 changes, container cleaned |
| 373 | Pi / Provider 7 `openrouter-free` | `completed` on superseded Bundle 165; CLI `0.84.2`, Adapter `2.0.0`, canonical seq 1–36, archive 5950 bytes, raw-log 4 chunks / 2692 bytes, 0 changes; excluded because `model.resolved` used a startup throwaway session while `harness.completed` and Task output used the active session |
| 374 | Pi / Provider 7 `openrouter-free` | `completed` on current Bundle 166; CLI `0.84.2`, Adapter `2.0.0`, fresh session, canonical seq 1–47, archive 6536 bytes, raw-log 5 chunks / 2701 bytes, 0 changes; `model.resolved`, `harness.completed`, and output session all `01a06cc4-9e66-78bf-8e99-75a0149f2e75` |
| 375 | Claude / Provider 11 `openrouter-minimax-anthropic` | `completed` on current Bundle 167; CLI `2.1.153`, Adapter `1.0.1`, fresh session, canonical seq 1–15, archive 5675 bytes, raw-log 7 chunks / 6117 bytes, usage 2576 input / 208 output, 0 changes |
| 376 | OpenCode / Provider 7 `openrouter-free` | `completed` on current Bundle 168; CLI `1.18.19`, Adapter `2.0.0`, fresh session, canonical seq 1–24, archive 7980 bytes, raw-log 5 chunks / 2711 bytes, usage 75 input / 5 output, 0 changes; canonical result `Workspace left unchanged.` |
| 377 | Codex / Provider 12 `openrouter-minimax-responses` | `failed` on current Bundle 169; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–13, archive 3549 bytes, raw-log 4 chunks / 2420 bytes; reached both requested shell commands, then upstream retry exhaustion returned HTTP 429 and canonical `run.failed(failure.kind=rate_limited)` |
| 378 | Codex / Provider 4 `opencode-luna` | `failed` on current Bundle 169; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–12, archive 3342 bytes, raw-log 4 chunks / 2426 bytes; upstream returned HTTP 403 `unsupported_country_region_territory`, classified as `engine_error` and not retried |

Together with Tasks 357/358, the live set covers Pi, OpenCode, Claude, and
Codex across multiple compatible Provider selections. The generation-73
additions provide current-Bundle success samples for Pi, Claude, and OpenCode;
Codex success remains represented by Task 368 on the preceding Bundle 163,
whose Codex Adapter identity is unchanged, while current-Bundle Tasks 377/378
are bounded upstream Provider availability failures rather than success claims.
They remain useful evidence that the failure classifier and single terminal
path reject rate-limited or region-blocked execution.

Tasks 369 and 370 were two isolated probes in which only the remote
`codify-backend` container was restarted while the task page remained open. The
frontend stayed on Issue #99, but both persisted terminal payloads identify the
failure as upstream `rate_limited`; neither reached the requested long-running
read-only command. They remain negative, inconclusive evidence only.

Task 371 was a separately authorized real-Provider OpenCode run using the known
successful Provider 7 selection. It entered `sleep 180` before the controlled
nginx restart. The browser stayed on `/tasks/371` with the three existing
commands visible and no error state; after the nginx interruption, the UI
continued to receive the post-delay AI result and completed the task. Persisted
event timestamps put seq 1–9 before the nginx restart and seq 10–26 after it:
the latter includes `tool.completed` for `sleep`, `message.completed`,
`delivery.completed`, `worker.finalization`, and `run.completed`. This is the
first valid real Host frontend-entrypoint disconnect/reconnect spot-check in
this evidence set. It does not prove mobile keyboard/safe-area behavior or a
broader disruption matrix.

Task 372 was a separately authorized real-Provider OpenCode cancellation
diagnostic on the same OpenCode-specific Bundle 164 and Provider 7. The task
page showed the Worker initialized and the `sleep 180` command in progress
before the operator clicked cancel. The UI converged to `已取消` while
retaining the command/log history. The persisted attempt had `last_seq=15`,
`control_state=closed`, and no duplicate or missing sequence; its canonical
terminal is intentionally `run.failed` because V2 reserves that event type for
all failed/cancelled Task terminals, with `status=cancelled` and
`failure.kind=cancelled` providing the cancellation semantics. This validates
stable-state cancellation on OpenCode with `exit_code=143`; it is not a code
delivery sample.

Tasks 374–378 then added the generation-73 post-`810f9fcb` smoke cohort. Task
374's Pi `model.resolved`, `harness.completed`, and Task output session all
match, demonstrating the `810f9fcb` fix against the real startup stream. Task
375 completed Claude and Task 376 completed OpenCode with clean workspaces.
Task 377 reached the Codex Adapter and both read-only shell commands before
Provider 12 became `rate_limited` after HTTP 429 retry exhaustion. Task 378
reached the Codex Adapter but its Provider 4 failed before the model turn with
`engine_error` for upstream 403 `unsupported_country_region_territory`.
Both failures have one canonical terminal, finalized raw logs, and retained
archives; neither is counted as a Codex success sample.

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
- Task #371 was a real Provider 7/OpenCode read-only diagnostic. The task detail
  page remained open while only `codify-nginx` restarted; it retained the three
  command records, then displayed the completion message and completed state
  after the delayed command. The persisted event sequence has 26 unique,
  contiguous receipts spanning the restart window.
- On the refreshed Issue #99 create-task drawer, enabling “use new session” made
  the Harness selector editable. The browser selected OpenCode with the default
  Provider 7 for Task 376, then selected Codex with Provider 12 for Task 377
  and Provider 4 for Task 378. The three tasks were submitted in freeform mode;
  the UI showed the expected completed or bounded failure states after reload.
- Task #374's detail page exposed the post-fix Pi completion with zero changes;
  the persisted session identity matched across `model.resolved`,
  `harness.completed`, and the Task output. Task #375/#376 exposed the Claude
  and OpenCode completions with their selected Provider, fresh-session context,
  usage, archive, and zero-change result. Tasks #377/#378 exposed Codex's
  `rate_limited` and `engine_error` reasons respectively; no retry was clicked
  after the bounded upstream failures.

After the restart probes, the frontend structured-log lifecycle was tightened
at the source level: `useTaskLogStreams` now checks EventSource identity in both
the `error` handler and the structured `done` callback before closing the
current stream or reporting completion. The same identity check now also
rejects stale `batch` and `update` callbacks from the old source before they
enter the shared pending queue or merge into current task logs. Three focused
regression tests cover the stale-error, stale-done, and stale-batch/update
races, and the full frontend suite passed 80 files / 1692 tests; `npm run build` also passed with only the existing
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
performed. The subsequent nginx-only build increased the final snapshot to the
values recorded above; no protected service or unrelated image was touched.

The follow-up frontend-only commit `a6be3f8b` was deployed through the `remote`
Docker context with the same nginx-only rebuild/recreate boundary. The actual
served `index.html` contains `viewport-fit=cover`, and the authenticated target
Host page at the desktop viewport exposed the mobile top-inset and drawer
bottom-inset rules in its loaded stylesheets. This verifies the built artifact
and deployment path; the desktop viewport still cannot prove a real iOS
keyboard, IME resize, notch, or home-indicator measurement.

## R4.3/R4.4 boundary after this run

### R4.3 — partial evidence, not signed

The run covers long-text layout, mobile task/create navigation, editor focus,
bottom-action reachability, form-level and existing-Issue Harness selection, a
real running/completed transition, command ACK wording, reload continuity, a
controlled real frontend-entrypoint disconnect/reconnect, and the post-fix
Codex execution-model display.
It does not yet sign the full gate because:

- Chrome's desktop extension viewport cannot prove behavior with a real mobile
  soft keyboard, IME resize, or notched-device safe-area inset. The frontend now
  opts into `viewport-fit=cover` and the served stylesheet places the mobile
  shell/drawer content around the top and bottom `safe-area-inset-*` values, but
  this run still observed a zero computed inset in the desktop viewport.
- Task 371 supplies a controlled real disconnect/reconnect spot-check: the
  browser task page stayed mounted through the nginx restart, and persisted
  events continued from seq 9 before the restart through seq 10–26 after it,
  ending in `run.completed` with zero changes. This is one Host-level sample,
  not a broad network-disruption matrix.
- The two backend-restart probes (#369/#370) are also inconclusive: their
  persisted `run.failed` payloads are upstream `rate_limited`, and no probe
  reached the delayed command needed to establish event-stream continuity.
- The structured-log client now rejects stale `error`/`done`/`batch`/`update`
  callbacks from a previous EventSource after reconnect; the focused race
  tests and the full frontend suite pass. Together with Task 371, this closes
  the current source-level and single-sample Host reconnect check, but not the
  remaining mobile-device and acceptance review gates.
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

Tasks 357–366 and 368–378 plus the prior five-task warm-start cohort provide all
four Harness selections with real success samples across the evidence set and
bounded upstream failure classification, command latency, usage, canonical
terminal, archive, raw-log finalization, delivery samples, and the current
queue/lock/secret-scan snapshot. The generation-73 current candidate adds
successful Pi/Claude/OpenCode samples (#374–#376) and two correctly bounded
Codex Provider failures (#377/#378); the current-Bundle Codex success sample
is still open because these two current-generation attempts were blocked by
upstream 429 and 403 responses. Task 368 on Bundle 163 remains a valid Codex success for
the unchanged Codex Adapter identity, but does not replace that missing exact
generation-73 Codex success. The local Mattermost mock E2E suite also passed
96 tests, covering profile CRUD, config validation, connection-test outcomes,
event filtering, and delivery result recording without contacting a real
notification service. A complete Harness/Profile/Host operational review of
alert behavior and a formal zero-P0/P1 sign-off are still required; no
notification profile was configured on this development Host for a live alert
delivery test.

The backend notification path was also exercised on the target Host with a
temporary channel profile and a mock Mattermost HTTP service attached only to
the Compose Docker network. Task 368 produced one real `POST /api/v4/posts`
and one recorded `success` delivery; the temporary profile, delivery row, and
mock container were removed immediately afterward. This proves the Host
container/DB/HTTP delivery path, but not authorization, a real Mattermost
server, or external alert routing.

The generation-73 Bundle 166–169 receipt recheck supports the
zero-duplicate-terminal and zero-sequence-gap claim for the current candidate:
five attempts (#374–#378) contain 111 contiguous receipts in total, each with
one Harness terminal and one Task terminal. Bundle 166/167/168/169 remain
selected-Harness evidence variants over the same Image/Kit and Adapter
identities. Bundle 163/164 and Task 368/371/372 are retained as historical
generation-72 evidence; Bundle 165 and Task 373 are explicitly superseded by
the Pi session-projection defect. The expanded current cohort still passes the
frozen status/terminal mapping, duplicate-terminal, sequence, and secret-like
checks, while leaving the exact generation-73 Codex success, live alert
delivery to a real Mattermost service, and the formal zero-P0/P1 review open.

R4.5 security/release sign-off and R4.6 independent hard-cut go/no-go remain
open. No R5 maintenance window or `v2_only` cutover was performed.
