# Open-Harness V2 R4.3/R4.4 Live Host Evidence

**Date:** 2026-09-05

**Scope:** Current R4 candidate on `192.168.50.129`, mobile/desktop browser
interaction checks, four-Harness live smoke attempts, one live command-plane
run, four current exact Worker/Kit/Bundle-composition cancellation samples,
five post-fix current-composition success samples, one controlled nginx-only
disconnect/reconnect, one current exact-composition Codex Provider-boundary
failure sample, two current exact-composition Codex success samples, and the
resulting Host/Task runtime evidence.

This is candidate evidence, not an L5 go/no-go decision. R4.3–R4.6 remain
partially open until the complete acceptance, operational, security/release,
and independent review gates are signed.

## Exact committed composition recheck

The mixed-provenance Host image recorded in the historical sections below is
not the current candidate. On 2026-09-05 the Backend/Scheduler image was first
rebuilt from committed tree `40235196` and deployed through the `remote` Docker
context. After the live cancellation samples exposed a Scheduler log
classification defect, commit `48b16fdc` changed only the final cancellation
log branch, and Backend/Scheduler were rebuilt and recreated again. The current
post-fix image is:

| Item | Result |
| --- | --- |
| Backend/Scheduler image | `sha256:334c674db035dd9e5ab63d96918c0af19a680387db4afcecef52a8b2f4d575bb`; built from committed tree `48b16fdc`; the image exposes `org.opencontainers.image.version=22.04` and no Git revision OCI label |
| Previous exact Backend/Scheduler image | `sha256:0ea2d9832fc0c7b3ca893b62f52a4f75fc54c56ed0bc80d732b08c95f5628c20`, committed tree `40235196`; historical for Tasks 380–386 |
| Running services | `codify-backend` and `codify-scheduler` both use the image above; Backend health is `healthy`, Scheduler reports `dual_canary` |
| Profile 4 | administrator Verify returned 200; `verified_at=2026-09-05T00:45:09Z`, V2 verification generation `74`, Kit `0.6.12` manifest `c33dbf86951bed6e3b4de1897313725f14f00006dc51fb300e7b821bb47e17bd` |
| Source/composition boundary | The post-fix change is limited to Scheduler cancellation-status logging; Worker image, Kit `0.6.12`, Profile 4 generation `74`, Bundles 170/171/172/173, selected Adapter/CLI identities, Provider protocols, and event contract remain unchanged. The current image's provenance is recorded by the committed tree and remote build/deploy command because no Git revision OCI label is present |
| Database/runtime mode | Alembic revision remains `077_v2_worker_kit_identity`; `AUTO_MIGRATE=false`; execution mode remains `dual_canary`; no `v2_only` cutover or migration was attempted |
| Host capacity | Remote `/` is `57G/61G` used with `4.2G` available and `94%` full; the post-Task-394 Docker snapshot reports 83 images, 12.42GB images with 6.713GB reclaimable, 9.033MB containers, 1.643GB volumes with 1.309GB reclaimable, and 6.526GB BuildKit cache. The filesystem is not full, so no Codify image/cache cleanup was performed. |

As a Host-level `v2_only` preflight, Backend and Scheduler were temporarily
recreated with `HARNESS_EXECUTION_MODE=v2_only` at `2026-09-05T01:04:26Z`.
Backend health returned `healthy` with `harness_execution_mode=v2_only`,
Scheduler health returned `running` with the same mode, auto-migration remained
disabled, and the authenticated browser loaded the real V2 Task #380 detail
without creating or mutating a Task. The database had zero active Tasks and
zero Issue locks. The services were restored to `dual_canary` at
`2026-09-05T01:05:13Z`; final health reports `dual_canary` and crash recovery
reported zero resumed/awaiting/failed Tasks. The database contains no V1 Task
(`legacy_tasks=0`), so this probe does not constitute live V1 read-only
acceptance; that acceptance remains open and is not fabricated from the V2
detail page.

A separate live V1 creation probe was attempted after the preflight. Issue
`#105` was created with enabled legacy-looking Profile 1
`kit-owned-0.4.0-dev`, Provider 12, Codex, and the read-only acceptance prompt.
The authenticated UI showed the Profile/Harness selection, but the Backend
rejected `POST /api/tasks` at `2026-09-05T03:35:34Z` with
`WorkerProfileValidationError: explicit V2 Profile has no verified CLI identity
for Harness 'codex'`. The Issue remains open with zero Tasks; the database still
has zero V1 Tasks and zero Issue locks. No database/profile bypass was used, so
this is current creation-boundary evidence rather than live V1 execution
evidence; V1 read-only acceptance remains open. The current database has 362
Task Worker Profile Snapshots, all with `runtime_contract_version=
codify.worker.harness/v2` and a bound runtime bundle; no legacy V1 Snapshot is
available to reuse for the read-only display probe.

The exact-composition positive cohort is:

| Task | Harness / Provider | Bundle | Result | Attempt evidence |
| ---: | --- | ---: | --- | --- |
| 380 | Pi / Provider 7 `openrouter-free` | 170 (`e812376c…`) | `completed`, zero changes | Adapter `2.1.0`, CLI `0.84.2`, usage 171/117, raw-log 4 chunks, 44 receipts, seq 1–44, terminal `run.completed` |
| 381 | Claude / Provider 11 `openrouter-minimax-anthropic` | 171 (`5a5bbd30…`) | `completed`, zero changes | Adapter `1.0.1`, CLI `2.1.153`, usage 2655/327, raw-log 6 chunks, 17 receipts, seq 1–17, terminal `run.completed` |
| 382 | OpenCode / Provider 7 `openrouter-free` | 172 (`9ed188ca…`) | `completed`, zero changes | Adapter `2.0.0`, CLI `1.18.19`, usage 89/58, raw-log 4 chunks, 40 receipts, seq 1–40, terminal `run.completed` |
| 383 | Pi / Provider 6 `opencode-pi` (`deepseek-v4-flash`) | 170 (`e812376c…`, reused Pi variant) | `completed`, zero changes | `anthropic_messages`; Adapter `2.1.0`, CLI `0.84.2`, usage 96/181, raw-log 4 chunks, 296 receipts, seq 1–296, terminal `run.completed`; two early `control_owner_unreachable` gate-probe warnings self-recovered |
| 388 | Claude / Provider 11 `openrouter-minimax-anthropic` | 171 (`5a5bbd30…`, reused Claude variant) | `completed`, zero changes | post-fix image; Adapter `1.0.1`, CLI `2.1.153`, usage 3512/724, raw-log 7 chunks, 19 receipts, seq 1–19, terminal `run.completed` |
| 389 | Claude / Provider 6 `opencode-pi` (`deepseek-v4-flash`) | 171 (`5a5bbd30…`, reused Claude variant) | `completed`, zero changes | `anthropic_messages`; fresh session; Adapter `1.0.1`, CLI `2.1.153`, usage 2247/597, raw-log 6 chunks, 20 receipts, seq 1–20, terminal `run.completed` |
| 390 | OpenCode / Provider 6 `opencode-pi` (`deepseek-v4-flash`) | 172 (`9ed188ca…`, reused OpenCode variant) | `completed`, zero changes | `anthropic_messages`; fresh session; Adapter `2.0.0`, CLI `1.18.19`, usage 136/128, raw-log 4 chunks / 2678 bytes, 216 receipts, seq 1–216, terminal `run.completed` |
| 392 | Codex / Provider 12 `openrouter-minimax-responses` (`minimax/minimax-m3:free`) | 173 (`de3b5a5f…`, Codex variant) | `completed`, zero changes | `openai_responses`; fresh session; Adapter `1.0.0`, CLI `0.146.0`, usage 21030/137, raw-log 5 chunks / 2733 bytes, 14 receipts, seq 1–14, terminal `run.completed`; archive 3980 bytes (`9afe4f3f…`) |
| 394 | Pi / Provider 12 `openrouter-minimax-responses` (`minimax/minimax-m3:free`) | 170 (`e812376c…`, reused Pi variant) | `completed`, zero changes | `openai_responses`; fresh session; Adapter `2.1.0`, CLI `0.84.2`, usage 139/118, raw-log 3 chunks / 2727 bytes, 74 receipts, seq 1–74, terminal `run.completed`; archive 8974 bytes (`2ffe9f76…`); one early `control_owner_unreachable` gate-probe retry self-recovered |

