# Open-Harness V2 R4.5 Security and Release Audit

**Date:** 2026-09-05

**Scope:** Current development Host `192.168.50.129`, the exact committed R4
candidate, and repository-side release checks. This is an audit record, not a
security approval or an independent R4.6 go/no-go decision.

The prior Profile-4 candidate was superseded after runtime commits `8110afa0`
and `810f9fcb` changed the Codex and Pi Adapter projections. The exact
composition was initially rebuilt from committed tree `40235196` and deployed
as Backend/Scheduler image `sha256:0ea2d9832fc0c7b3ca893b62f52a4f75fc54c56ed0bc80d732b08c95f5628c20`.
Commit `48b16fdc` then fixed Scheduler cancellation log classification; the
current Backend/Scheduler image is
`sha256:334c674db035dd9e5ab63d96918c0af19a680387db4afcecef52a8b2f4d575bb`.
It exposes no Git revision OCI label, so the current image provenance is the
committed tree plus the remote build/deploy record. Profile 4 remains
generation `74`, and its exact-composition selected-Harness Bundles are 170
(Pi), 171 (Claude), 172 (OpenCode), and 173 (Codex); Tasks 380–383 and post-fix Tasks 388–394
validation are recorded in the
[R4.3/R4.4 live Host evidence](2026-09-04-open-harness-v2-r4.3-r4.4-live-host.md).
The generation-73 Bundles 166–169 and Tasks 374–379 remain historical evidence
for the preceding image composition. Tasks 369 and 370 were additional negative backend-restart probes on the
preceding Codex-selected Bundle; both were bounded as upstream `rate_limited`.
Task 371 then completed on the preceding OpenCode-specific Bundle 164 during a
controlled nginx-only disconnect/reconnect spot-check, and Task 372 completed
a stable-state cancellation on that same Bundle. Current Task 377 was an
upstream 429, Task 378 an upstream 403 region restriction, and follow-up Task
379 again hit an upstream 429; these are Host evidence, not a security or
release-owner approval.

## Checks completed

| Check | Result | Boundary |
| --- | --- | --- |
| `python3 scripts/harness-probes/v2/secret-scan.py` | passed, `findings=0` | Repository candidate only; it does not replace a Provider/GitLab access audit |
| `backend/.venv/bin/python -m pytest backend/tests/unit/test_codex_harness_adapter.py -q` | passed, 33 tests | Covers the post-fix Codex `OPENAI_MODEL` projection and V2 envelope/result mapping |
| `backend/.venv/bin/python -m pytest backend/tests/unit/test_pi_harness_adapter.py -q` | passed, 54 tests | Covers active-session projection when Pi emits startup `get_state` before `new_session` acknowledgement |
| `backend/.venv/bin/python -m ruff check deploy/worker-entrypoint/harness/adapters/pi_events.py backend/tests/unit/test_pi_harness_adapter.py` | passed | Focused lint for the Pi runtime fix |
| Affected Bundle/Profile/Scheduler/notification/freeform regression set | passed, 227 tests | Re-checks the source/binding/runtime paths affected by the post-fix candidate |
| `backend/.venv/bin/python -m pytest backend/tests/unit/test_scheduler_coverage.py -q` | passed, 64 tests | Covers the post-fix cancellation log classification |
| Focused Ruff for Scheduler change | passed | Validates the cancellation log classification change |
| Backend focused regression | passed, 39 `test_issues_api.py` tests | Covers the current `task_mode` serialization fix |
| Frontend unit suite | passed, 80 files / 1692 tests | Includes structured SSE stale-source and mobile safe-area regression coverage |
| Frontend production build | passed | Vite emitted only the existing large-chunk warning |
| Backend lint | passed | `make lint-backend` |
| Remote Docker state | cleaned after full-disk trigger | The new Kit build briefly left the root filesystem at 100% with about 413MB available. After checking every target with `docker ps -a --filter ancestor=<image>`, a scoped cleanup removed unreferenced Codify Kit-export/Backend/Frontend/test/mock images, 29 dangling Codify layers, and BuildKit cache older than one hour. Final `df -h /` is 61G total / 59G used / 2.5G available (97%); Docker reports 25 Images / 10.12GB, 9 containers, 1.643GB volumes, and 7.487GB remaining reclaimable BuildKit cache. Running services, volumes, GitLab/DB/Redis and unrelated images were not touched. |
| Current Kit archive reconstruction and V2 release preflight | passed, not signed | The installed `0.6.12-linux-amd64-c33dbf86951b` Kit was streamed into a temporary `518M` archive; archive SHA-256 `2d3ee7f81525d465731344571cbf5bd93a0cd94bb6cf16f5a4d5512d5c0a25a6`, manifest SHA-256 `c33dbf86951bed6e3b4de1897313725f14f00006dc51fb300e7b821bb47e17bd`, content inventory `7630f086800c95f851db8c9351638868ab60ac33fb3bfe22f9f2f5c8dcdc98a1`; `deploy/scripts/preflight-v2-release.sh` passed against the target daemon and Worker image repo digest `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`. The temporary archive is not a release-owner-signed package and is not committed. |
| Exact committed image/Profile/Task recheck | passed with bounded Provider outcomes plus separate V1 evidence | Backend/Scheduler now run image `sha256:334c674d…` built after `48b16fdc`; Profile 4 generation 74 completed four-Harness Verify; Tasks 380–383 completed Pi/Claude/OpenCode/Pi on unchanged Bundles 170–172 with 397 unique contiguous receipts and zero changes. Current exact OpenCode/Pi/Claude cancellation Tasks 384–386 on the prior Backend image added 15/40/8 receipts; post-fix Task 387 on Bundle 171 / Provider 11 added 9 unique contiguous receipts, one `run.failed(status=cancelled)` terminal, zero changes, a 4594-byte archive (`69e8a1df…`), 6 raw-log chunks / 5117 bytes, and a removed Worker container. Post-fix Task 388 on the same Bundle/Provider completed with 19 unique contiguous receipts, `run.completed`, zero changes, a 7586-byte archive (`27852b5a…`), 7 raw-log chunks / 8486 bytes, and a removed Worker container; Task 389 on Bundle 171 / Provider 6 completed with 20 unique contiguous receipts, `run.completed`, zero changes, a 7236-byte archive (`439f3132…`), 6 raw-log chunks / 8359 bytes, and a removed Worker container; Task 390 on Bundle 172 / Provider 6 completed with 216 unique contiguous receipts, `run.completed`, zero changes, a 22384-byte archive (`d54b5eb2…`), 4 raw-log chunks / 2678 bytes, and a removed Worker container; Task 391 on Codex Bundle 173 / Provider 4 reached the Adapter and ended with 12 unique contiguous receipts, one `run.failed(status=failed, failure.kind=engine_error)` terminal, zero changes, a 3314-byte archive (`db05ea24…`), 4 raw-log chunks / 2393 bytes, and a removed Worker container after upstream `403 unsupported_country_region_territory`; Task 392 on the same Codex Bundle 173 / Provider 12 completed with 14 unique contiguous receipts, `run.completed`, zero changes, a 3980-byte archive (`9afe4f3f…`), 5 raw-log chunks / 2733 bytes, 21030/137 usage, and a removed Worker container; Task 394 on Pi Bundle 170 / Provider 12 completed with 74 unique contiguous receipts, `run.completed`, zero changes, an 8974-byte archive (`2ffe9f76…`), 3 raw-log chunks / 2727 bytes, 139/118 usage, and a removed Worker container. The separate V1-compatible Kit/Profile 5 path then completed Task 399 on Bundle 174 with 14 V1 receipts, zero changes, a 3796-byte archive, and a removed Worker container. The new Scheduler emitted one `Task 387 cancelled` INFO with no `Task 387 failed`, successful INFO lines for Tasks 388/389/390/392/394/399, and one bounded failure for Task 391; V2 integrity statistics remain separate from Task 399. |
| Profile re-verification and prior post-fix smoke | passed with bounded Provider negatives | Profile 4 generation 73 and Tasks 374–379 remain historical evidence for the superseded image composition; Tasks 374–376 completed Pi/Claude/OpenCode on Bundles 166–168, while Codex Tasks 377–379 reached the Adapter and were correctly bounded as upstream `rate_limited`/`engine_error`; Task 368 remains the preceding-generation Codex success |
| GitLab integration connectivity | passed, not a permission sign-off | The authenticated admin UI read-only connection test reached `http://192.168.50.129:8080`, authenticated as `ai-bot`, and reported GitLab `18.5.5-ee`; the Webhook overview currently returned zero projects. This proves application connectivity/identity only, not token scope, least privilege, or rotation. |
| Remote execution mode | restored and healthy | After Task 399 completed, Backend and Scheduler were temporarily recreated with `HARNESS_EXECUTION_MODE=v2_only`; both health endpoints agreed, and authenticated Task399 detail rendered `Legacy V1 · 只读` with summary/events/logs/statistics. No task was created or mutated. Services were restored to `dual_canary`; final preflight agrees and reports Backend healthy. No hard-cut or migration was attempted. |

