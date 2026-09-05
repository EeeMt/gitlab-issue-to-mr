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
`sha256:2cff3fd7eb27d21625614785cf6d5f37bc538f6851775253a9a379b6b6360161`.
It exposes no Git revision OCI label, so the current image provenance is the
committed tree plus the remote build/deploy record. Profile 4 is now at
generation `77` with Kit `0.6.14`; the current additional Pi Bundle is 177,
while the exact-composition selected-Harness Bundles 170 (Pi), 171 (Claude),
172 (OpenCode), and 173 (Codex) remain the frozen cohort identities. Tasks
380–383 and post-fix Tasks 388–394 validation are recorded in the
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

## 2026-09-05 continuation: nginx rebuild under disk pressure

The remote nginx build initially failed during `COPY frontend/` with
`no space left on device`. The cleanup was scoped after checking all container
references and image labels: the only image removed was the unreferenced
dangling Codify Backend image `sha256:334c674db035…`; private BuildKit cache
was pruned. GitLab, databases, Redis, Mattermost, active/unknown Worker
images, and volumes were left untouched. The rebuilt nginx image is
`sha256:8b6fbfb939a598678ef0d3e9c263c0a89d8f22fc90a283b3f890046071712c76`.

Because `compose up nginx` recreated Backend as a dependency, Backend and
Scheduler were then recreated with an untracked temporary override restoring
`FRONTEND_URL=http://192.168.50.129:8880`; the tracked generic
`deploy/.env.test` template was not changed. Both services report
`HARNESS_EXECUTION_MODE=dual_canary` and `AUTO_MIGRATE=false`, Backend is
healthy, the Scheduler process is running, and the database remains at
`077_v2_worker_kit_identity`. Mattermost 10.9.1 remains healthy. The final
Host state is 378 Tasks, zero pending/queued/running Tasks, zero
`issue_execution_locks`, and approximately 2.0GB available on `/` (97%).

The served Task 410 page was rechecked after the nginx deployment and now
renders the canonical upstream 403 failure detail. The UI change prefers
`failure_message` over the generic first line for `engine_error`; its focused
25-test suite and frontend production build passed. This evidence does not
close the open credential/least-privilege, migration 078, release-package,
owner-signature, R4.6, R5/L6, or deferred real-mobile-device gates.

## 2026-09-05 continuation: post-restart Provider boundary recheck

Two additional real read-only analysis tasks were run after the current nginx,
Backend, and Scheduler deployment was healthy. Task 411 used Provider 7
`openrouter-free` / `openai_chat_completions` with OpenCode and ended as a
bounded `protocol_error` (`session.idle with active tool parts`) after 1134
contiguous unique V2 receipts; it persisted a 107313-byte archive, zero
changes, and a successful `task_failed` Mattermost delivery. Task 412 used
Provider 12 `openrouter-minimax-responses` / `openai_responses` with the same
OpenCode analysis shape and completed with zero changes, 885 contiguous unique
V2 receipts, an 84474-byte archive, and a successful `task_completed` delivery.
Both tasks left no container or Issue lock, and the served Task 411/412 pages
matched their canonical outcomes.

The pair is operational evidence, not a permission or release approval. It
shows the current deployment and Responses path remain healthy while the
Provider 7 chat path produces a correctly bounded OpenCode protocol failure;
no provider configuration was changed and neither task alters the frozen
Task-ID 380–394 integrity cohort. R4.5 credential/least-privilege,
release-package, retention, maintenance-owner, independent approval, R4.6,
migration 078, R5/L6, and real-mobile-device gates remain open.

## 2026-09-05 continuation: OpenCode redaction framing fix and Task 415

The failed Task 411 archive identified a security-relevant correctness defect
at the OpenCode Adapter boundary. The Adapter applied the string-oriented
secret sanitizer to serialized JSON before parsing it. An `API_KEY` value
could consume escaped newlines and quotes, causing valid tool snapshots to be
stored as malformed JSON. The resulting fail-closed protocol error was safe,
but the archive and diagnostic path lost the actual completion snapshot.