All nine tasks used fresh sessions and read-only smoke prompts.
Tasks 380–383 contain 397 unique contiguous receipts; Task 388 adds 19,
Task 389 adds 20, Task 390 adds 216, Task 392 adds 14, and Task 394 adds 74
more, for 740 receipts across the nine exact-composition success attempts. No active Task
or Issue execution lock remains. Current exact Task 391 remains a Provider 4
`403 unsupported_country_region_territory` negative sample, while current exact
Tasks 392 and 394 add Provider 12 Codex and Pi success samples. Together they
bound both the runtime success path and the known Provider availability boundary;
the 403 is not a claim of runtime failure.

Task #384 is a separate current-composition cancellation sample and is not
counted in the exact-composition success cohort above. It used OpenCode with Provider 7
(`openrouter-free`) on Bundle 172, with a fresh session and the read-only
`pwd` plus `sleep 180` prompt. The operator cancelled while the sleep was
running; the task ended `cancelled` with `MessageAbortedError: Aborted`, zero
changes, and no Issue lock. Its attempt used Adapter `2.0.0` / CLI `1.18.19`
and persisted 15 unique contiguous receipts (seq 1–15):
`harness.failed(failure.kind=cancelled)` →
`worker.finalization(exit_code=143)` →
`run.failed(status=cancelled, failure.kind=cancelled)`. The runtime archive
was finalized at 7039 bytes (`59c56212165eee79e67dc0772c973e26e0bad3c949169740ba442db53d8c9e86`),
raw-log persistence has 4 chunks / 3215 bytes, and the Worker container was
removed. The expected post-exit canonical-tail 409 warning was observed after
the container had already stopped; persisted receipts and archive finalization
were unaffected.

Task #385 is a second separate current-composition cancellation sample for
Pi. It used Provider 6 (`opencode-pi` / `deepseek-v4-flash`) on Bundle 170,
with a fresh session and the same read-only `pwd` plus `sleep 180` prompt.
The operator cancelled while the sleep was running; the task ended
`cancelled` with `Cancelled by user`, zero changes, and no Issue lock. Its
attempt used Adapter `2.1.0` / CLI `0.84.2` and persisted 40 unique contiguous
receipts (seq 1–40): `harness.failed(failure.kind=cancelled)` →
`worker.finalization(exit_code=143)` →
`run.failed(status=cancelled, failure.kind=cancelled)`. The runtime archive
was finalized at 6547 bytes (`b742525261e4cc6f75fb02b7308310e0dfd12f9c6cce0e33aaef8a70005d5f4d`),
raw-log persistence has 3 chunks / 5659 bytes, and the Worker container was
removed. A transient `control_owner_unreachable` gate-probe retry warning and
the expected post-exit canonical-tail 409 were non-blocking; the persisted
cancellation receipts and archive remained complete.

Task #386 is a third separate current-composition cancellation sample for
Claude. It used Provider 11 (`openrouter-minimax-anthropic` /
`minimax/minimax-m3:free`) on Bundle 171, with a fresh session and the same
read-only `pwd` plus `sleep 180` prompt. The operator cancelled while the
sleep was running; the task ended `cancelled` with `Cancelled by user`, zero
changes, and no Issue lock. Its attempt was
`task-386-attempt-1-7ab79696e2c1`, using Adapter `1.0.1` / CLI `2.1.153`, and
persisted 8 unique contiguous receipts (seq 1–8):
`harness.failed(failure.kind=cancelled)` →
`worker.finalization(exit_code=143)` →
`run.failed(status=cancelled, failure.kind=cancelled)`. The runtime archive
was finalized at 4980 bytes
(`a9dead4511a125904fd12e5bd960350cb8a72f2990251c6aff411d3082b8fa6a`),
raw-log persistence has 5 chunks / 6904 bytes, and the Worker container was
removed. The expected post-exit canonical-tail 409 was non-blocking because
the canonical cancellation receipts and archive were already persisted.
The Scheduler also emitted its generic `Task 386 failed` error log after
cancellation; it did not change the database or canonical terminal state and
remains an alert-classification item for the R4.4 operational review.

Task #387 is the post-fix current-composition cancellation sample for Claude.
It used the same Provider 11 (`openrouter-minimax-anthropic` /
`minimax/minimax-m3:free`), Bundle 171, fresh session, Adapter `1.0.1`, and
CLI `2.1.153` as Task #386, but ran after the Scheduler image was rebuilt from
`48b16fdc`. The operator cancelled while the real `sleep 180` command was
running; the task ended `cancelled` with `Cancelled by user`, zero changes,
and no Issue lock. Attempt
`task-387-attempt-1-a3e1b350ae78` persisted 9 unique contiguous receipts
(seq 1–9), ending in the same
`harness.failed(failure.kind=cancelled)` →
`worker.finalization(exit_code=143)` →
`run.failed(status=cancelled, failure.kind=cancelled)` chain. The runtime
archive was finalized at 4594 bytes with SHA-256
`69e8a1df9a6c7ffce572b92c414ae9d1b38b5eb1cd057726425d28dce7a9427e`, raw-log
persistence has 6 chunks / 5117 bytes, and the Worker container was removed.
The expected post-exit canonical-tail 409 was non-blocking because the
canonical cancellation receipts and archive were already persisted. The
post-fix Scheduler emitted exactly one `Task 387 cancelled` INFO line and no
`Task 387 failed` line.

Task #388 is the post-fix current-composition success sample for Claude. It
used the same Provider 11 (`openrouter-minimax-anthropic` /
`minimax/minimax-m3:free`), Bundle 171, fresh session, Adapter `1.0.1`, and
CLI `2.1.153` as Task #387, but completed the read-only smoke on the rebuilt
Backend/Scheduler image. The task ended `completed` with zero changes and no
Issue lock. Attempt `task-388-attempt-1-7c1e218d55ee` closed with 19 unique
contiguous receipts (seq 1–19), including `worker.finalization(exit_code=0,
diff.total=0)` and terminal `run.completed(status=completed)`. The runtime
archive was finalized at 7586 bytes with SHA-256
`27852b5a58f264f0cd881030b9c44dc647fd0cf759df61c6421fba6112fb8acf`, raw-log
persistence has 7 chunks / 8486 bytes, and the Worker container was removed.
The expected post-exit canonical-tail 409 was non-blocking after the archive
and receipts were persisted. Scheduler emitted one `Task 388 completed
successfully` INFO line, with no failure terminal; the authenticated task
detail page showed `completed`, Claude, Provider 11, the exact Worker image,
20 seconds, 3512 input / 724 output tokens, and `+0 -0` changes.