The remote image/cache state was inspected before and after the live smoke and
again after the frontend nginx-only deployment. During the V1 Kit build the
filesystem reached 100%, so the explicitly scoped Codify cleanup described in
the table above was performed. No protected service, volume, GitLab/DB/Redis
image, or unrelated image was touched.

The current remote recheck also returned Backend health `healthy` with database
and Docker checks `ok`, and confirmed `HARNESS_EXECUTION_MODE=dual_canary`.
The frontend-only commit `a6be3f8b` was deployed through the `remote` Docker
context with nginx-only rebuild/recreate; the served `index.html` contains
`viewport-fit=cover`, while backend, scheduler, and database containers were
not recreated. The authenticated browser page loaded the mobile safe-area
rules, but its desktop viewport cannot establish real mobile keyboard or notch
behavior.

The current installed Kit was also streamed without modifying the Host into a
temporary content-addressed archive and passed the repository's V2 release
preflight against the remote daemon. The archive checksum, manifest/content
inventory, and Worker image platform/repo digest were all verified. This is
reproducibility evidence for the frozen Kit, not release-owner approval: the
archive is temporary and there is no signed package or approved release note
attached to this audit.
The pre-Mattermost database checkpoint had 367 Tasks, zero
`pending`/`queued`/`running` Tasks, zero `issue_execution_locks`, zero
Mattermost notification profiles, and zero notification deliveries. Five new
V1 snapshots belonged to Tasks 395–399;
the other 362 Task Worker Profile Snapshots have
`runtime_contract_version=codify.worker.harness/v2`. These are current Host
observations; they do not replace the missing live alert delivery or
independent release sign-off.

The current development-Host Provider inventory was checked without reading
credentials or URL paths: enabled Providers 3–6 resolve to `opencode.ai`, and
enabled Providers 7–12 resolve to `openrouter.ai`; the only fixture entry,
Provider 13, is disabled. No enabled local-only Provider is available. This is
an endpoint inventory for the release audit, not a least-privilege approval.
Task 371 used Provider 7 only as an explicitly authorized development
diagnostic; it does not establish production authorization, rotation, or
external destination approval.

The application-level GitLab connection test succeeded with the effective
stored configuration, but no token scope or rotation metadata is exposed by
that test. The successful identity check therefore remains a connectivity
observation only; the release owner still must provide the least-privilege and
rotation record.

The current live evidence covers Pi, OpenCode, Claude, and Codex on Profile 4,
including exact-composition successful Tasks 380–383 and post-fix Tasks 388–390,
392, and 394, current exact-composition Codex negative Task 391, generation-73 successful
Tasks 374–376, the generation-73 Codex negative Tasks 377–379, the
preceding-generation Codex success Task 368, the OpenCode reconnect Task 371,
the stable-state cancellation Task 372, and the negative restart probes
369/370. The known non-success outcomes were
correctly bounded as upstream/provider availability failures (`rate_limited`,
selected-model `engine_error`, region-blocked `engine_error`, or the earlier
real upstream 404). The detailed task, identity, archive, raw-log, and
canonical-sequence evidence is in the
[R4.3/R4.4 live Host evidence](2026-09-04-open-harness-v2-r4.3-r4.4-live-host.md).

## Items that cannot be signed from this workspace

The following R4.5 inputs remain explicit release-owner evidence rather than
claims inferred from tests or a development Host:

1. **Provider/GitLab least privilege and rotation.** The repository contains a
   restricted legacy credential-delivery acceptance: the Worker runtime still
   receives the encrypted Provider key as a task environment value, while the
   `credential_ref` resolver is not yet the runtime delivery path. This is
   accepted only for trusted internal/development Profiles and is not a
   production or untrusted-repository security pass. The current Provider and
   GitLab permission scope, rotation timestamp, and revocation/rollback record
   must be supplied by the credential/system owner.
2. **Release notes and exact release package.** The current commits and R4
   candidate evidence are recorded, but no release-owner-approved release
   notes or signed package manifest has been attached to this audit.
3. **Old Kit/image retention and retirement.** The full-disk debug cleanup
   removed only explicitly checked, unreferenced Codify images/layers and old
   BuildKit cache. The remote daemon still has reclaimable images/cache, but no
   retirement date, retention owner, or approved long-term deletion list is
   recorded; future cleanup must remain scoped and owner-reviewed.
4. **Maintenance window and ownership.** No approved R5 window, migration
   owner, rollback owner, or observation window is recorded here. These values
   must not be invented from the development run.
5. **P0/P1 and independent approval.** No independent reviewer has signed the
   complete R4.3–R4.5 checklist. The upstream availability failures are not
   P0/P1 evidence by themselves, but they also do not constitute a formal
   zero-blocker sign-off.

The current development candidate records the Scheduler-only post-fix image
`sha256:334c674d…` built after committed tree `48b16fdc`; unlike the previous
image, it has no Git revision OCI label. The Worker/Kit/Profile/Bundle identity
remains unchanged, and Tasks #387–#390 are direct real-Provider evidence on
this new image. This closes the observed cancellation log-classification
defect and adds current success-path samples, but does not create a
release-owner signature: the package manifest, release notes, retention plan,
and independent approval remain open.

## R4.5 conclusion

**Partial evidence, not signed.** Repository secret scanning, local regression,
remote-state checks, and exact committed artifact provenance pass. Provider/
GitLab authorization and rotation, release notes, retention/retirement,
maintenance ownership, and independent zero-P0/P1 approval remain open. R4.6
therefore has no recorded decision, and the system must remain in
`dual_canary`.

## Latest read-only recheck

At `2026-09-04T15:03:49Z`, the target Host still reported a healthy Backend,
`dual_canary`, and no new task after the generation-73 smoke cohort. The
enabled Provider inventory was unchanged: the Codex-legal
`openai_responses` entries remain Providers 4, 9, and 12; Provider 4 is the
known region-blocked endpoint, Provider 9 has a prior rate-limit result, and
Provider 12 has the current generation-73 429 result. No new legal Provider
was available, so no additional Codex Task was created against a known
restricted endpoint.

The same recheck found Tasks 374–376 `completed` and 377–378 `failed`. The
generation-73 cohort then contained five attempts and 111 receipts, with 111
unique event IDs and exactly one `run.completed` or `run.failed` receipt per
attempt; every attempt's `last_seq` equals its receipt count. Host disk usage
was 57G/61G (94%) with 4.1G available and 19% inode usage. Docker reported
81 images, 8 active images, and 6.706GB reclaimable BuildKit/image space;
because the filesystem is not full, no Codify image/cache cleanup was
performed.

At `2026-09-05T00:30:29Z`, the controlled follow-up against the now-aged
Provider 9 created Task 379 on Bundle 169. It resolved the selected Codex model,
persisted eight contiguous canonical receipts, and ended with the expected
upstream HTTP 429 `run.failed(failure.kind=rate_limited)` and zero changes.
The generation-73 cohort now contains six attempts and 119 receipts: three
completed (Tasks 374–376) and three bounded Provider failures (Tasks 377–379).
Provider 4 remains region-blocked, and no additional Codex-legal Provider with
a credible availability signal was available for another retry.

At `2026-09-05T00:54:07Z`, the exact committed composition recheck converged
Tasks 380–382 to `completed`: Pi/Provider 7 on Bundle 170, Claude/Provider 11
on Bundle 171, and OpenCode/Provider 7 on Bundle 172. Their attempts have
Adapter/CLI identities `2.1.0/0.84.2`, `1.0.1/2.1.153`, and `2.0.0/1.18.19`,
respectively; they contain 44, 17, and 40 unique contiguous receipts, each
ending in `run.completed`, with zero changes. There are zero active Tasks and
zero Issue execution locks. Profile 4 Verify is generation 74, and the
Backend/Scheduler image is the exact `40235196` image recorded above.

The real mobile-device keyboard/IME/notch/gesture-area acceptance is
temporarily deferred per user instruction. The desktop browser and served
safe-area artifact remain evidence only; no device-level acceptance claim is
recorded in this audit.

At `2026-09-05T01:08:52Z`, a further read-only Provider/Host recheck found no
new Codex-legal availability signal: enabled `openai_responses` rows remain
Providers 4 (`opencode-luna`), 9 (`openrouter-glm52-responses`), and 12
(`openrouter-minimax-responses`); Provider 13 remains a disabled fixture. The
recent real outcomes for these endpoints remain the previously recorded
region-blocked 403 or upstream 429 classifications, so no duplicate Codex
Task was created. Backend/Scheduler stayed healthy in `dual_canary`; remote
root remained at 4.2G available / 94% used with no cleanup trigger.

At `2026-09-05T01:11:39Z`, the exact-composition smoke added Task 383 using
Provider 6 (`opencode-pi` / `deepseek-v4-flash`) and Pi's
`anthropic_messages` protocol. It completed on the existing Pi Bundle 170
variant with Adapter `2.1.0`, CLI `0.84.2`, model `deepseek-v4-flash`, session
`01a06f1e-924a-771a-b12b-46fa2a1a7389`, 96 input / 181 output tokens, four raw
log chunks, zero changes, and 296 unique contiguous receipts (seq 1–296)
ending in `run.completed`. The two early `control_owner_unreachable`
gate-probe warnings self-recovered; the task and attempt remained successful.
The exact-composition cohort then contained four attempts and 397 unique
contiguous receipts. Task 388 later added a fifth successful attempt with 19
receipts, Task 389 added a sixth with 20 receipts, Task 390 added a seventh
with 216 receipts, Task 392 added an eighth with 14 receipts, and Task 394
added a ninth with 74 receipts, for 740 unique contiguous receipts across the
current success cohort. Task 391 is
separate negative evidence: its Codex attempt on Bundle 173 reached the
Adapter and was bounded by Provider 4's upstream
`403 unsupported_country_region_territory` response; Task 392 then completed
the same Bundle through Provider 12.
Backend health remained `healthy` with database/Docker
checks `ok`, Scheduler remained in `dual_canary`, and no active Task or Issue
lock remained.

