# Open-Harness V2 R4.5 Security and Release Audit

**Date:** 2026-09-04

**Scope:** Current development Host `192.168.50.129`, the post-fix frozen R4
candidate, and repository-side release checks. This is an audit record, not a
security approval or an independent R4.6 go/no-go decision.

The prior Profile-4 candidate was superseded after commit `8110afa0` changed
the Codex Adapter's model projection. The current candidate is Profile 4
generation `72` with Runtime Bundle 163; the exact identity and Task 368
validation are recorded in the
[R4.3/R4.4 live Host evidence](2026-09-04-open-harness-v2-r4.3-r4.4-live-host.md).
Tasks 369 and 370 were additional negative backend-restart probes on the same
Bundle; both were bounded as upstream `rate_limited` and do not constitute a
reconnect or release-safety pass.

## Checks completed

| Check | Result | Boundary |
| --- | --- | --- |
| `python3 scripts/harness-probes/v2/secret-scan.py` | passed, `findings=0` | Repository candidate only; it does not replace a Provider/GitLab access audit |
| `backend/.venv/bin/python -m pytest backend/tests/unit/test_codex_harness_adapter.py -q` | passed, 33 tests | Covers the post-fix Codex `OPENAI_MODEL` projection and V2 envelope/result mapping |
| Affected Bundle/Profile/Scheduler/notification/freeform regression set | passed, 227 tests | Re-checks the source/binding/runtime paths affected by the post-fix candidate |
| Backend focused regression | passed, 39 `test_issues_api.py` tests | Covers the current `task_mode` serialization fix |
| Frontend unit suite | passed, 80 files / 1692 tests | Includes structured SSE stale-source and mobile safe-area regression coverage |
| Frontend production build | passed | Vite emitted only the existing large-chunk warning |
| Backend lint | passed | `make lint-backend` |
| Remote Docker state | near capacity, not full | The final nginx-only deployment recheck reports `df -h /` at 61G total / 58G used / 3.6G available (95%) and `df -ih /` at 22% inode use; `docker system df` reports Images 12.41GB / 6.698GB reclaimable, containers 28.27MB, volumes 1.639GB, and BuildKit 6.526GB. No cleanup was performed because the disk was not full. |
| Current Kit archive reconstruction and V2 release preflight | passed, not signed | The installed `0.6.12-linux-amd64-c33dbf86951b` Kit was streamed into a temporary `518M` archive; archive SHA-256 `2d3ee7f81525d465731344571cbf5bd93a0cd94bb6cf16f5a4d5512d5c0a25a6`, manifest SHA-256 `c33dbf86951bed6e3b4de1897313725f14f00006dc51fb300e7b821bb47e17bd`, content inventory `7630f086800c95f851db8c9351638868ab60ac33fb3bfe22f9f2f5c8dcdc98a1`; `deploy/scripts/preflight-v2-release.sh` passed against the target daemon and Worker image repo digest `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`. The temporary archive is not a release-owner-signed package and is not committed. |
| Profile re-verification and live post-fix smoke | passed | Profile 4 generation 72 completed four-Harness Verify; Task 368 completed on Bundle 163 with the expected model field |
| Remote execution mode | unchanged | `HARNESS_EXECUTION_MODE=dual_canary`; no `v2_only` switch was attempted |

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
The database snapshot has 339 Tasks, zero `pending`/`queued`/`running` Tasks,
zero `issue_execution_locks`, zero Mattermost notification profiles, and zero
notification deliveries. These are current Host observations; they do not
replace the missing live alert delivery or independent release sign-off.

The current development-Host Provider inventory was checked without reading
credentials or URL paths: enabled Providers 3–6 resolve to `opencode.ai`, and
enabled Providers 7–12 resolve to `openrouter.ai`; the only fixture entry,
Provider 13, is disabled. No enabled local-only Provider is available. This is
an endpoint inventory for the release audit, not a least-privilege approval or
authorization to send another repository task to either external destination.

The current live evidence covers Pi, OpenCode, Claude, and Codex on Profile 4,
including the post-fix Codex Task 368 and the negative restart probes 369/370;
the known non-success outcomes were correctly bounded as upstream/provider
availability failures (`rate_limited`, selected-model `engine_error`, or the
earlier real upstream 404). The detailed task, identity, archive, raw-log, and
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
   complete R4.3–R4.5 checklist. The two upstream rate-limit failures are not
   P0/P1 evidence by themselves, but they also do not constitute a formal
   zero-blocker sign-off.

## R4.5 conclusion

**Partial evidence, not signed.** Repository secret scanning, local regression,
and remote-state checks pass. Provider/GitLab authorization and rotation,
release notes, retention/retirement, maintenance ownership, and independent
zero-P0/P1 approval remain open. R4.6 therefore has no recorded decision, and
the system must remain in `dual_canary`.

No `v2_only` cutover, maintenance-window action, or broad Docker prune was
performed as part of this audit.