Task #389 is a second post-fix current-composition success sample for Claude.
It used Provider 6 (`opencode-pi` / `deepseek-v4-flash`) over the legal
`anthropic_messages` protocol on Bundle 171, with a fresh session, Adapter
`1.0.1`, and CLI `2.1.153`. The task was created and completed at
`2026-09-05T02:31:32Z` / `2026-09-05T02:31:50Z`; it ended `completed` with zero
changes and no Issue lock. Attempt `task-389-attempt-1-b514023e39e1` closed
with 20 unique contiguous receipts (seq 1–20), including
`worker.finalization(exit_code=0, diff.total=0)` and terminal
`run.completed(status=completed)`. The runtime archive was finalized at 7236
bytes with SHA-256
`439f313210aaf845aecdcdbf1b08c724fa5ec6b4dee8072664191dc9c29208d4`, raw-log
persistence has 6 chunks / 8359 bytes, and the Worker container was removed.
The expected post-exit canonical-tail 409 was non-blocking after receipt and
archive persistence. Scheduler emitted one `Task 389 completed successfully`
INFO line; the authenticated task detail page showed completed Claude,
Provider 6 `opencode-pi`, the exact Worker image, 16 seconds, 2247 input / 597
output tokens, and `+0 -0` changes.

Task #390 is the third post-fix current-composition success sample, using
OpenCode with Provider 6 (`opencode-pi` / `deepseek-v4-flash`) over the legal
`anthropic_messages` protocol on Bundle 172. It used a fresh session, Adapter
`2.0.0`, and CLI `1.18.19`; the task was created and completed at
`2026-09-05T02:48:47Z` / `2026-09-05T02:49:38Z`. It ended `completed` with zero
changes and no Issue lock. Attempt `task-390-attempt-1-8414e97cc86d` closed
with 216 unique contiguous receipts (seq 1–216), including
`worker.finalization(exit_code=0, diff.total=0)` and terminal
`run.completed(status=completed)`. The runtime archive was finalized at 22384
bytes with SHA-256
`d54b5eb2e2a24b6e98d2614f9e249a10fd35d22ed6d91643924ff9191c68dd0e`, raw-log
persistence has 4 chunks / 2678 bytes, and the Worker container was removed.
The expected post-exit canonical-tail 409 was non-blocking after receipt and
archive persistence. Scheduler emitted one `Task 390 completed successfully`
INFO line; the authenticated task detail page showed completed OpenCode,
Provider 6, the exact Worker image, 46 seconds, 136 input / 128 output
tokens, and `+0 -0` changes.

Task #391 is a current exact-composition Codex negative sample, not part of the
positive success cohort. It used Provider 4 (`opencode-luna` /
`gpt-5.6-luna`) over the legal `openai_responses` protocol on the Codex Bundle
173 (`de3b5a5f…`), with a fresh session, Adapter `1.0.0`, and CLI `0.146.0`.
The task was created and completed at `2026-09-05T03:06:28Z` /
`2026-09-05T03:06:50Z`; it ended `failed` with zero changes and no Issue lock.
Attempt `task-391-attempt-1-b262994239a1` closed with 12 unique contiguous
receipts (seq 1–12), one `run.failed(status=failed, failure.kind=engine_error)`
terminal, and six provider retries. The upstream failure was
`403 unsupported_country_region_territory` from
`https://opencode.ai/zen/go/v1/responses`; the Host-only unauthenticated
`/v1/models` reachability check returned 200 immediately beforehand, so model
listing reachability is not treated as model execution availability. The
runtime archive was finalized at 3314 bytes with SHA-256
`db05ea24b9d670b9d85d5aab58779fe17fd28ca2a058eb81f6dfc140b79d8e75`, raw-log
persistence has 4 chunks / 2393 bytes, and the Worker container was removed.
The expected post-exit canonical-tail 409 was non-blocking after persistence;
Scheduler emitted one `Task 391 failed` ERROR for the bounded upstream failure;
the authenticated task detail page showed failed Codex, Provider 4
`opencode-luna`, the exact Worker image, 20 seconds, no token usage, and
`+0 -0` changes.

Task #392 is the current exact-composition Codex success sample. It used
Provider 12 (`openrouter-minimax-responses` / `minimax/minimax-m3:free`) over
the legal `openai_responses` protocol on Bundle 173 (`de3b5a5f…`), with a
fresh session, Adapter `1.0.0`, and CLI `0.146.0`. The task ran from
`2026-09-05T03:21:56Z` to `2026-09-05T03:22:38Z` and completed with zero
changes. Attempt `task-392-attempt-1-4a0143f634b7` closed with 14 unique
contiguous receipts (seq 1–14), one `run.completed(status=completed, success=true)`
terminal, and a successful read-only shell inspection of `/workspace` on
`codify/issue-99`; the delivery result had exit code 0 and no commit. Usage was
21030 input / 137 output tokens. The runtime archive was finalized at 3980
bytes with SHA-256
`9afe4f3f9bfd08b01ec75f1f8b6ca7316cfa88dbf204c0fb8fd40571478f44ad`, raw-log
persistence has 5 chunks / 2733 bytes, and the Worker container was removed.
The expected post-exit canonical-tail 409 was non-blocking after persistence;
Scheduler logged one `Task 392 completed successfully` INFO. The authenticated
task detail page showed completed Codex, Provider 12, the exact Worker image,
42 seconds, 21K input / 137 output tokens, and `+0 -0` changes. The model also
emitted a bounded fallback-metadata diagnostic because the OpenRouter model
was not in the local metadata table; it did not change the successful terminal
or delivery result.

Task #394 is the fifth post-fix current-composition success sample and a second
Provider 12 success sample. It used Pi with the same OpenRouter model over the
legal `openai_responses` protocol on the reused Pi Bundle 170 variant
(`e812376c…`), with a fresh session, Adapter `2.1.0`, and CLI `0.84.2`. The
task ran from `2026-09-05T03:41:26Z` to `2026-09-05T03:41:54Z` and completed
with zero changes. Attempt `task-394-attempt-1-f59d45de3da3` closed with 74
unique contiguous receipts (seq 1–74), one
`run.completed(status=completed, success=true)` terminal, and the read-only
shell inspection returned a clean `/workspace` on `codify/issue-99`; the
delivery result had exit code 0 and no commit. Usage was 139 input / 118 output
tokens. The runtime archive was finalized at 8974 bytes with SHA-256
`2ffe9f760035d6ec85aad6029d41659f97d4e0a2a5927ae169f976b4460b69ee`, raw-log
persistence has 3 chunks / 2727 bytes, and the Worker container was removed.
The authenticated task detail page showed completed Pi, Provider 12, the exact
Worker image, 28 seconds, 139 input / 118 output tokens, and `+0 -0` changes.
Scheduler emitted one `control_owner_unreachable` gate-probe retry warning that
self-recovered, then logged `Task 394 completed successfully`; the expected
post-exit canonical-tail 409 was non-blocking after receipt/archive persistence.

## Candidate and validation boundary

- The Worker runtime image, Worker Kit `0.6.12`, and frozen CLI identities remain
  unchanged from the
  [R4.1/R4.2 candidate evidence](2026-09-03-open-harness-v2-r4.1-kit-boundary.md).
  The exact candidate identity in that document was superseded after the
  Codex Adapter fix below; its Kit-boundary evidence remains historical
  structural evidence.
- Commit `48b16fdc` is a Scheduler-only post-fix change: unsuccessful Worker
  outcomes are logged after the final Task row is loaded, so a final
  `cancelled` status produces an INFO cancellation line rather than a generic
failure ERROR. The remote Backend/Scheduler image for Tasks #387–#392 is
  `sha256:334c674d…`; the Worker/Kit/Profile/Bundle/Adapter/CLI composition is
  unchanged from Tasks 380–386.
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
- The following generation-73 identity and Task table are retained as historical
  pre-rebuild evidence; the exact-composition recheck above is the current
  candidate. Current post-fix identity in that historical cohort: Profile 4
  generation `73`; Worker Kit `0.6.12`
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
  | `backend/.venv/bin/python -m pytest backend/tests/unit/test_scheduler_coverage.py -q` | 64 passed; includes post-fix cancellation log classification |
  | focused Ruff for Scheduler change | passed |
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