The later current-composition integrity recheck covered the Task-ID 380–394
range (Task 393 has no Task row), including the cancellation attempts, the
Codex negative sample, and the Codex success samples: 14 attempts contained
824 receipts and 824 distinct event IDs,
with zero sequence/ID failures, zero terminal-count
failures, and zero task-status/terminal-type mapping failures. The constrained
token-like scan returned zero matches in both canonical event JSON and raw-log
chunks.

At `2026-09-05T01:22:46Z`, the current exact-composition cancellation sample
Task 384 (OpenCode / Provider 7 / Bundle 172) was cancelled while its read-only
`sleep 180` command was running. The task row ended `cancelled` with
`MessageAbortedError: Aborted`; the attempt used Adapter `2.0.0` / CLI
`1.18.19`, closed with 15 unique contiguous receipts (seq 1–15), and persisted
`harness.failed(failure.kind=cancelled)` →
`worker.finalization(exit_code=143)` →
`run.failed(status=cancelled, failure.kind=cancelled)`. It produced zero
changes, four raw-log chunks / 3215 bytes, and the archive
`task-384-runtime-archive.tar.gz` at 7039 bytes with SHA-256
`59c56212165eee79e67dc0772c973e26e0bad3c949169740ba442db53d8c9e86`.
The container was removed and the Issue lock count returned to zero. The
canonical tail's post-exit Docker 409 was recorded as a non-blocking cleanup
warning because the canonical cancellation receipts had already been
persisted.

At `2026-09-05T01:31:06Z`, the Pi cancellation sample Task 385 completed on
Bundle 170 with Provider 6 (`opencode-pi` / `deepseek-v4-flash`). The task row
ended `cancelled` with `Cancelled by user`; its Adapter/CLI identity was
`2.1.0`/`0.84.2`, and the attempt closed with 40 unique contiguous receipts
(seq 1–40) in the same cancellation chain. It produced zero changes, three
raw-log chunks / 5659 bytes, and archive
`task-385-runtime-archive.tar.gz` at 6547 bytes with SHA-256
`b742525261e4cc6f75fb02b7308310e0dfd12f9c6cce0e33aaef8a70005d5f4d`.
The container was removed and active attempt / Issue lock counts remained zero.

At `2026-09-05T01:37:21Z`, the Claude cancellation sample Task 386 completed
on Bundle 171 with Provider 11 (`openrouter-minimax-anthropic` /
`minimax/minimax-m3:free`). The task row ended `cancelled` with `Cancelled by
user`; its Adapter/CLI identity was `1.0.1`/`2.1.153`, and the attempt
`task-386-attempt-1-7ab79696e2c1` closed with 8 unique contiguous receipts
(seq 1–8) in the same cancellation chain. It produced zero changes, five
raw-log chunks / 6904 bytes, and archive
`task-386-runtime-archive.tar.gz` at 4980 bytes with SHA-256
`a9dead4511a125904fd12e5bd960350cb8a72f2990251c6aff411d3082b8fa6a`.
The container was removed and no active Task or Issue lock remained. The
post-exit canonical-tail 409 was non-blocking because the persisted
cancellation receipts and archive were complete. Scheduler emitted its
generic `Task 386 failed` error after cancellation; this did not alter the
database or canonical terminal state and remains an R4.4 alert-classification
review item.

At `2026-09-05T01:53:53Z`, post-fix Task 387 repeated the real Claude
cancellation diagnostic with Provider 11 and Bundle 171 after Backend/Scheduler
were rebuilt from `48b16fdc`. The task ended `cancelled` with `Cancelled by
user`; attempt `task-387-attempt-1-a3e1b350ae78` used Adapter `1.0.1` / CLI
`2.1.153`, closed with 9 unique contiguous receipts (seq 1–9), and had exactly
one terminal `run.failed(status=cancelled, failure.kind=cancelled)`. It
produced zero changes, 6 raw-log chunks / 5117 bytes, and archive
`task-387-runtime-archive.tar.gz` at 4594 bytes with SHA-256
`69e8a1df9a6c7ffce572b92c414ae9d1b38b5eb1cd057726425d28dce7a9427e`.
The Worker container and Issue lock were removed/cleared, global active Tasks
returned to zero, and Scheduler emitted one `Task 387 cancelled` INFO with no
`Task 387 failed` line. The expected post-exit canonical-tail 409 remained a
non-blocking warning after persistence was complete.

At `2026-09-05T02:06:51Z`, post-fix Task 388 completed the real Claude
read-only smoke with Provider 11 and Bundle 171 on the same image. The task
ended `completed` with zero changes; attempt
`task-388-attempt-1-7c1e218d55ee` used Adapter `1.0.1` / CLI `2.1.153`, closed
with 19 unique contiguous receipts (seq 1–19), and had one terminal
`run.completed(status=completed)`. It produced 7 raw-log chunks / 8486 bytes
and archive `task-388-runtime-archive.tar.gz` at 7586 bytes with SHA-256
`27852b5a58f264f0cd881030b9c44dc647fd0cf759df61c6421fba6112fb8acf`.
The Worker container and Issue lock were removed/cleared, global active Tasks
returned to zero, and Scheduler emitted one `Task 388 completed successfully`
INFO line. The expected post-exit canonical-tail 409 remained non-blocking
after receipt/archive persistence; the task detail page exposed the same
completed Claude/Provider/Worker identity and `+0 -0` result.

At `2026-09-05T02:31:50Z`, post-fix Task 389 completed a second real Claude
success smoke on Bundle 171 using Provider 6 (`opencode-pi` /
`deepseek-v4-flash`) over the legal `anthropic_messages` protocol. The task
ended `completed` with zero changes; attempt
`task-389-attempt-1-b514023e39e1` used Adapter `1.0.1` / CLI `2.1.153`, closed
with 20 unique contiguous receipts (seq 1–20), and had one terminal
`run.completed(status=completed)`. It produced 6 raw-log chunks / 8359 bytes
and archive `task-389-runtime-archive.tar.gz` at 7236 bytes with SHA-256
`439f313210aaf845aecdcdbf1b08c724fa5ec6b4dee8072664191dc9c29208d4`.
The Worker container and Issue lock were removed/cleared, global active Tasks
returned to zero, and Scheduler emitted one `Task 389 completed successfully`
INFO line. The authenticated task detail page exposed completed Claude,
Provider 6, the exact Worker image, 16 seconds, 2247 input / 597 output
tokens, and `+0 -0` changes. The expected post-exit canonical-tail 409 was
non-blocking after receipt/archive persistence.