The correction parses valid JSON first, recursively sanitizes only string
values, and keeps the sanitized raw-line fallback for genuinely non-JSON
input. The regression test includes an API key plus embedded JSON in a tool
output and proves that the completed tool event survives, the secret is not
persisted, and no `non_json_raw_line` diagnostic is emitted. The focused
OpenCode Adapter suite passed 77 tests. No credential, Provider, or
notification configuration was changed.

The remote Backend/Scheduler image is now
`sha256:d73018a40507ae08e20f1cc1944a428c370bc8d56377cf4e9410dd764cc5fb5e`.
Profile 4 was re-verified through the normal path at generation 75 with Kit
`0.6.12`; the Task 415 snapshot records Bundle 175 and the exact runtime
bundle digest `532c4a410962433c094c775815748da11c0f2d546290b9a0da95e4f348a27e7f`.

Task 415 was a fresh-session, read-only analysis run using existing Provider 7
`openrouter-free` / `openai_chat_completions` and OpenCode. It completed with
zero repository changes. Its V2 attempt persisted 96 contiguous, unique
receipts through `run.completed`; the 25,988-byte archive contained 183
parseable OpenCode JSONL records, 13 tool parts and 3 completed tool parts,
with zero `non_json_raw_line` or secret-like matches. The five raw-log chunks
totaled 2,723 bytes. Codify delivery row 8 recorded one successful
`task_completed` post to the independent Mattermost 10.9.1 service, and the
authenticated browser showed Task 415 completed on Issue #99.

The post-run Host state had zero active Tasks and Issue locks, healthy
Backend/Scheduler/Mattermost, `dual_canary`, and about 1.9GB free on `/`.
Docker reported 4.424GB reclaimable images and 1.796GB private BuildKit cache;
no cleanup was needed. This strengthens the current candidate's secret
redaction and real-provider evidence, but is not an R4.5 security sign-off:
credential/least-privilege and rotation records, release package/signatures,
retention and maintenance ownership, migration 078, independent zero-P0/P1
approval, R4.6, R5/L6, and real-mobile-device acceptance remain open. The
mobile-device item remains explicitly deferred by the user.

## 2026-09-05 continuation: OpenCode Responses post-fix recheck (Task 416)

Task 416 exercised the complementary real Provider protocol after the
redaction framing fix. It used existing Provider 12
`openrouter-minimax-responses` / `openai_responses`, OpenCode, Profile 4
generation 75 / Bundle 175, a fresh session, and the read-only analysis
prompt. The Task completed with zero repository changes and no Provider or
notification configuration changes.

The attempt `task-416-attempt-1-f6529450b7d4` used
`codify.worker.event/v2`, OpenCode Adapter `2.0.0`, CLI `1.18.19`, and closed
with `run.completed` at seq 121. All 121 receipts were contiguous and had
distinct event IDs. Raw logs were 5 chunks / 2,716 bytes. The 31,767-byte
runtime archive has SHA-256
`c38bfe79648337abbc9491739c0e07d9b271b7cbdcbbb89e6f6ba3313f865183`; its
OpenCode JSONL contains 211 parseable records / 211 distinct event IDs, 19
tool updates / 4 completed tools, zero `non_json_raw_line` records, and zero
matches in the targeted secret scan. Codify delivery row 9 is
`task_completed/success` to the independent Mattermost 10.9.1 channel.

This is additional candidate security/correctness evidence that the same
post-fix Adapter preserves valid OpenCode Responses framing; it is not an
R4.5 sign-off. Credential/least-privilege and rotation records, release
package/signatures, retention and maintenance ownership, migration 078,
independent zero-P0/P1 approval, R4.6, R5/L6, and real-mobile-device
acceptance remain open. The mobile-device item remains explicitly deferred by
the user.

## 2026-09-05 continuation: receipt-ingest performance and archive safety (Task 418)

Task 417, run before the next Backend/Scheduler rebuild, completed successfully
but showed a roughly 409-second archive-backfill tail after a roughly 535-second
Worker run. The attempt had 4726 contiguous receipts. Review identified the
canonical ingest path's repeated full-replay query as the cause. Commit
`e0d487ec` replaced that repeated scan with incremental identity/order/
finalization checks and retained full replay as the final integrity assertion.
The related regression set passed 105 attempt/protocol/archive tests and 68
Worker/Scheduler tests, with Ruff and diff checks passing.