## Historical remote Host state (before the post-fix image)

The generation-73 and mixed-provenance snapshots in this section are retained
for traceability only. The current Backend/Scheduler image, capacity snapshot,
and post-fix Task #387 evidence are recorded in the exact-composition section
above.

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

## Historical operational snapshot (before post-fix Task #387)

The read-only snapshot taken after Task 379 converged showed zero active Tasks
(`pending`, `queued`, or `running`) and zero `issue_execution_locks`; the
database contained 347 Tasks. Tasks 374–379 each had exactly one canonical
terminal event, contiguous sequence numbers starting at 1, and finalized
raw-log storage. Their raw-log totals were 5/2701 bytes, 7/6117 bytes,
5/2711 bytes, 4/2420 bytes, 4/2426 bytes, and 4/2397 bytes respectively. The
six current generation-73 attempts contain 119 receipts and 119 distinct event
IDs; the
task and Harness terminal counts are both six. Token-shaped secret scanning
for the complete current cohort remains zero as recorded below.

Task 358's one live `steer` command was `delivered` with one delivery attempt;
the other recorded smoke tasks had no control command. The remote database had
no Mattermost notification profile or delivery record, so live alert delivery
was not exercised and is not treated as passing evidence.

A fresh read-only integrity query scoped to the generation-73 Runtime Bundles
166–169 found the six current-candidate attempts (Tasks 374–379): all six
have exactly one terminal event, 119 receipts total, and contiguous sequences
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

The historical additions below used Profile 4, the generation-73 V2
mounted-Kit composition, the selected Harness/Provider combinations shown
below, and a fresh session. All prompts were read-only diagnostics and
produced no code changes. The post-fix current-composition Task #387 is
recorded above.

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
| 379 | Codex / Provider 9 `openrouter-glm52-responses` | `failed` on current Bundle 169; CLI `0.146.0`, Adapter `1.0.0`, canonical seq 1–8, raw-log 4 chunks / 2397 bytes, 0 changes; `model.resolved` and the Provider retry path were reached, but the upstream again exhausted HTTP 429 retries before a model turn, ending in `run.failed(failure.kind=rate_limited)` |

Together with Tasks 357/358, the live set covers Pi, OpenCode, Claude, and
Codex across multiple compatible Provider selections. The generation-73
additions provide current-Bundle success samples for Pi, Claude, and OpenCode;
the historical Codex success remains represented by Task 368 on the preceding
Bundle 163, whose Codex Adapter identity is unchanged, while current-Bundle
Tasks 377–379 are bounded upstream Provider availability failures rather than
success claims. Current generation-74 Bundle 173 now also has the successful
Codex Task 392, alongside the separate Provider 4 negative Task 391.
They remain useful evidence that the failure classifier and single terminal
path reject rate-limited or region-blocked execution.

Task 379 was a controlled follow-up against Provider 9 after the prior result
was more than 24 hours old and no task was in flight. The Codex Adapter resolved
`z-ai/glm-5.2:free`, emitted the expected `provider.retry` classification, and
persisted the bounded upstream `rate_limited` failure with no requested command
execution and no workspace changes. It therefore does not add a Codex success
sample or reopen the Adapter/runtime diagnosis; it strengthens the current
Provider-availability boundary. No additional Codex retry was created against
the already-known region-blocked Provider 4.

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

Tasks 374–379 then added the generation-73 post-`810f9fcb` smoke cohort. Task
374's Pi `model.resolved`, `harness.completed`, and Task output session all
match, demonstrating the `810f9fcb` fix against the real startup stream. Task
375 completed Claude and Task 376 completed OpenCode with clean workspaces.
Task 377 reached the Codex Adapter and both read-only shell commands before
Provider 12 became `rate_limited` after HTTP 429 retry exhaustion. Task 378
reached the Codex Adapter but its Provider 4 failed before the model turn with
`engine_error` for upstream 403 `unsupported_country_region_territory`.
Task 379 reached the Codex Adapter and resolved Provider 9, but failed before
the requested commands after another HTTP 429 retry exhaustion. All three
failures have one canonical terminal and finalized raw logs; none is counted as
a Codex success sample.

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
  this run still observed a zero computed inset in the desktop viewport. Per
  the user's instruction, real mobile-device keyboard/IME/notch/gesture-area
  acceptance is temporarily deferred and is not part of this round's remote
  execution; this evidence deliberately makes no device-level pass claim.
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
  pending/failed/running rendering and API rejection semantics. A temporary
  Host `v2_only` preflight then confirmed mode health and real V2 detail
  loading, but no V1 Task exists in the development database, so it did not
  produce live V1 read-only evidence; the Host was restored to `dual_canary`.
- The live Task #358 remained Pi-locked. On existing Issue #99, the drawer
  kept the current OpenCode Harness and displayed the continuation lock hint;
  enabling “use new session” allowed a temporary switch to Claude and the
  form was restored to OpenCode without submitting a task. `v2_only` V1
  read-only presentation was not exercised on the Host; the source suite does
  cover pending/failed/running V1 read-only rendering, including a 390px case.
  The Host remains `dual_canary`.

### R4.4 — partial evidence, not signed