At `2026-09-05T02:49:38Z`, post-fix Task 390 completed a real OpenCode
success smoke on Bundle 172 using Provider 6 (`opencode-pi` /
`deepseek-v4-flash`) over the legal `anthropic_messages` protocol. The task
ended `completed` with zero changes; attempt
`task-390-attempt-1-8414e97cc86d` used Adapter `2.0.0` / CLI `1.18.19`, closed
with 216 unique contiguous receipts (seq 1–216), and had one terminal
`run.completed(status=completed)`. It produced 4 raw-log chunks / 2678 bytes
and archive `task-390-runtime-archive.tar.gz` at 22384 bytes with SHA-256
`d54b5eb2e2a24b6e98d2614f9e249a10fd35d22ed6d91643924ff9191c68dd0e`.
The Worker container and Issue lock were removed/cleared, global active Tasks
returned to zero, and Scheduler emitted one `Task 390 completed successfully`
INFO line. The authenticated task detail page exposed completed OpenCode,
Provider 6, the exact Worker image, 46 seconds, 136 input / 128 output
tokens, and `+0 -0` changes. The expected post-exit canonical-tail 409 was
non-blocking after receipt/archive persistence.

At `2026-09-05T03:06:50Z`, current exact-composition Task 391 ran Codex with
Provider 4 (`opencode-luna` / `gpt-5.6-luna`) on Bundle 173 over the legal
`openai_responses` protocol. The task ended `failed` with zero changes; attempt
`task-391-attempt-1-b262994239a1` used Adapter `1.0.0` / CLI `0.146.0`, closed
with 12 unique contiguous receipts (seq 1–12), one terminal
`run.failed(status=failed, failure.kind=engine_error)`, and six provider
retries. The upstream response was `403 unsupported_country_region_territory`
from `https://opencode.ai/zen/go/v1/responses`; a separate unauthenticated
`/v1/models` reachability check returned 200, which is not treated as model
execution availability. It produced 4 raw-log chunks / 2393 bytes and archive
`task-391-runtime-archive.tar.gz` at 3314 bytes with SHA-256
`db05ea24b9d670b9d85d5aab58779fe17fd28ca2a058eb81f6dfc140b79d8e75`.
The Worker container and Issue lock were removed/cleared, and Scheduler logged
one bounded `Task 391 failed` ERROR. The authenticated task detail page showed
failed Codex, Provider 4, the exact Worker image, 20 seconds, no token usage,
and `+0 -0` changes. The expected post-exit canonical-tail 409 was non-blocking
after receipt/archive persistence.

At `2026-09-05T03:22:38Z`, current exact-composition Task 392 ran Codex with
Provider 12 (`openrouter-minimax-responses` / `minimax/minimax-m3:free`) on
Bundle 173 over the legal `openai_responses` protocol. The task completed with
zero changes; attempt `task-392-attempt-1-4a0143f634b7` used Adapter `1.0.0` /
CLI `0.146.0`, closed with 14 unique contiguous receipts (seq 1–14), and one
terminal `run.completed(status=completed, success=true)`. The read-only shell
inspection returned a clean `/workspace` on `codify/issue-99`, and the delivery
result had exit code 0 with no commit. Usage was 21030 input / 137 output
tokens. It produced 5 raw-log chunks / 2733 bytes and archive
`task-392-runtime-archive.tar.gz` at 3980 bytes with SHA-256
`9afe4f3f9bfd08b01ec75f1f8b6ca7316cfa88dbf204c0fb8fd40571478f44ad`.
The Worker container and Issue lock were removed/cleared, and Scheduler logged
one `Task 392 completed successfully` INFO. The authenticated task detail page
showed completed Codex, Provider 12, the exact Worker image, 42 seconds, 21K
input / 137 output tokens, and `+0 -0` changes. A local fallback-metadata
diagnostic was present for the OpenRouter model but did not alter the
successful terminal or delivery result. The expected post-exit canonical-tail
409 was non-blocking after receipt/archive persistence.

At `2026-09-05T03:41:26Z`, current exact-composition Task 394 ran Pi with
Provider 12 (`openrouter-minimax-responses` / `minimax/minimax-m3:free`) on
reused Bundle 170 over the legal `openai_responses` protocol. The task completed
at `2026-09-05T03:41:54Z` with zero changes; attempt
`task-394-attempt-1-f59d45de3da3` used Adapter `2.1.0` / CLI `0.84.2`, closed
with 74 unique contiguous receipts (seq 1–74), and one
`run.completed(status=completed, success=true)` terminal. The read-only shell
inspection returned a clean `/workspace` on `codify/issue-99`, the delivery
result had exit code 0 with no commit, and usage was 139 input / 118 output
tokens. It produced 3 raw-log chunks / 2727 bytes and archive
`task-394-runtime-archive.tar.gz` at 8974 bytes with SHA-256
`2ffe9f760035d6ec85aad6029d41659f97d4e0a2a5927ae169f976b4460b69ee`.
The Worker container and Issue lock were removed/cleared, and the authenticated
task detail page showed completed Pi, Provider 12, the exact Worker image, 28
seconds, 139 input / 118 output tokens, and `+0 -0` changes. Scheduler logged
one self-recovered `control_owner_unreachable` gate-probe retry and then one
`Task 394 completed successfully` INFO; the expected post-exit canonical-tail
409 was non-blocking after receipt/archive persistence. Constrained scans of
the Task 394 canonical events and raw logs found no `sk-`, `glpat-`, or auth-like
token matches.

## Permission and rotation recheck

At `2026-09-04T15:12:48Z`, a read-only GitLab administration review found the
`ai-bot` account at highest role `Maintainer`, with top-level group creation
enabled and two-factor authentication disabled. The `GIMR` OAuth application
used by the development integration also advertises `api`,
`write_repository`, and `write_virtual_registry` scopes (along with its read
and OIDC scopes). These observations are stronger than an application
connectivity check, but they do not satisfy least privilege and must not be
treated as a release approval.