The current remote Backend/Scheduler image is
`sha256:2cff3fd7eb27d21625614785cf6d5f37bc538f6851775253a9a379b6b6360161`.
No Provider configuration or credential data changed, and Mattermost 10.9.1,
its database, GitLab, Postgres, Redis, and existing Workers were not recreated
by this deployment.

Task 418 supplied the post-fix real-host security/correctness recheck. It used
existing Provider 6 / `opencode-pi` over legal `anthropic_messages` with
OpenCode, Profile 4 generation 75, Bundle 175, a fresh analysis session, and
zero repository changes. The attempt closed at `last_seq=6612` with one
`run.completed`; all 6612 receipts and event IDs were contiguous and unique.
The 477600-byte archive SHA-256 was
`e6379c3c2ca63a3366fb13eba6c0c51fbc5289ece38227fd5a7f3ae9587a9843`.

The archive contained 6758 parseable OpenCode JSONL records and 6612 canonical
records. Canonical types included exactly one each of `harness.completed`,
`worker.finalization`, and `run.completed`, plus 11 `tool.started` and 11
`tool.completed`; the targeted secret-pattern scan returned zero hits. Raw
logs persisted as 5 chunks / 2710 bytes. Codify recorded
`mattermost_notification_deliveries.id=11` as `task_completed/success` to the
existing Mattermost channel. The post-run Host had zero active Tasks and zero
Issue locks, database revision `077_v2_worker_kit_identity`, `dual_canary`, and
2.1GB available on `/` (97%). Docker still reported 1.796GB private BuildKit
cache; the full-disk trigger was not reached, so no cleanup was performed and
protected services/active or unknown Worker images were untouched.

This is additional release/security evidence for receipt persistence, archive
integrity, redaction, and notification delivery; it is not an R4.5 sign-off.
Credential/least-privilege and rotation ownership, release package/signatures,
retention/maintenance ownership, migration 078, independent zero-P0/P1
approval, R4.6, R5/L6, and the user-deferred real-mobile-device acceptance
remain open.

## 2026-09-05 continuation: post-Task-418 Host recheck

At `2026-09-05T10:00Z`, a read-only recheck through the `remote` Docker
context confirmed that `codify-backend` remained healthy on image
`sha256:2cff3fd7…`, `codify-scheduler` was running in `dual_canary`, and both
`codify-mattermost` (`mattermost/mattermost-team-edition:10.9.1`, repo digest
`sha256:445ef983…`) and its Postgres were healthy. Backend/Scheduler still
reported `FRONTEND_URL=http://192.168.50.129:8880` and
`AUTO_MIGRATE=false`. The database reported zero pending/queued/running Tasks,
zero `issue_execution_locks`, and revision `077_v2_worker_kit_identity`.

The remote root filesystem was `61G` total / `59G` used / `2.1G` available
(`97%`). Docker reported 29 images, 11 active containers, 1.796GB reclaimable
BuildKit cache, and 4.76GB reclaimable images. This is high pressure but not
the agreed full-disk trigger, so no cleanup was performed; GitLab, databases,
Redis, Mattermost, volumes, and active or unknown Worker images were not
touched. The Scheduler's current startup/crash-recovery log reported
`0 resumed`, `0 awaiting Docker`, and `0 marked failed`, with no new selected
Task-417/418 failure or traceback signal.

The same snapshot found one long-running, non-Compose container named
`quirky_allen`, created on `2026-09-01`, using the content-addressed Worker
image and Kit `0.6.11` only to inspect the OpenCode API schema. It has no
Codify task labels, no active Task or Issue lock exists, and its process is
stalled in that one-off probe. It was intentionally retained because the Host
is not full and the image is an active/unknown Worker image; if a full-disk
cleanup becomes necessary, it must be rechecked and handled separately from
the protected service/image cleanup. This is an operational observation, not
an R4.5 approval or permission to remove it now.

## 2026-09-05 continuation: real Task 419 and Mattermost delivery

