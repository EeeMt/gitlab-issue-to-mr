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
(Pi), 171 (Claude), and 172 (OpenCode); Tasks 380–383 validation is recorded in the
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
| Remote Docker state | near capacity, not full | The post-Task-387 snapshot reports `df -h /` at 61G total / 57G used / 4.2G available (94%); `docker system df` reports 83 Images / 12.42GB / 6.713GB reclaimable, 5.054MB containers, 1.642GB volumes / 1.309GB reclaimable, and 6.526GB BuildKit. No cleanup was performed because the disk was not full. |
| Current Kit archive reconstruction and V2 release preflight | passed, not signed | The installed `0.6.12-linux-amd64-c33dbf86951b` Kit was streamed into a temporary `518M` archive; archive SHA-256 `2d3ee7f81525d465731344571cbf5bd93a0cd94bb6cf16f5a4d5512d5c0a25a6`, manifest SHA-256 `c33dbf86951bed6e3b4de1897313725f14f00006dc51fb300e7b821bb47e17bd`, content inventory `7630f086800c95f851db8c9351638868ab60ac33fb3bfe22f9f2f5c8dcdc98a1`; `deploy/scripts/preflight-v2-release.sh` passed against the target daemon and Worker image repo digest `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`. The temporary archive is not a release-owner-signed package and is not committed. |
| Exact committed image/Profile/Task recheck | passed with bounded Provider boundary | Backend/Scheduler now run image `sha256:334c674d…` built after `48b16fdc`; Profile 4 generation 74 completed four-Harness Verify; Tasks 380–383 completed Pi/Claude/OpenCode/Pi on unchanged Bundles 170–172 with 397 unique contiguous receipts and zero changes. Current exact OpenCode/Pi/Claude cancellation Tasks 384–386 on the prior Backend image added 15/40/8 receipts; post-fix Task 387 on Bundle 171 / Provider 11 added 9 unique contiguous receipts, one `run.failed(status=cancelled)` terminal, zero changes, a 4594-byte archive (`69e8a1df…`), 6 raw-log chunks / 5117 bytes, and a removed Worker container. The new Scheduler emitted one `Task 387 cancelled` INFO and no `Task 387 failed`; the old Task 386 generic error is historical. No current-composition Codex success was claimed because the available Codex-legal Providers remain bounded by the recorded upstream 429/403 failures. |
| Profile re-verification and prior post-fix smoke | passed with bounded Provider negatives | Profile 4 generation 73 and Tasks 374–379 remain historical evidence for the superseded image composition; Tasks 374–376 completed Pi/Claude/OpenCode on Bundles 166–168, while Codex Tasks 377–379 reached the Adapter and were correctly bounded as upstream `rate_limited`/`engine_error`; Task 368 remains the preceding-generation Codex success |
| GitLab integration connectivity | passed, not a permission sign-off | The authenticated admin UI read-only connection test reached `http://192.168.50.129:8080`, authenticated as `ai-bot`, and reported GitLab `18.5.5-ee`; the Webhook overview currently returned zero projects. This proves application connectivity/identity only, not token scope, least privilege, or rotation. |
| Remote execution mode | restored and healthy | A temporary no-task `v2_only` mode-health/V2-detail preflight was run and then restored; final Backend/Scheduler health reports `HARNESS_EXECUTION_MODE=dual_canary`. No hard-cut, migration, or V1 Task mutation was attempted. |

The remote image/cache state was inspected before and after the live smoke and
again after the frontend nginx-only deployment. The disk was not full, so no
image, volume, or BuildKit cleanup was performed. No protected service or
unrelated image was touched.

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
The latest database snapshot has 356 Tasks, zero `pending`/`queued`/`running` Tasks,
zero `issue_execution_locks`, zero Mattermost notification profiles, and zero
notification deliveries. These are current Host observations; they do not
replace the missing live alert delivery or independent release sign-off.

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
including exact-composition successful Tasks 380–383, generation-73 successful
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
3. **Old Kit/image retention and retirement.** The remote daemon still has
   reclaimable images/cache. No retirement date, retention owner, or approved
   deletion list is recorded, so cleanup remains intentionally deferred.
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
remains unchanged, and Task #387 is direct real-Provider evidence on this new
image. This closes the observed cancellation log-classification defect but
does not create a release-owner signature: the package manifest, release
notes, retention plan, and independent approval remain open.

## R4.5 conclusion

**Partial evidence, not signed.** Repository secret scanning, local regression,
remote-state checks, and exact committed artifact provenance pass. Provider/
GitLab authorization and rotation, release notes, retention/retirement,
maintenance ownership, and independent zero-P0/P1 approval remain open. R4.6
therefore has no recorded decision, and the system must remain in
`dual_canary`.

No `v2_only` cutover, maintenance-window action, or broad Docker prune was
performed as part of this audit.

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
The exact-composition cohort now contains four attempts and 397 unique
contiguous receipts. Backend health remained `healthy` with database/Docker
checks `ok`, Scheduler remained in `dual_canary`, and no active Task or Issue
lock remained.

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
That row is Provider 11; it is referenced by 19 historical Tasks and their
Profile Snapshots, while no Issue currently selects it as a default Provider.
The existing foreign keys use `SET NULL`, so the migration would preserve the
Tasks but clear their editable `provider_id` association; the immutable
Snapshot evidence must be checked again after the migration.

The 078 migration tests and focused lint pass (`6 passed`, Ruff clean); the
combined Provider/Endpoint/Runtime/migration regression set also passes (`81
passed`). No migration was run on the development Host. Before any `v2_only` cutover, the
maintenance owner must back up the database, execute the reviewed target
revision once, confirm the expected Provider cleanup, and repeat Profile,
Bundle, and relevant Task verification; the current generation-73 evidence
was recorded against revision 077 and cannot silently be reused as post-
migration proof.