All enabled Provider rows currently have an active `credential_ref`, but the
associated credential records have no `version_metadata`; the stored
creation/update timestamps therefore do not constitute a rotation record. A
direct self-token check using the container's legacy `GITLAB_BOT_TOKEN`
environment value returned HTTP 401, while the effective GitLab URL is a
database override. The effective encrypted credential was not read or
printed. The release owner must reconcile the effective credential source,
reduce GitLab/OAuth permissions, enable the required account controls, and
record a verifiable rotation/revocation plan before R4.5 can be signed.

## Schema alignment check

The target database is currently at Alembic revision
`077_v2_worker_kit_identity`. Both the Backend and Scheduler images contain
`078_remove_provider_driver`, but both services are intentionally configured
with `AUTO_MIGRATE=false`; the Scheduler log records that auto-migration was
skipped. The live database still has the `provider_driver` column and one
`openai_compatible` + `anthropic_messages` Provider row, which is exactly the
legacy row that 078 would delete before dropping the column.
That row is Provider 11; it is referenced by 23 Tasks and 23 immutable Profile
Snapshots, including the current successful Task 388, while no Issue currently
selects it as a default Provider. The existing foreign keys use `SET NULL`, so
the migration would preserve those Tasks but clear their editable `provider_id`
association; the frozen Snapshot evidence must be checked again after the
migration.

A transaction-scoped rollback audit against the live database confirmed that
078 would delete exactly Provider 11 and affect all 23 direct Task references;
the transaction was rolled back. The database is approximately 116 MB, so a
backup is practical but must precede the irreversible roll-forward-only
migration. The dedicated 078/migration-owner tests pass (`16 passed`) and the
focused Ruff check is clean; no migration was run on the development Host.
Before any `v2_only` cutover, the maintenance owner must back up the database,
execute the reviewed target revision once, confirm the expected Provider
cleanup, and repeat Profile, Bundle, and relevant Task verification; the
current generation-73 evidence was recorded against revision 077 and cannot
silently be reused as post-migration proof.

## Continuation addendum: V1 compatibility, Task 399, and full-disk cleanup

The previous audit checkpoint correctly recorded that Profile 1 could not
create a V1 Task because it was an explicit V2 Profile without verified Codex
identity. To obtain legitimate V1 evidence, a temporary V1-only Profile 5 was
created through the normal UI with `harness_runtimes={}`; no database bypass or
historical Snapshot rewrite was used.

The launcher had a real dual-canary compatibility defect: it rejected V1
runtime-bundle manifests and applied the V2 self-binding digest check to V1.
The minimal source fix accepts `codify.worker.runtime-bundle/v1` and `/v2`, and
limits the digest check to V2. The focused Worker Kit/Profile regression set
passed 83 tests. A new four-Harness Kit was built and installed on the target:
`0.6.13-v1-compat2`, manifest SHA-256
`d97f2157bbe79ec1c278fb216d9e208063e7273ed402169a860193046b86be2e`, at
`/opt/codify/worker-kits/0.6.13-v1-compat2-linux-amd64-d97f2157bbe7`.
Administrator runtime Verify returned 200 at `2026-09-05 04:39:31`; the V1-only
Profile correctly has no V2 identity fields.

Tasks 395–398 remain bounded diagnostic samples: two were cancelled after the
old image digest was unavailable/immutable retry reuse, Task 397 exposed the
old V2-only schema gate, and Task 398 exposed the V2-only digest check applied
to V1. After the fix, Task 399 completed with Profile 5, Codex, Provider 12
`openrouter-minimax-responses`, Bundle 174, zero changes, and 20996/151 input/
output tokens. Its V1 attempt used Adapter `1.0.0` / Codex CLI `0.146.0`,
closed with 14 contiguous `codify.worker.event/v1` receipts (seq 1–14) and
`run.completed`; raw logs were 5 chunks / 2289 bytes and the runtime archive
was 3796 bytes with SHA-256
`205dfaf54d20fe07c72b9e1370274b537e5565700a1edbc72dd2d877d91d21fd`. The
Worker container and Issue lock were cleared.

After completion, Backend and Scheduler were temporarily recreated in
`v2_only`. Both health endpoints agreed on `v2_only`, and the authenticated
Task399 detail page displayed `已完成` and `Legacy V1 · 只读` together with the
delivery summary, V1 event stream, raw logs, Provider/Worker/Harness context,
and runtime statistics. No task mutation occurred. Services were recreated
back to `dual_canary`; the final preflight agreed and Backend was healthy. This
is a read-only compatibility preflight, not an L6 cutover.

The new Kit build filled the remote root filesystem to 100% (about 413MB
available). After checking every target with an ancestor-container query, the
cleanup removed only unreferenced Codify Kit-export/Backend/Frontend/test/mock
images, 29 dangling Codify layers, and BuildKit cache older than one hour.
Running services, Worker image, volumes, GitLab/DB/Redis, and unrelated images
were not touched. Final root capacity is 61G total / 59G used / 2.5G available
(97%); all Codify services remained healthy. The remaining reclaimable cache
is intentionally kept for current development unless another full-disk event
requires scoped cleanup.

The live database now has 367 Tasks: 362 V2 snapshots and 5 V1 snapshots
(Tasks 395–399), with zero active Tasks or Issue locks. The V2 exact
Task-ID 380–394 integrity result remains 14 attempts, 824 receipts, and 824
distinct event IDs; Task 399 is excluded from that V2 statistic. Migration
078 remained unapplied (`077_v2_worker_kit_identity`) at that checkpoint, real
Mattermost delivery and release-owner/independent sign-off remained open, and
the Host remained in `dual_canary`.

## Post-cleanup V2 smoke recheck: Task 400

After the scoped Docker cleanup, Task 400 was run from Issue #99 with Profile
4, the existing Provider 12 `openrouter-minimax-responses`, and the Pi Harness.
It completed as a real V2 freeform read-only task with zero changes and
130/136 input/output tokens. The immutable snapshot used Bundle 170, Kit
`0.6.12`, Pi CLI `0.84.2`, Adapter `2.1.0`, and the same current Worker image
digest recorded in the preceding R4 audit.