Using the authenticated target-Host Dashboard, a new read-only analysis Task 419
was created from Issue 99 and executed after the post-fix Backend/Scheduler
restart. It used existing Provider 12
`openrouter-minimax-responses` / `minimax/minimax-m3:free` over legal
`openai_responses`, Worker Profile 4
`v2-canary-0.6.11-four-harness` at generation 75 with Worker Kit `0.6.12` and
`mounted_kit`, OpenCode, a fresh session, and `plan` mode. The Task started at
`2026-09-05T10:11:34Z`, completed at `10:13:09Z`, and made zero repository
changes. The served Issue page then showed `Task #419` as completed and 47 total
tasks.

| Item | Result |
| --- | --- |
| Attempt | `task-419-attempt-1-aaced1cae60a`, `codify.worker.event/v2`, OpenCode Adapter `2.0.0`, CLI `1.18.19`, `last_seq=820`, terminal `run.completed`, `control_state=closed` |
| Canonical persistence | 820 receipts, 820 distinct event IDs, contiguous seq 1–820; event counts included one each of `harness.completed`, `worker.finalization`, and `run.completed`, plus 4 `tool.started` / 4 `tool.completed` |
| Raw/archive | 5 raw-log chunks / 2,716 bytes; `task-419-runtime-archive.tar.gz` is 79,490 bytes with SHA-256 `d009a8600a3612b6857ff83b1d24a6853def97f56c7fc448d6a27362d40dd37c`; its `event.jsonl` had 820 parseable records and 820 unique event IDs; a targeted scan across 9 archive files returned 0 credential-like matches |
| Mattermost | `mattermost_notification_deliveries.id=12`, `task_completed/success`, target `channel:aaz68niiuff3txfot5wjrgj33e`; Mattermost 10.9.1 and its Postgres were healthy |
| Post-run Host | zero active Tasks and zero Issue locks, database `077_v2_worker_kit_identity`, Scheduler `dual_canary`, Backend healthy, root filesystem 2.1GB available / 97%; Docker reported 29 images, 4.76GB reclaimable images, and 1.796GB reclaimable BuildKit cache |

This is additional real-provider, archive-integrity, redaction, and completion-
notification evidence. It is not a new member of the frozen Task-ID 380–394
cohort and is not an R4.3/R4.4/R4.5/R4.6 sign-off. No full-disk cleanup was
performed; the unlabelled `quirky_allen` OpenCode schema-probe container and its
active/unknown Worker image remain intentionally retained for separate review if
the disk reaches the cleanup trigger. Credential/least-privilege and rotation
records, release package/signatures, retention/maintenance ownership, migration
078, independent zero-P0/P1 approval, R4.6, R5/L6, and the user-deferred
real-mobile-device acceptance remain open.

## 2026-09-05 continuation: Kit 0.6.14 and delivery-summary regression audit

Task 420 supplied a real-provider defect sample: the Task completed, but the
delivery-summary validator reported `ok=false` because a Mermaid fenced block
contained the parser-sensitive token `@{u}`. Two summary repair attempts failed
without changing the Task terminal state. Commit `59d55585` now escapes only
the no-colon Git-ref form inside Mermaid fenced blocks, preserves valid Mermaid
shape syntax, and leaves outside text unchanged. The focused delivery/worker
regression set passed `136` tests.

The repaired runtime was packaged on the local `desktop-linux` Docker daemon as
the `linux/amd64` Worker Kit `0.6.14`; manifest SHA-256 is
`d461d040694b20b88944a88de47b5ad78188f91d74d528421cdef44b68274035`; the
export archive SHA-256 is
`bd6debd99c411cb6a50d1628f09d1fbe3127fffac11038ea8d58f5b512668251`
(`543487461` bytes). It was
installed through the content-addressed installer at
`/opt/codify/worker-kits/0.6.14-linux-amd64-d461d040694b` and passed the
Profile-specific four-Harness Verify. The direct launcher/content check also
passed when run with the Kit's `/nix/store` closure and the Worker verification
container's `/workspace` tmpfs. Profile 4 records generation `77`; Bundle 177
records digest
`20634962827d632e003fe0d5b87b974af22b66c0ad7c785ac6c407dfb60d51e1`. No
Provider credential or protocol configuration was changed.