Tasks 357–366, 368–379, and the exact-composition Tasks 380–383, 388–394 plus the prior
five-task warm-start cohort provide all four Harness selections with real
success samples across the evidence set and bounded upstream failure
classification, command latency, usage, canonical terminal, archive, raw-log
finalization, delivery samples, and the current queue/lock/secret-scan
snapshot. The exact-composition candidate adds successful Pi/Claude/OpenCode/Pi
samples (#380–#383, #388–#390, #394) on Bundles 170/171/172; Task 391 adds the
current exact-composition Codex negative sample on Bundle 173, and Task 392
adds the current exact-composition Codex success sample on the same Bundle;
Task 394 adds a current exact-composition Pi success sample on Bundle 170.
Task 383 reuses the Pi Bundle 170
variant with Provider 6 over `anthropic_messages`, post-fix Tasks #388/#389 add
two Claude successes on Bundle 171 (Provider 11 then Provider 6), and Task #390
adds an OpenCode success on Bundle 172 with Provider 6 over the same legal
protocol. The
pre-fix Backend image's current
exact OpenCode, Pi, and Claude cancellation samples are Tasks 384,
385, and 386 on Bundles 172, 170, and 171; post-fix Task #387 repeats the
Claude cancellation path on Bundle 171 and verifies the corrected Scheduler
log classification. The generation-73 samples
(#374–#376) and three correctly bounded Codex Provider failures (#377–#379)
remain historical. Current-composition Task 391 reached the Codex Adapter and
was bounded as `engine_error` from Provider 4's
`403 unsupported_country_region_territory` response on Bundle 173. Current
Task 392 then completed Codex on Bundle 173 through Provider 12, so the
current exact-composition Codex success gate is now evidenced; Task 394 then
completed Pi on Bundle 170 through Provider 12, adding a current exact-composition
Pi success sample; Task 368 on
Bundle 163 remains a valid preceding-generation Codex success for the
unchanged Codex Adapter identity. The local Mattermost mock E2E suite also passed
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

The generation-73 Bundle 166–169 receipt recheck remains historical evidence:
six attempts (#374–#379) contain 119 contiguous receipts in total, each with
one Harness terminal and one Task terminal. The exact-composition Bundle
170/171/172 recheck adds four attempts (#380–#383) with 397 contiguous,
unique receipts and one `run.completed` terminal per attempt; post-fix Task
#388 adds a fifth attempt with 19 contiguous receipts and one `run.completed`
terminal, and #389 adds a sixth 20-receipt success attempt on Bundle 171. Bundle 163/164
and Task 368/371/372 are retained as historical generation-72 evidence;
Bundle 165 and Task 373 are explicitly superseded by the Pi session-projection
defect. Tasks 384, 385, and 386 add separate 15-, 40-, and 8-receipt
pre-fix current-composition cancellation chains, while Task #387 adds a
post-fix 9-receipt chain ending in `run.failed(status=cancelled)` and Task
#388 adds a post-fix 19-receipt success chain ending in `run.completed`, and
#390 adds a seventh 216-receipt OpenCode success chain on Bundle 172 ending in
`run.completed`, while #391 adds a current-composition 12-receipt Codex failure
chain on Bundle 173 ending in
`run.failed(status=failed, failure.kind=engine_error)`, and #392 adds a
current-composition 14-receipt Codex success chain on Bundle 173 ending in
`run.completed`, while #394 adds a 74-receipt Pi success chain on Bundle 170
ending in `run.completed`.
The expanded cohorts pass the frozen status/terminal mapping,
duplicate-terminal, sequence, and secret-like checks, while leaving the exact
composition Provider boundary, live alert delivery to a real Mattermost
service, and the formal zero-P0/P1 review open.

At the current Host recheck after Task 394, the Task-ID 380–394 range (Task 393
has no Task row) was audited together: 14 attempts, 824 receipts, and 824
distinct event IDs; every attempt had exactly one
Harness terminal and one Task terminal, all sequences were contiguous from
seq 1, and the completed/cancelled-to-terminal mapping had zero failures.
The constrained token-like scan found zero matches in both canonical event JSON
and raw-log chunks. This strengthens the current R4.4 runtime-integrity
evidence without changing the known Provider boundary, live-alert, or
independent release-sign-off boundaries.

R4.5 security/release sign-off and R4.6 independent hard-cut go/no-go remain
open. No R5 maintenance window or `v2_only` cutover was performed.

## 2026-09-05 continuation: live V1 acceptance and strict read-only display

The earlier sections above are the checkpoint recorded before a V1 Task could
be created. The following continuation supersedes only the statements that
said the development database had no V1 Task; it does not change the frozen
V2 cohort or claim an L5/L6 approval.

### Launcher compatibility fix and V1 Kit composition

The dual-canary policy explicitly permits frozen V1 bundles, but the Kit
launcher still rejected every outer `codify.worker.runtime-bundle/v1`
manifest and applied the V2-only `bundle_digest` self-binding check to V1.
The minimal fix in `deploy/worker-kit/launcher/main.go` now accepts both
runtime-bundle schemas and performs the launcher-facing digest check only for
V2. This preserves the V1 archive verification boundary: V1 stores the bundle
digest in the persisted outer manifest because placing it inside the archive
would make the archive digest self-referential. The focused backend regression
set remained green: 83 tests passed in
`backend/tests/unit/test_worker_kit.py` and
`backend/tests/unit/test_worker_profile_runtime.py`.

From that source, the target daemon built and verified a four-Harness Kit:

| Item | Result |
| --- | --- |
| Kit version/path | `0.6.13-v1-compat2` at `/opt/codify/worker-kits/0.6.13-v1-compat2-linux-amd64-d97f2157bbe7` |
| Kit manifest SHA-256 | `d97f2157bbe79ec1c278fb216d9e208063e7273ed402169a860193046b86be2e` |
| Export archive SHA-256 | `317838dd2b701129d9ae8d33f821e46835d810a087dde935c12ad4407494876e` |
| Payload verification | Pi `0.84.2`, OpenCode `1.18.19`, Claude `2.1.153`, Codex `0.146.0`; remote build smoke passed |
| Profile | temporary V1-only Profile 5 `r4-v1-readonly-smoke-20260905`, image `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`, `harness_runtimes={}` |
| Profile Verify | administrator Verify returned 200; `verified_at=2026-09-05 04:39:31` with `worker_kit_source=profile`; V2 identity fields remain null by design for this V1-only Profile |

The first four V1 probes are retained as bounded debug evidence: Tasks 395
and 396 were cancelled after the old image digest was unavailable and retry
preserved their immutable old Bundle; Task 397 reached the V1 Bundle but
exposed the old V2-only launcher schema gate; Task 398 reached the corrected
schema gate but exposed the V2-only digest check applied to V1. None is in the
V2 success or integrity cohort.

### Task 399: real V1 read-only acceptance

Task 399 was created from Issue #106 with a fresh session, Codex Harness,
Provider 12 `openrouter-minimax-responses` (`minimax/minimax-m3:free`), Profile
5, and the explicit read-only prompt to print `pwd`, inspect Git status, and
stop without changing files. It completed on the existing immutable Bundle
174 after the Kit fix:

| Item | Result |
| --- | --- |
| Task/runtime | `completed`, 31s, `total_changes=0`, input/output `20996/151` |
| Contract | Bundle 174, outer `codify.worker.runtime-bundle/v1`, `codify.worker.harness/v1`, event `codify.worker.event/v1`, bundle digest `376a80031dd5181966172132d735b45c2fe73780428ebe15c2e5a587b7d0c742`, archive-manifest digest `6da46ad0a2e12697c4baf89018032b782b36223839147c209a044972637dc6ac` |
| Attempt | `task-399-attempt-1-76758c712621`, Adapter `1.0.0`, Codex CLI `0.146.0`, `last_seq=14`, `control_state=closed`, terminal `run.completed` |
| Receipts | 14 receipts, seq 1–14, 14 distinct event IDs; event stream includes `run.started`, model resolution, tool start/completion, usage, delivery, finalization, and `run.completed` |
| Persistence | 5 raw-log chunks / 2289 bytes; archive `/opt/codify-archives/task-399-runtime-archive.tar.gz`, 3796 bytes, SHA-256 `205dfaf54d20fe07c72b9e1370274b537e5565700a1edbc72dd2d877d91d21fd`; `container_id` empty after cleanup |
| Host cleanup | `docker ps -a --filter name=codify-399` returned no container; Task 399 has zero residual `issue_execution_locks` |

The persisted raw log records `/workspace`, a clean `codify/issue-106`
branch, the requested read-only shell command, no Harness changes, and a
successful Mermaid delivery-summary validation. This is live V1 execution
evidence; it is not a V2 contract or V2 receipt contribution.

### `v2_only` V1 read-only display preflight

After Task 399 was terminal, Backend and Scheduler were recreated temporarily
with `HARNESS_EXECUTION_MODE=v2_only`. The deployment preflight reported both
health endpoints as `v2_only`. The authenticated browser loaded
`/tasks/399` and rendered `已完成` plus `Legacy V1 · 只读`, the delivery
summary, the three persisted event-stream entries, raw-log tab, Provider 12,
Profile 5, Codex Harness, 31-second runtime, and 21.1K-token statistics.
No task was created or mutated. Backend/Scheduler were then recreated with
`HARNESS_EXECUTION_MODE=dual_canary`; the final preflight reported both
endpoints consistently as `dual_canary`, Backend healthy, and zero residual
Issue locks. This closes the missing live V1 read-only display evidence, but
not the R5 hard cut or the remaining L5 review/sign-off.

### Final Host capacity and cleanup boundary

The new Kit build temporarily filled the target root filesystem to 100% with
about 413MB available. Before cleanup, every deletion target was checked with
`docker ps -a --filter ancestor=<image>` and had no container references. The
following scoped Codify-only cleanup was then performed: old Kit-export and
Backend/Frontend/test/mock images, 29 untagged Codify build layers, and
BuildKit cache older than one hour. Running Backend/Scheduler, nginx, the
Worker image, Postgres, GitLab, Redis, all volumes, and unrelated images were
not deleted. The final remote state was 25 images / 8 active, 9 containers / 9
active, 11 volumes, 160 BuildKit records, and root filesystem 61G total / 59G
used / 2.5G available (97%). All Codify services remained healthy.

### Updated R4 boundary

R4.3 now has live V1 detail evidence and a successful V1 execution, but remains
partial because real mobile keyboard/IME/notch/gesture-area acceptance is
temporarily deferred per user instruction, and the full interaction/operations
review is not independently signed. R4.4 retains the V2 exact integrity
result of 14 attempts, 824 receipts, and 824 distinct event IDs for Task IDs
380–394; V1 Task 399 is explicitly excluded. Real Mattermost delivery and
formal zero-P0/P1 sign-off remain open. R4.5 still requires migration-owner,
credential/least-privilege, release-package, retention, and maintenance-window
evidence. R4.6 remains open; the Host is intentionally left in
`dual_canary`.

## 2026-09-05 continuation: post-cleanup V2 Pi smoke (Task 400)

After the scoped full-disk cleanup, a fresh real task was created from Issue
#99 to verify that the current V2 composition still executes with the existing
Provider. This is a separate post-cleanup smoke sample; it is intentionally
not added to the frozen Task-ID 380–394 integrity cohort and does not change
the R4 sign-off boundary.

| Item | Result |
| --- | --- |
| Task/runtime | Task 400, `completed`, 19s execution, `total_changes=0`, input/output tokens `130/136` |
| Selection | Issue #99, Profile 4 `v2-canary-0.6.11-four-harness`, Pi Harness, Provider 12 `openrouter-minimax-responses` / `minimax/minimax-m3:free`, freeform, fresh session |
| Composition | Bundle 170; Worker Kit `0.6.12` at `/opt/codify/worker-kits/0.6.12-linux-amd64-c33dbf86951b`; image `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`; Pi CLI `0.84.2`, Adapter `2.1.0`, contract `codify.worker.harness/v2`, orchestration `1.0.0` |
| Attempt | `task-400-attempt-1-96d0bad6b487`, event schema `codify.worker.event/v2`, `last_seq=42`, `control_state=closed`, terminal `run.completed` |
| Receipts | 42 receipts, seq 1–42 contiguous, 42 distinct seq values and 42 distinct event IDs; the sequence-gap/duplicate check returned zero |
| Persistence | 5 raw-log chunks / 2680 bytes; 9 payload rows / 1459 bytes; archive `/opt/codify-archives/task-400-runtime-archive.tar.gz`, 6905 bytes, SHA-256 `eae25e8e14f181ef626dc766816f578e660c399b82b4766db08c9bde65f4d1ab`; `container_id` empty after cleanup |
| Host cleanup | `docker ps -a --filter name=codify-400` returned no container; Task 400 has zero residual Issue locks; the post-run query reported zero active Tasks and zero Issue locks |

The persisted raw log records `/workspace`, a clean `codify/issue-99` branch,
the requested `pwd`/Git read-only inspection, three read-only tool calls, no
Harness changes, and successful delivery-summary validation. The authenticated
desktop browser loaded `/tasks/400` and displayed `已完成`, the Provider/Worker/
Pi context, the read-only delivery summary, event stream, raw-log access, and
the 130/136 token statistics. This is desktop-browser evidence only; the real
mobile keyboard/IME/notch/gesture-area acceptance remains explicitly deferred.

The global database still contains eight historical `disabled` and three
historical `starting` Harness Attempt rows belonging to older tasks. Task 400
itself is closed and has no task or Issue-lock residue; this smoke does not
claim unrelated historical Attempt cleanup or alter those records.

The Host remains healthy in `dual_canary`. This post-cleanup smoke strengthens
current R4.3/R4.4 execution evidence, but real Mattermost delivery, the full
operations/security review, release-owner sign-off, and R4.6 independent
go/no-go remain open.

## 2026-09-05 continuation: post-cleanup protocol matrix follow-up

The follow-up run completed a legal current-Profile V2 matrix using the
existing configured Providers. These Tasks remain separate from the frozen
Task-ID 380–394 integrity cohort; they are post-cleanup execution evidence,
not a retroactive change to the cohort.

| Task | Harness / Provider | Bundle / CLI | Result and receipts | Persistence |
| --- | --- | --- | --- | --- |
| 401 | Pi / Provider 12 `openrouter-minimax-responses` (`openai_responses`) | 170 / Pi `0.84.2` | `completed`, zero changes, 58 contiguous unique receipts, `run.completed` | 5 raw chunks / 2680 bytes; archive 12953 bytes, SHA-256 `4f1117cb08a390d364ab9eb6846b7f102c6dee8074476e1781d5a038452dde61` |
| 402 | OpenCode / Provider 7 `openrouter-free` (`openai_chat_completions`) | 172 / OpenCode `1.18.19` | `completed`, zero changes, 36 contiguous unique receipts, `run.completed` | 5 raw chunks / 2691 bytes; archive 9216 bytes, SHA-256 `55ecb92af2e8d745496d9624bd4d77774e090c46ebdbd6f79e1e97fa959a359` |
| 403 | OpenCode / Provider 12 `openrouter-minimax-responses` (`openai_responses`) | 172 / OpenCode `1.18.19` | `completed`, zero changes, 44 contiguous unique receipts, `run.completed` | 5 raw chunks / 2684 bytes; archive 10271 bytes, SHA-256 `4deaf236b5c37e689654cd276b98467b31a33843438d62895426b1248c22ce7e` |
| 404 | Claude / Provider 6 `opencode-pi` (`anthropic_messages`) | 171 / Claude `2.1.153` | `completed`, zero changes, 22 contiguous unique receipts, `run.completed` | 8 raw chunks / 8619 bytes; archive 7034 bytes, SHA-256 `fa8ec7d9a70eae75ba7093801a7e0ef62fddaa06c1b3a228eb0c4b323c2fe543` |
| 405 | Codex / Provider 12 `openrouter-minimax-responses` (`openai_responses`) | 173 / Codex `0.146.0` | `completed`, zero changes, 18 contiguous unique receipts, `run.completed` | 6 raw chunks / 2683 bytes; archive 4278 bytes, SHA-256 `2f1a795687359133b4df091af7193d37148e75767e2525b5361ef467406bab0e` |

For all five follow-up Tasks, the persisted attempt used
`codify.worker.event/v2`, had one terminal event, zero seq anomalies, and
distinct event IDs equal to receipt count. The immutable snapshots retained
Profile 4 / `v2-canary-0.6.11-four-harness`, Kit `0.6.12`, the current Worker
image digest, and the expected Bundle identity. The raw-log check found both
the `No changes made by Harness` marker and the successful completion banner
for every Task. Each explicit `docker ps -a --filter name=codify-401` through
`codify-405` query returned no container, and the post-run database query
reported zero active Tasks and zero Issue locks. Root capacity remained 61G
total / 59G used / 2.5G available (97%). The constrained token-like scan
returned zero matches in the raw logs for Tasks 400–405. Backend `/health`
remained healthy with Docker and database checks `ok`; both Backend and
Scheduler still reported `HARNESS_EXECUTION_MODE=dual_canary`.

Task 402 was created while validating the selector and intentionally remains
an alternate Provider 7 sample; it is not presented as Provider 12 evidence.
The core legal current-Provider matrix is Task 400 (Pi), Task 403 (OpenCode),
Task 404 (Claude), and Task 405 (Codex). No real mobile-device acceptance,
Mattermost delivery, migration 078, release-owner sign-off, or R4.6/R5
decision is claimed by this follow-up.

## 2026-09-05 continuation: Mattermost 10.9.1 real delivery

The previously missing real-notification check was completed on the same
development Host. This is an additional R4.4 evidence sample; it does not
change the frozen Task-ID 380–394 integrity cohort and is not an R4.6 or L5
approval.

### Mattermost deployment and connection evidence

The Host now runs an independent Mattermost debug stack:

| Item | Result |
| --- | --- |
| Mattermost image | `mattermost/mattermost-team-edition:10.9.1`, repo digest `sha256:445ef98396678f3d4e269e05e11738e7a808e54c414db24625a855c37b5f978b` |
| Containers | `codify-mattermost` and independent `codify-mattermost-db` (`postgres:16-alpine`); both running and healthy |
| Isolation | Dedicated `codify-mattermost-debug` Docker network and named volumes; the existing `codify-postgres` was not touched |
| Endpoint | `0.0.0.0:8065 -> Mattermost:8065`; remote `/api/v4/system/ping` returned `status=OK` |
| Codify connection | Authenticated Codify admin UI connection test passed; profile `V2 live notifications` was created for `codifydebug/notifications`, with only `task_completed` enabled |
| Direct Bot smoke | Mattermost returned HTTP 201 for a separate direct Bot post (`Codify V2 Mattermost direct smoke`) |

The Bot token and generated admin/database credentials are kept only in the
remote debug directory under mode-600 files. They are not committed, copied
into the repository, or included in this evidence.

### Real Codify completion delivery

Task 406 was created from Issue #99 with Profile 4, Provider 12
`openrouter-minimax-responses`, the OpenCode Harness, `openai_responses`, a
fresh session, and `plan`/analysis mode. It was intentionally read-only and
completed with zero changes:

| Item | Result |
| --- | --- |
| Task/runtime | Task 406, `completed`, `total_changes=0`, input/output tokens `1691/987` |
| Composition | Bundle 172; OpenCode CLI `1.18.19`, Adapter `2.0.0`, event schema `codify.worker.event/v2` |
| Attempt | `task-406-attempt-1-6ae3171267eb`, `last_seq=82`, terminal `run.completed`, `control_state=closed` |
| Receipts | 82 receipts, seq 1–82 contiguous, 82 distinct seq values and 82 distinct event IDs |
| Persistence | 5 raw-log chunks / 2772 bytes; archive `task-406-runtime-archive.tar.gz`, 23219 bytes; Worker container and Issue lock were absent after completion |
| Codify delivery row | `mattermost_notification_deliveries.id=2`, `event_type=task_completed`, `status=success`, target `channel:aaz68niiuff3txfot5wjrgj33e` |
| Mattermost delivery | Bot post `5pksuyef73nbjxfphqkxuxw1de` appeared in `codifydebug/notifications` with the Task 406 completion card and task/project/status/link fields |

The real post rendered the task link from the existing remote
`FRONTEND_URL=http://frontend.example.test:8880`, while the direct target Host
URL is `http://192.168.50.129:8880`. The target IP route returned HTTP 200; the
example-host URL did not produce a usable page in the remote check. This is a
development deployment URL follow-up, not a Mattermost transport failure, and
must be corrected or explicitly accepted before release sign-off.

The final database/Service recheck reports 374 Tasks, zero pending/queued/
running Tasks, zero Issue locks, one enabled Mattermost profile, and one
successful Task 406 delivery. Backend remained healthy and Scheduler remained
in `dual_canary`; no `codify-406-issue99` container remained.

### Current Host boundary

After pulling Mattermost 10.9.1, the remote root filesystem reports roughly
`61G` total / `60G` used / `1.2G` available (`99%`). Docker reports 26 images,
11 running containers, 18 volumes, and 7.487GB reclaimable BuildKit cache.
The Host has not reached a full-disk trigger, so no further Codify image/cache
cleanup was performed in this continuation; the active `quirky_allen` Worker
image and unrelated services were not touched. If the filesystem reaches the
authorized cleanup boundary, repeat the ancestor-container checks and remove
only unreferenced Codify debug images/cache.

This closes the prior “no real Mattermost delivery” evidence gap but does not
sign R4.4: the full alert/zero-P0-P1 review, URL configuration decision,
R4.5 migration/credential/release-owner checks, R4.6 independent go/no-go,
R5/L6, and real mobile-device keyboard/IME/notch/gesture-area acceptance
remain open. The mobile-device acceptance remains explicitly deferred per the
user's instruction.

## 2026-09-05 continuation: development URL rebind and Task 407

The Task 406 message exposed the remote deployment's generic
`frontend.example.test` URL. With zero active Tasks and zero Issue locks, the
Backend and Scheduler were recreated using a temporary Compose override that
set `FRONTEND_URL=http://192.168.50.129:8880`. The repository's generic
`deploy/.env.test` template was not modified. The resulting containers report
the corrected URL, `HARNESS_EXECUTION_MODE=dual_canary`, and
`AUTO_MIGRATE=false`; the database remained at `077_v2_worker_kit_identity`.
Mattermost and its separate database were not recreated.

Task 407 was then created from Issue #99 using Profile 4, Provider 12
`openrouter-minimax-responses`, OpenCode with `openai_responses`, fresh-session
plan mode, and a read-only prompt. It completed with zero changes:

| Item | Result |
| --- | --- |
| Task/runtime | Task 407, `completed`, `total_changes=0`, input/output tokens `156/933` |
| Attempt | `task-407-attempt-1-65dc647fb191`, `codify.worker.event/v2`, OpenCode Adapter `2.0.0`, CLI `1.18.19`, `last_seq=472`, `run.completed`, `closed` |
| Receipts | 472 receipts, seq 1–472 contiguous, 472 distinct seq values and 472 distinct event IDs |
| Persistence | 5 raw-log chunks / 2725 bytes; runtime archive 50223 bytes; no `codify-407-issue99` container remained |
| Codify delivery row | `mattermost_notification_deliveries.id=3`, `event_type=task_completed`, `status=success` |
| Mattermost delivery | Bot post `oghjj97rmf8apm7oymcuetbjto` rendered `http://192.168.50.129:8880/tasks/407` in `codifydebug/notifications` |

This resolves the current development Host's task-link defect and confirms
the URL override through a real AI-backed task. The override is deployment
state rather than a portable repository-template change, so future recreates
must explicitly supply the target deployment's frontend URL.

The V2 frozen integrity cohort remains unchanged. Formal zero-P0/P1 review,
R4.5 owner/security/release evidence, R4.6 independent go/no-go, migration 078,
R5/L6, and real mobile-device keyboard/IME/notch/gesture-area acceptance remain
open; mobile-device acceptance is explicitly deferred by the user.

## 2026-09-05 continuation: remote four-Harness Kit verify

The installed current candidate was verified directly on the Docker daemon
Host, without creating a Codify Task or changing the database. The command
used the exact installed Kit
`/opt/codify/worker-kits/0.6.12-linux-amd64-c33dbf86951b`, the Worker image
repo digest
`127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`,
and the Kit's trusted `verify-kit-content.py` verifier. The no-runtime-manifest
path enumerated all four present Kit inventory keys.

| Harness | CLI version | Result |
| --- | --- | --- |
| Claude | `2.1.153` | `Worker kit verification passed` |
| Codex | `0.146.0` | `Worker kit verification passed` |
| OpenCode | `1.18.19` | `Worker kit verification passed` |
| Pi | `0.84.2` | `Worker kit verification passed` |

Every run reported content inventory
`7630f086800c95f851db8c9351638868ab60ac33fb3bfe22f9f2f5c8dcdc98a1` and the
remote image was `linux/amd64` with image ID
`sha256:b07ac48b129c35876c044079f8e9cd7aa7558dbb0ade2e50e856d4ab980f5e71`.
The single all-present invocation exited 0. Its temporary `docker run`
containers were removed by `--rm`; no Codify service or Task container was
changed. The Host remains in `dual_canary`; this strengthens current L3/R4.2
evidence but does not provide release-owner or independent R4.6 approval.

## 2026-09-05 continuation: post-fix real cancellation notification

The real Mattermost stack was kept in place and a second notification profile
was created through the Codify admin UI:

| Item | Result |
| --- | --- |
| Profile | `V2 failure/cancel notifications` (profile 3), enabled, channel target `codifydebug/notifications` |
| Events | `task_failed` and `task_cancelled` only; completion remained subscribed only by the existing profile 2 |
| Backend/Scheduler | Rebuilt from commit `594bf67a` as image `sha256:92321ff20bda74088b44a9c1410d5688399c44f15d78007b58e0068aaf07d7a3`, `dual_canary`, `AUTO_MIGRATE=false`, database revision `077_v2_worker_kit_identity` |

### Task 408 exposed the lifecycle gap

Task 408 was created from Issue #99 with the existing legal Provider 12
`openrouter-minimax-responses`, OpenCode, a fresh session, freeform mode, and
the controlled `sleep 180` prompt. The operator cancelled while the Bash
command was running. The task ended `cancelled`, but the cancellation API's
Phase B re-read still saw `RUNNING` with the Worker container present; the
Worker finalizer converged the row afterwards. The existing route-side
notification condition therefore did not run, and Task 408 had no delivery
row. This was classified as a lifecycle gap, not a Mattermost transport
failure.

Commit `594bf67a` fixes the ownership boundary: PENDING/QUEUED cancellations
remain notified by the API, while a RUNNING cancellation is notified once by
the Worker finalizer after it persists the terminal state. The API no longer
duplicates the notification if the Worker wins the Phase B race. The focused
regression run passed 114 tests with 19 subtests, and focused Ruff passed.

### Task 409 post-fix live cancellation

Task 409 repeated the same controlled real task after the new Backend/Scheduler
image was deployed. It used Provider 12 `openrouter-minimax-responses`
(`minimax/minimax-m3:free`), OpenCode with `openai_responses`, a fresh session,
and freeform mode. The operator cancelled after the real `sleep 180` command
had started:

| Item | Result |
| --- | --- |
| Task/runtime | Task 409, `cancelled`, `MessageAbortedError: Aborted`, zero changes, 0 input / 0 output tokens |
| Attempt | `task-409-attempt-1-19c54ef331b9`, `codify.worker.event/v2`, OpenCode Adapter `2.0.0`, CLI `1.18.19`, `last_seq=9`, terminal `run.failed`, `control_state=closed` |
| Receipts | 9 receipts, seq 1–9 contiguous, 9 distinct event IDs |
| Persistence | 4 raw-log chunks / 2550 bytes; no `codify-409-issue99` container remained; no Issue lock remained |
| Codify delivery row | `mattermost_notification_deliveries.id=4`, `event_type=task_cancelled`, `status=success`, target `channel:aaz68niiuff3txfot5wjrgj33e` |
| Mattermost delivery | Bot post `ughpc5bd63dz8y9fz7exdc4kee` appeared in `codifydebug/notifications` as `@root 🛑 任务已取消 · [任务 409](http://192.168.50.129:8880/tasks/409)` |

The delivery query found exactly one successful `task_cancelled` row and the
Mattermost channel query found one matching post. The post therefore proves
the real API → Codify delivery log → Mattermost 10.9.1 path after Worker
finalization, including the corrected development Host URL. Task 409 is an
additional R4.4 operational sample and is not added to the frozen Task-ID
380–394 integrity cohort.

The final Host recheck reported 377 total Tasks, zero pending/queued/running
Tasks, zero Issue locks, no Task 409 container, healthy Backend/Scheduler, and
`dual_canary`. The root filesystem was approximately `61G` total / `60G` used /
`1.4G` available (`98%`); Docker reported 27 images, 11 containers, and
6.992GB reclaimable BuildKit cache. The Host had not reached the full-disk
cleanup trigger, so no further Codify image/cache cleanup was performed and
active/unknown Worker images and protected services were not touched.

At the Task 409 checkpoint this closed the real completion and cancellation
notification evidence gap; the live `task_failed` path was still pending at
that point. The continuation below records that separate failure sample. This
does not by itself provide R4.4 sign-off, R4.5 owner or security approval, R4.6
independent go/no-go, migration 078, R5/L6, or the real mobile-device
keyboard/IME/notch/gesture-area acceptance that remains explicitly deferred by
the user.

## 2026-09-05 continuation: real `task_failed` notification

Task 410 was created from Issue #99 using the existing Provider 4
`opencode-luna` (`gpt-5.6-luna`), the Codex Harness, and the legal
`openai_responses` protocol. The prompt was intentionally read-only and asked
the task to preserve an upstream provider failure without retrying or making
repository changes. The enabled profile was `V2 failure/cancel notifications`
(profile 3), targeting `codifydebug/notifications` and subscribed only to
`task_failed` and `task_cancelled`.

The real Provider request failed at the known upstream availability boundary
with HTTP 403 `unsupported_country_region_territory`:

| Item | Result |
| --- | --- |
| Task/runtime | Task 410, `failed`; canonical failure kind `engine_error` |
| Attempt | `task-410-attempt-1-54e3bd239521`, `codify.worker.event/v2`, Codex Adapter `1.0.0`, CLI `0.146.0`, `last_seq=12`, terminal `run.failed`, `control_state=closed` |
| Canonical failure | seq 10 `harness.failed`, seq 12 `run.failed`; the bounded message included the upstream 403 and `unsupported_country_region_territory` |
| Receipts | 12 receipts, seq 1–12 contiguous, 12 distinct event IDs |
| Persistence | 5 raw-log chunks / 2458 bytes; runtime archive `task-410-runtime-archive.tar.gz`, 3335 bytes; no active Task or Issue lock remained |
| Codify delivery row | `mattermost_notification_deliveries.id=5`, `event_type=task_failed`, `status=success`, target `channel:aaz68niiuff3txfot5wjrgj33e` |
| Mattermost delivery | Bot post `4bw9czpbpfbuznzuj33ftj6ara` appeared in `codifydebug/notifications` as `@root ❌ 任务失败 · [任务 410](http://192.168.50.129:8880/tasks/410)` |

The Task reached its terminal state without a container or Issue lock left
behind. The delivery query found one successful `task_failed` row, and the
Mattermost channel query found one matching Bot post. Together with Tasks 406,
407, and 409, this proves the real completion, cancellation, and failure
notification paths through the Codify delivery log into Mattermost 10.9.1,
including the corrected development Host URL. Task 410 is an additional R4.4
operational sample and is not added to the frozen Task-ID 380–394 integrity
cohort.

The final recheck reported 378 total Tasks, zero pending/queued/running Tasks,
zero Issue locks, healthy Backend and Scheduler services, database revision
`077_v2_worker_kit_identity`, and `dual_canary`. Docker reported 27 images, 11
containers, and 6.992GB reclaimable BuildKit cache. The latest direct Host
filesystem check remained approximately `61G` total / `60G` used / `1.4G`
available (`98%`); the full-disk cleanup trigger was not reached, so no Codify
image/cache cleanup was performed and active/unknown Worker images and
protected services were not touched.

This closes the previously missing live failure-notification evidence sample,
but not formal R4.4 sign-off, the R4.5 owner/security/release audit, R4.6
independent go/no-go, migration 078, R5/L6, or the real mobile-device
keyboard/IME/notch/gesture-area acceptance that remains explicitly deferred.