The attempt closed at `last_seq=42` with `run.completed`; all 42 receipt
sequence numbers and event IDs were unique and contiguous. Five raw-log chunks
were persisted, the runtime archive was 6905 bytes with SHA-256
`eae25e8e14f181ef626dc766816f578e660c399b82b4766db08c9bde65f4d1ab`, and the
temporary Worker container plus Task Issue lock were absent after completion.
The authenticated desktop `/tasks/400` page displayed the completed Provider,
Worker, Pi, delivery-summary, event-stream, raw-log, and runtime-statistics
context.

This recheck updates the live database count from the preceding 367-task
checkpoint to 368 Tasks: 363 V2 snapshots and 5 V1 snapshots. It does not add
Task 400 to the frozen 380–394 integrity cohort, does not execute migration
078, and at that checkpoint did not claim real Mattermost delivery,
mobile-device acceptance,
release-owner sign-off, or an R4.6/R5 decision. The Host remains in
`dual_canary`.

## Post-cleanup protocol matrix follow-up

The subsequent real-task recheck used the current Profile 4 and existing
configured Providers without running migration 078 or changing service mode.
The core legal matrix completed successfully: Task 400 Pi / Provider 12,
Task 403 OpenCode / Provider 12, Task 404 Claude / Provider 6, and Task 405
Codex / Provider 12. Each used the expected V2 protocol, Bundle 170/172/171/173
respectively, produced zero changes, and closed with `run.completed`. Task 401
was an additional Provider 12 Pi repeat; Task 402 was a bounded Provider 7
OpenCode alternate and is not counted as Provider 12 evidence.

Across Tasks 401–405, each attempt had contiguous unique receipt IDs, one
terminal event, and persisted raw logs plus a readable runtime archive. The
post-run Host query found zero active Tasks and zero Issue locks; all five
Worker containers were absent; root capacity remained 61G total / 59G used /
2.5G available (97%). The current database count is 373 Tasks: 368 V2
snapshots and 5 V1 snapshots.

This follow-up strengthens runtime evidence only. It does not extend the
frozen 380–394 integrity cohort and, at that checkpoint, did not satisfy the
then-open real Mattermost delivery, migration-owner, credential/least-privilege,
release-package, release-owner, mobile-device, R4.6, or R5/L6 gates.

No `v2_only` cutover, maintenance-window action, or broad Docker prune was
performed as part of this audit.

## Archive ownership recheck

The current database contains 349 `task_run_archives` rows covering Task IDs
1–405, with no archive row whose Task is missing. The backend archive
directory contains 525 `task-*-runtime-archive.tar.gz` files in total. A
separate set of 176 files (Task IDs greater than 405, up to the observed
parallel-debug range) is not referenced by the current database and occupies
4,109,381 bytes.

Because the development Host is shared by parallel/legacy debugging, these
unreferenced files were not deleted or treated as this V2 run's evidence. The
retention owner must classify their ownership and retirement policy before any
cleanup; the current Host is at 97% usage but has not reached the authorized
full-disk cleanup trigger. This remains an R4.5 retention/ownership gate.

## 2026-09-05 continuation: Mattermost debug deployment and delivery

The development Host subsequently received an independent Mattermost
10.9.1/Team Edition debug stack. The exact image is
`mattermost/mattermost-team-edition:10.9.1` at repo digest
`sha256:445ef98396678f3d4e269e05e11738e7a808e54c414db24625a855c37b5f978b`.
`codify-mattermost` and its separate `codify-mattermost-db` (`postgres:16-alpine`)
are healthy on the dedicated `codify-mattermost-debug` network and named
volumes, with port `8065` published on the development Host. The existing
Codify Postgres, GitLab, Redis, and active Worker container were not touched.

The authenticated Codify admin UI connection test passed. Profile `V2 live
notifications` targets `codifydebug/notifications` and enables only
`task_completed`; credentials remain only in remote mode-600 files and are not
part of this repository or audit. A separate direct Bot smoke returned HTTP
201. The real Codify Task 406 completion then created delivery row 2 with
`event_type=task_completed` and `status=success`; the Mattermost channel
contained the resulting Task 406 completion card.

Task 406 used the existing Provider 12 / OpenCode / `openai_responses` legal
combination on Bundle 172 in fresh-session plan mode. It completed with zero
changes; its closed V2 attempt had 82 contiguous unique receipts, a single
`run.completed` terminal, 5 raw-log chunks / 2772 bytes, and a 23219-byte
archive. This is real transport and application-delivery evidence, not a
release approval.

The completion card currently renders the task link from the existing remote
`FRONTEND_URL=http://frontend.example.test:8880`, while the target development
URL is `http://192.168.50.129:8880`. The target IP returned HTTP 200 in the
direct check; the example-host URL did not produce a usable page. The URL
configuration therefore remains an explicit release follow-up.

The Mattermost pull left the Host at approximately `61G` total / `60G` used /
`1.2G` available (`99%`). Docker reports 26 images, 11 running containers, 18
volumes, and 7.487GB reclaimable BuildKit cache. This is high pressure but not
a full-disk trigger, so no further Codify cleanup was performed here. If the
trigger is reached, the operator must repeat ancestor-container checks and
remove only unreferenced Codify debug images/cache. Migration 078, credential
and least-privilege review, release package/signatures, URL configuration,
release-owner sign-off, R4.6, R5/L6, and real mobile-device acceptance remain
open; the latter is explicitly deferred by the user.

## 2026-09-05 continuation: frontend URL correction

The Mattermost Task 406 card showed that the running development deployment
still used the generic `frontend.example.test` value. Because the Host had zero
active Tasks and zero Issue locks, Backend and Scheduler were recreated with a
temporary Compose override setting
`FRONTEND_URL=http://192.168.50.129:8880`. The generic repository
`deploy/.env.test` template was left unchanged; this was a Host deployment
override only. Backend remained healthy, Scheduler remained in `dual_canary`,
`AUTO_MIGRATE=false` remained set, and the database stayed at
`077_v2_worker_kit_identity`.