Task 421 used existing Provider 12 `openrouter-minimax-responses` /
`minimax/minimax-m3:free`, legal `openai_responses`, Profile 4, Pi, `plan`,
and a fresh session. It completed at `2026-09-05T11:18:13Z` with zero changes.
The attempt `task-421-attempt-1-39ec65925f1d` closed with `run.completed` at
seq 1158; all 1158 receipts and event IDs were contiguous and unique. The
five raw-log chunks totaled 2713 bytes. The 87419-byte runtime archive has
SHA-256
`c3d30a461b035db790c9755261a48af3364da15a803588c1d6e643a3c7744819`.
Its delivery-summary validation is `ok=true` with two diagrams, zero errors,
and zero repair attempts; the targeted archive secret-pattern scan returned
zero matches. Mattermost delivery row 14 is `task_completed/success` on the
10.9.1 debug service.

The authenticated served `/tasks/421` detail showed the completed Provider,
Worker, Pi, plan/fresh context, zero changes, summary, event stream, and
runtime statistics; its Worker modal showed Kit `0.6.14` and the immutable
host path. After the task, the remote Host had about 2.0GB available on `/`
(97%), Docker BuildKit cache `0`, and only the expected services plus the
retained unlabelled `quirky_allen` probe. The earlier full-disk response was
scoped to verified Codify debug build images/cache; Mattermost, GitLab,
databases, Redis, volumes, and active/unknown Worker images were not touched.

This strengthens current L2/L3/L4 and R4.5 evidence but is not a security
approval or release-owner sign-off. The frozen Task-ID 380–394 cohort is
unchanged. Credential/least-privilege and rotation ownership, migration 078,
release package/signatures, retention and maintenance ownership, independent
zero-P0/P1 approval, R4.6, R5/L6, and real mobile-device keyboard/IME/notch/
gesture-area acceptance remain open; the mobile-device item is explicitly
deferred by the user.

## 2026-09-05 continuation: four-Harness real-provider audit on Kit 0.6.14

The current development candidate was exercised through the existing AI
Providers on the target Host after the Kit `0.6.14` install. Tasks 422, 423,
and 424 were fresh `plan` sessions from Issue #99 using Profile 4 and made zero
repository changes. They add OpenCode, Claude, and Codex real-provider evidence
to Task 421's Pi run without changing Provider configuration or the frozen
cohort.

| Task | Runtime evidence | Security/notification evidence |
| --- | --- | --- |
| 422 | Provider 12 `openrouter-minimax-responses` / `minimax/minimax-m3:free`, OpenCode / `openai_responses`, Bundle 178; 123 unique contiguous V2 receipts; Adapter `2.0.0` / CLI `1.18.19`; archive 32790 bytes; summary validation `ok=true` | Mattermost delivery 15 `task_completed/success`; targeted archive scan found no `glpat-*`, `sk-ant-*`, `ANTHROPIC_API_KEY=`, or `OPENAI_API_KEY=` |
| 423 | Provider 6 `opencode-pi` / `deepseek-v4-flash`, Claude / `anthropic_messages`, Bundle 179; 48 unique contiguous V2 receipts; Adapter `1.0.1` / CLI `2.1.153`; archive 81963 bytes; summary validation `ok=true` | Mattermost delivery 16 `task_completed/success`; targeted archive scan found no credential-like matches |
| 424 | Provider 12 `openrouter-minimax-responses` / `minimax/minimax-m3:free`, Codex / `openai_responses`, Bundle 180; 19 unique contiguous V2 receipts; Adapter `1.0.0` / CLI `0.146.0`; archive 14382 bytes; summary validation `ok=true` | Mattermost delivery 17 `task_completed/success`; targeted archive scan found no credential-like matches |

The three tasks all ended with `run.completed`, closed control state, zero
changes, and no summary repair attempts. This strengthens current candidate
L4/runtime-integrity and redaction evidence, but it is not an R4.5 security
approval or release-owner sign-off. The frozen Task-ID 380–394 integrity cohort
is unchanged. Credential least-privilege/rotation ownership, migration 078,
release package/signatures, retention and maintenance ownership, independent
zero-P0/P1 approval, R4.6, R5/L6, and the user-deferred real mobile-device
keyboard/IME/notch/gesture-area acceptance remain open; no migration or
`v2_only` switch was executed. Post-run Host inspection still showed about
`2.0GB` available on `/` (97%) and Docker BuildKit cache `0`; because the disk
was not full, no new cleanup was performed, and protected Mattermost/GitLab/
database/volume resources plus the active/unknown `quirky_allen` Worker were
retained.

The served Task 424 Worker modal independently showed the Profile 4 snapshot,
Kit `0.6.14` content-addressed path, selected Worker image digest, and read-only
Kit/Nix mounts. The Host remained in `dual_canary` with `AUTO_MIGRATE=false`,
database revision `077_v2_worker_kit_identity`, and zero execution locks. The
stored Kit `0.6.14` readiness row was already past `ready_until` at the recheck;
under the documented contract this is derived `unknown`, not a current release
approval. No Verify was repeated because it would change the Profile generation
and exact identity. This is an explicit operational/release gate, not a failure
of the completed real-provider tasks; their archive fallback, canonical replay,
redaction scan, and successful Mattermost delivery remain intact.

## 2026-09-05 current candidate update: Profile 4 generation 78

The normal administrator Verify was subsequently completed through the
authenticated Dashboard. Profile 4 moved from generation `77` to generation
`78` while retaining Kit `0.6.14`, the same Worker image digest, and the same
legal Harness/protocol matrix. The Verify-time readiness row was
`ready` through `2026-09-05 12:18:31.417926` with `check_generation=2`; after
that TTL it is derived as `unknown` under the contract and is not a current
release approval.

Tasks 425–428 then exercised the current generation with existing Providers:
Pi/Provider 12, OpenCode/Provider 12, Claude/Provider 6, and Codex/Provider 12.
They bound Bundles 181/182/183/184, ended with `run.completed` and closed
control state, preserved zero repository changes, passed canonical archive
sequence/ID checks, and produced Mattermost deliveries 18/19/20/21 with
`task_completed/success`. The legal protocol and `[TOKEN]` redaction checks
matched the frozen matrix. Task 425's model-generated Mermaid still caused
delivery-summary validation `ok=false`; Task 426 did not write an independent
`delivery_summary` payload. These are recorded as delivery-summary boundaries,
not execution failures or a blanket summary-validation pass. Full details are
in the [generation 78 evidence](2026-09-05-open-harness-v2-generation-78-four-harness-smoke.md).

The post-run Host remained healthy in `dual_canary`, with database revision
`077_v2_worker_kit_identity`, `AUTO_MIGRATE=false`, zero active Tasks and zero
Issue locks. Mattermost `10.9.1` and its Postgres remained healthy. Root disk
usage was about 97% with roughly 2.0GB free, so the disk-full cleanup trigger
was not reached; no new cleanup was performed and protected services,
volumes, databases, and the active/unknown `quirky_allen` Worker were retained.
This update strengthens current runtime and redaction evidence but leaves the
release-owner least-privilege/rotation record, signed package/release notes,
retention/retirement plan, maintenance ownership, independent zero-P0/P1
approval, R4.3–R4.6, R5/L6, migration 078, `v2_only`, and user-deferred mobile
acceptance open.

## 2026-09-05 current-generation expiry and cancellation recheck

After the generation 78 four-Harness smoke, the stored readiness row passed
its `ready_until` (`2026-09-05 12:18:31Z`) and therefore derived to
`unknown`. Without re-running Verify, Tasks 429 and 430 completed on the
frozen generation 78 snapshot through OpenCode and Pi. Both were `plan/fresh`
read-only runs, with 742 and 116 contiguous unique V2 receipts respectively,
and Mattermost deliveries 22 and 23 succeeded. The models ignored the
requested `sleep 180`, so these runs are not counted as cancellation evidence.