Task 407 then completed through the existing Provider 12/OpenCode legal
`openai_responses` path on Bundle 172. It had zero changes, a closed V2
attempt with 472 contiguous unique receipts, 5 raw-log chunks / 2725 bytes,
and a 50223-byte archive. Codify recorded
`mattermost_notification_deliveries.id=3` as `task_completed/success`; the
real Mattermost card used `http://192.168.50.129:8880/tasks/407`. This confirms
the current Host URL correction through an AI-backed real task, but does not
make the generic repository template or a future deployment configuration a
release-owner-approved URL policy.

The existing migration, credential/least-privilege, release-package,
retention, maintenance-owner, independent approval, R4.6, and R5/L6 gates
remain unchanged. The Host remains in `dual_canary`, and no `v2_only` cutover
or migration 078 was performed.

## 2026-09-05 continuation: remote four-Harness Kit verify

The current installed candidate was verified directly on the target Docker
daemon with the Kit's trusted content verifier. The command used Kit
`0.6.12-linux-amd64-c33dbf86951b` and Worker image
`127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`.
The no-runtime-manifest path enumerated all four present harnesses and exited
0:

| Harness | CLI version | Result |
| --- | --- | --- |
| Claude | `2.1.153` | `Worker kit verification passed` |
| Codex | `0.146.0` | `Worker kit verification passed` |
| OpenCode | `1.18.19` | `Worker kit verification passed` |
| Pi | `0.84.2` | `Worker kit verification passed` |

The content inventory was
`7630f086800c95f851db8c9351638868ab60ac33fb3bfe22f9f2f5c8dcdc98a1`; the
remote image ID was
`sha256:b07ac48b129c35876c044079f8e9cd7aa7558dbb0ade2e50e856d4ab980f5e71`
and its platform was `linux/amd64`. This is direct L3/R4.2 composition and
launcher evidence, not a signed release package or owner approval. The
verification containers were temporary `--rm` containers and no service,
Task, database revision, or execution mode was changed.

## 2026-09-05 continuation: real cancellation notification after lifecycle fix

The live-host evidence now also includes the post-fix cancellation path. Code
commit `594bf67a` sends `task_cancelled` after Worker finalization persists the
terminal state, while keeping the API-side notification only for the direct
PENDING/QUEUED path. The focused regression suite passed with 114 tests and 19
subtests, and focused Ruff checks passed. The rebuilt Backend/Scheduler image
was `sha256:92321ff20bda74088b44a9c1410d5688399c44f15d78007b58e0068aaf07d7a3`.

Task 409 used the existing Provider 12/OpenCode/`openai_responses` legal
combination and was cancelled while a controlled `sleep 180` command was
running. The Task converged to `cancelled`; Codify recorded
`mattermost_notification_deliveries.id=4` with
`task_cancelled/success`, and Mattermost received the card linking to
`http://192.168.50.129:8880/tasks/409`. This closes the verified real
completion/cancellation notification gap, but it does not establish the live
`task_failed` path or R4.4 sign-off.

At the final check the Host had 377 Tasks, zero active Tasks, zero Issue locks,
healthy Backend/Scheduler services, `dual_canary` execution mode, and database
revision `077_v2_worker_kit_identity`. Disk pressure was approximately `61G`
total / `60G` used / `1.4G` available (`98%`); Docker reported 27 images, 11
containers, and 6.992GB reclaimable BuildKit cache. No cleanup was performed
because the disk was not full. Migration 078, release package/signatures,
owner approval, R4.6, R5/L6, and real mobile-device acceptance remain open;
mobile-device acceptance is explicitly deferred by the user.

## 2026-09-05 continuation: real failure notification

The previously missing live failure-notification sample was then exercised on
the same development Host. Task 410 used the existing Provider 4
`opencode-luna` (`gpt-5.6-luna`), the Codex Harness, and the legal
`openai_responses` protocol. The prompt prohibited repository changes, retry,
commit, push, and merge-request activity. Profile 3, `V2 failure/cancel
notifications`, remained enabled for `codifydebug/notifications` with only
`task_failed` and `task_cancelled` subscribed.

The real Provider request reached the Adapter and failed at the known upstream
availability boundary with HTTP 403 `unsupported_country_region_territory`:

| Item | Result |
| --- | --- |
| Task/runtime | Task 410, `failed`; canonical failure kind `engine_error` |
| Attempt | `task-410-attempt-1-54e3bd239521`, `codify.worker.event/v2`, Codex Adapter `1.0.0`, CLI `0.146.0`, `last_seq=12`, terminal `run.failed`, `control_state=closed` |
| Canonical failure | seq 10 `harness.failed`, seq 12 `run.failed`; the bounded message included the upstream 403 and `unsupported_country_region_territory` |
| Persistence | 12 contiguous unique receipts, 5 raw-log chunks / 2458 bytes, runtime archive `3335` bytes; no active Task or Issue lock remained |
| Codify delivery row | `mattermost_notification_deliveries.id=5`, `event_type=task_failed`, `status=success`, target `channel:aaz68niiuff3txfot5wjrgj33e` |
| Mattermost delivery | Bot post `4bw9czpbpfbuznzuj33ftj6ara` rendered `@root ❌ 任务失败 · [任务 410](http://192.168.50.129:8880/tasks/410)` |

The delivery query found one successful `task_failed` row and the Mattermost
channel query found one matching Bot post. Together with Tasks 406, 407, and
409, this establishes real completion, cancellation, and failure delivery
through the Codify notification log into Mattermost 10.9.1, including the
corrected development Host URL. Task 410 is an additional operational sample;
it does not alter the frozen Task-ID 380–394 integrity cohort.

The final recheck reported 378 total Tasks, zero pending/queued/running Tasks,
zero Issue locks, healthy Backend and Scheduler services, database revision
`077_v2_worker_kit_identity`, and `dual_canary`. Docker reported 27 images, 11
containers, and 6.992GB reclaimable BuildKit cache. The latest direct Host
filesystem check remained approximately `61G` total / `60G` used / `1.4G`
available (`98%`); the full-disk cleanup trigger was not reached, so no Codify
image/cache cleanup was performed and active/unknown Worker images and
protected services were not touched.

This adds the missing R4.4 runtime evidence but does not sign R4.4 or R4.5.
Credential/least-privilege and rotation evidence, release package/signatures,
retention ownership, maintenance-window ownership, independent zero-P0/P1
approval, R4.6, migration 078, R5/L6, and real mobile-device acceptance remain
open; the mobile-device item is explicitly deferred by the user.