Task 431 then used the same current Pi/Provider 12 legal path as
`freeform/fresh`. Remote process inspection confirmed the actual `sleep 180`
process before the served `/tasks/431` Cancel action. The Worker container was
removed, the task page showed `cancelled`, the attempt closed with canonical
`run.failed` at seq 14, all 14 receipt IDs/seqs were unique and contiguous,
and Mattermost delivery 24 was `task_cancelled/success`. Its 4122-byte archive
has SHA-256
`e257e2e1e7a55a92715603a1cac6606a2de1e4b84eea4a0d43d4a083e9006a37`.
Targeted scans of the 429–431 archives returned no `glpat-*`, `sk-ant-*`,
`ANTHROPIC_API_KEY=`, or `OPENAI_API_KEY=` matches.

The post-run development Host remained healthy in `dual_canary`, with no
active Tasks or Issue locks, Mattermost `10.9.1` and its Postgres healthy, and
about `2.0GB` free on the 97%-used root filesystem. The full-disk cleanup
trigger was not reached, so no cleanup was performed and the active/unknown
`quirky_allen` Worker was retained. This is current-generation desktop
cancellation evidence only; it does not constitute R4.5 security approval,
release-owner sign-off, R4.6/R5/L6 approval, migration 078 or `v2_only`
authorization, or real mobile-device acceptance.

Task 432 extended the same current-generation cancellation check to OpenCode:
Provider 12, `openai_responses`, Bundle 182, `freeform/fresh`. The real
`sleep 180` process was observed before the Dashboard Cancel action; the
container was removed, the served task page showed `cancelled`, nine canonical
receipt IDs/seqs were unique and contiguous, and Mattermost delivery 25 was
`task_cancelled/success`. The 5878-byte archive has SHA-256
`7eef4692558f2fe59205c68882e7413c2668b76ab3d121c03e26466bd05c4aaf`; its
targeted secret-pattern scan returned no matches. This is additional desktop
runtime evidence only and does not change the open R4.5 security/owner gates.

Tasks 433 and 434 completed the same current-generation cancellation procedure
for Claude and Codex. Task 433 used Provider 6 / `anthropic_messages` / Bundle
183 and closed with 8 contiguous receipts plus Mattermost delivery 26;
Task 434 used Provider 12 / `openai_responses` / Bundle 184 and closed with 9
contiguous receipts plus Mattermost delivery 27. Their 4180-byte and 3214-byte
archives had SHA-256 values
`7f40296df8be6ab1cc81d82b759b6ecaedbd77b0b9435e89dc1173a889293e4b` and
`60f84d3629b999c34c52be5ef7c2d1ab6b287af05c110a67b468ca52b5645988`;
both targeted secret scans returned no matches. Alongside Tasks 431 and 432,
this gives all four current-generation Harnesses a real desktop cancellation
sample, but it remains runtime evidence rather than R4.5 security approval or
owner/go-no-go sign-off.

## 2026-09-05 continuation: current Kit 0.6.14 release preflight

为当前 Profile 4 generation 78 / Kit `0.6.14` exact candidate 重新执行了仓库提供的
`deploy/scripts/preflight-v2-release.sh`。使用的临时归档为
`codify-worker-kit-0.6.14-linux-amd64-d461d040694b.tar.gz`，sidecar 与归档 SHA-256
均为
`bd6debd99c411cb6a50d1628f09d1fbe3127fffac11038ea8d58f5b512668251`。在
`DOCKER_CONTEXT=remote` 下，脚本针对目标 Host 当前 Worker image
`127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`
返回 `V2 release preflight OK`；manifest SHA-256 为
`d461d040694b20b88944a88de47b5ad78188f91d74d528421cdef44b68274035`，content inventory
SHA-256 为
`3be8e2272dbc1f4e6d645bfa3403657e3986bcbbdb5f0fb278fee735b079d5f2`，退出码为 `0`。

这是当前 exact candidate 的可复现归档、完整性和远端 image 绑定证据，补强 R4.1/R4.2 的技术门禁；
临时归档未提交，也没有签名包、批准的 release notes 或 release-owner 签署，因此不关闭 R4.5。
本次只读 preflight 未切换 `dual_canary`、未执行 migration 078/`v2_only`，也未修改远端服务。目标
Host 仍保持健康、无 active Task/Issue lock，根盘约 97% 使用但未达到满盘清理条件，未执行新的 Codify
image/cache 清理；真实移动设备验收继续按用户指示暂缓。

同一轮 schema-aligned 数据库复核确认 generation 78 的 Tasks 425–434 全部已收敛：425–430 为
`run.completed`，431–434 为取消后的 `run.failed`，10 个 attempt 均 `control_state=closed`，
receipt/`last_seq`、连续 seq 和唯一 event ID 均一致；Mattermost delivery 18–27 全部
`success`。当前 readiness 行仍为存储 `ready`/generation 2，但 `ready_until` 已过期，按合同为
有效状态 `unknown`；数据库 revision 为 `077_v2_worker_kit_identity`，active Task 与 Issue lock
均为 0。该复核补强 R4.4 的当前运维收敛证据，但不改变 R4.5 的安全/owner 签署边界。

## R4.5 owner handoff snapshot (unsigned)

The following is the handoff boundary for the current development candidate. It
is a checklist and identity record, not a release approval:

| Field | Current evidence |
| --- | --- |
| Target Host / mode | `192.168.50.129`, `HARNESS_EXECUTION_MODE=dual_canary`, `AUTO_MIGRATE=false` |
| Database | `077_v2_worker_kit_identity` |
| V2 Profile | Profile 4, generation 78; readiness `ready_until` is expired and therefore effective `unknown` |
| Worker Kit | `0.6.14-linux-amd64-d461d040694b`; manifest `d461d040694b20b88944a88de47b5ad78188f91d74d528421cdef44b68274035`; archive `bd6debd99c411cb6a50d1628f09d1fbe3127fffac11038ea8d58f5b512668251` |
| Worker image | `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`, `linux/amd64` |
| Backend/Scheduler image | Compose image label `sha256:2cff3fd7eb27d21625614785cf6d5f37bc538f6851775253a9a379b6b6360161` |
| Technical release preflight | Passed with manifest/content inventory checks; no signed package attached |

Before R4.5/R4.6 can be signed, the owner packet must add all of the
following without inferring them from the development smoke:

| Required owner input | Required result |
| --- | --- |
| Provider/GitLab/OAuth credential owner | Least-privilege scopes, effective credential source, rotation timestamp, revocation/rollback procedure, and confirmation of account controls |
| Migration owner | Backup/recovery point, decision for migration 078, and post-migration re-verification plan for Provider 11 and its 23 historical references |
| Release owner | Exact release notes, signed package/manifest, and signature identity bound to the table above |
| Operations owner | Kit/image retention and retirement dates, maintenance window, rollback owner, and observation window |
| Independent reviewer | Current R4.3–R4.5 P0/P1 review, exceptions, and explicit R4.6 `GO`/`NO-GO` |

No names, timestamps, signatures, or release decisions are invented here. A
fresh administrator Verify, if required for a release decision, creates a new
Profile generation and must update this identity record before anyone signs it.

## 2026-09-05 continuation: remote image retention boundary recheck

The named `remote` Docker daemon currently reports 26 images, 9 active image
references, 11 containers, 18 volumes (11 active), zero BuildKit cache, and
about `4.08GB` reclaimable image space. Ancestor checks showed:

| Image | Referenced containers | Retention result |
| --- | --- | --- |
| `codify-backend:latest` / `sha256:2cff3fd7…` | `codify-backend`, `codify-scheduler` | retain |
| `codify-nginx:latest` / `sha256:8b6fbfb9…` | `codify-nginx` | retain |
| `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c6…` (listed locally as `<none>`) | active `quirky_allen` Worker | retain; digest-only/dangling display is not proof of unreferenced state |
| Mattermost `10.9.1`, GitLab, Postgres and Redis images | corresponding protected services | retain |

The filesystem remains about 97% used with 2.0GB available, not a full-disk
condition. No image, volume, cache, or protected service was removed. This
recheck closes the current cleanup-safety observation but does not supply the
missing retention owner, retirement dates, or release approval required by
R4.5.
